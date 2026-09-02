"""ingest.py - Stage A Step 1.

Scan inbox/<venue>/ FLAT. Inputs = one-or-more .zip (Sensor Logger recordings) +
one-or-more pre-extracted timing-sheet *.json. IGNORE everything else gracefully
(.DS_Store, images, stray files). NO vision / NO image classification.

- Unzip each recording -> raw_sessions/<zip_stem>/ (skip if already present).
- Some Sensor Logger exports nest all CSVs under a single top-level folder inside the
  zip; auto-detect the real session root (the dir that contains Metadata.csv).
- Read Metadata.csv (device, schema v, recording epoch+tz, sensor list/rates) per
  recording and compute the absolute time span from Location.csv.
- Confirm required CSVs + Microphone.mp4 are present per recording.
- Count timing-sheet JSON files.
- VALIDATE (data-driven): >=1 recording with all required files; >=1 timesheet;
  GPS/IMU row counts sane.

Writes: output/<venue>/raw/ingest.json  (recordings[] + legacy single-recording keys)
"""
from __future__ import annotations
import csv
import sys
import zipfile
from pathlib import Path

from common import (INBOX, RAW_SESSIONS, OUTPUT, REQUIRED_CSVS, AUDIO_FILE,
                    METADATA_FILE, NS_PER_S, write_json)

IMAGE_EXTS = {".heic", ".jpg", ".jpeg", ".png"}


def scan_inbox(venue_dir: Path) -> dict:
    zips, sheets, ignored = [], [], []
    for f in sorted(venue_dir.iterdir()):
        if f.is_dir():
            continue
        ext = f.suffix.lower()
        if ext == ".zip":
            zips.append(f)
        elif ext == ".json":
            sheets.append(f)
        else:
            ignored.append(f.name)  # .DS_Store, images, etc - ignored gracefully
    if not zips:
        raise RuntimeError(f"No .zip recording found in {venue_dir}")
    print(f"[ingest] zips:   {[z.name for z in zips]}")
    print(f"[ingest] sheets: {[s.name for s in sheets]}")
    if ignored:
        print(f"[ingest] ignored (no vision): {ignored}")
    return {"zips": zips, "sheets": sheets, "ignored": ignored}


def unzip_recording(zip_path: Path) -> Path:
    stem = zip_path.stem
    session_dir = RAW_SESSIONS / stem
    if session_dir.exists() and any(session_dir.iterdir()):
        print(f"[ingest] raw_sessions/{stem}/ already present - skipping unzip")
    else:
        session_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(session_dir)
        print(f"[ingest] unzipped -> raw_sessions/{stem}/")
    return session_dir


def find_session_root(session_dir: Path) -> Path:
    """Return the dir actually holding Metadata.csv (handles a nested top folder)."""
    if (session_dir / METADATA_FILE).exists():
        return session_dir
    # search one/two levels down, skip __MACOSX
    for p in session_dir.rglob(METADATA_FILE):
        if "__MACOSX" in p.parts:
            continue
        return p.parent
    return session_dir


def read_metadata(root: Path) -> dict:
    meta_path = root / METADATA_FILE
    with open(meta_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    row = rows[0]
    names = [s.strip() for s in row.get("sensors", "").split("|") if s.strip()]
    rates = [r.strip() for r in row.get("sampleRateMs", "").split("|")]
    sensor_rates = {}
    for i, n in enumerate(names):
        r = rates[i] if i < len(rates) else ""
        sensor_rates[n] = int(r) if r.isdigit() else (r or None)
    meta = {
        "version": row.get("version"),
        "device": row.get("device name"),
        "recording_epoch_ms": int(row.get("recording epoch time", 0)),
        "recording_time": row.get("recording time"),
        "timezone": row.get("recording timezone"),
        "platform": row.get("platform"),
        "app_version": row.get("appVersion"),
        "standardisation": row.get("standardisation"),
        "platform_version": row.get("platform version"),
        "sensor_rates_ms": sensor_rates,
    }
    return meta


def check_required(root: Path) -> dict:
    present, missing = {}, []
    for fname in REQUIRED_CSVS + [AUDIO_FILE]:
        p = root / fname
        if p.exists():
            present[fname] = p.stat().st_size
        else:
            missing.append(fname)
    return {"present": list(present), "missing": missing, "sizes_bytes": present}


def count_rows(p: Path) -> int:
    with open(p, "rb") as f:
        return sum(1 for _ in f) - 1


def location_span(root: Path) -> dict:
    """First/last epoch-ns timestamp from Location.csv."""
    loc = root / "Location.csv"
    if not loc.exists():
        return {}
    first = last = None
    with open(loc, newline="") as f:
        rdr = csv.reader(f)
        next(rdr, None)  # header
        for r in rdr:
            if not r:
                continue
            try:
                t = int(r[0])
            except ValueError:
                continue
            if first is None:
                first = t
            last = t
    if first is None:
        return {}
    return {"t0_ns": first, "t1_ns": last,
            "dur_s": round((last - first) / NS_PER_S, 1)}


def ingest_recording(zip_path: Path) -> dict:
    session_dir = unzip_recording(zip_path)
    root = find_session_root(session_dir)
    meta = read_metadata(root)
    files = check_required(root)
    inv = {}
    for fname in REQUIRED_CSVS:
        p = root / fname
        if p.exists():
            inv[fname] = count_rows(p)
    span = location_span(root)
    loc_n = inv.get("Location.csv", 0)
    imu_n = inv.get("Accelerometer.csv", 0)
    rec = {
        "zip_name": zip_path.name,
        "zip_stem": zip_path.stem,
        "session_dir": str(session_dir),
        "root": str(root),
        "root_rel": str(root.relative_to(session_dir)) if root != session_dir else "",
        "metadata": meta,
        "required_files": {"present": files["present"], "missing": files["missing"]},
        "row_counts": inv,
        "span": span,
        "gps_rows": loc_n,
        "imu_rows": imu_n,
        "ok": (not files["missing"]) and loc_n > 500 and imu_n > 50000,
    }
    print(f"[ingest] {zip_path.name}: root='{rec['root_rel'] or '.'}' "
          f"required_missing={files['missing']} GPS={loc_n} IMU={imu_n} "
          f"span={span.get('dur_s')}s")
    return rec


def run(venue: str = "gateway-kartplex") -> dict:
    venue_inbox = INBOX / venue
    if not venue_inbox.exists():
        raise FileNotFoundError(f"venue inbox not found: {venue_inbox}")
    print("=" * 64)
    print(f"[ingest] STEP 1  venue={venue}")
    print("=" * 64)

    scan = scan_inbox(venue_inbox)
    recordings = [ingest_recording(z) for z in scan["zips"]]
    recordings.sort(key=lambda r: r["span"].get("t0_ns", 0))

    n_sheets = len(scan["sheets"])
    first = recordings[0]
    result = {
        "venue": venue,
        "recordings": recordings,
        # legacy single-recording keys (first recording) for back-compat consumers
        "zip_name": first["zip_name"],
        "zip_stem": first["zip_stem"],
        "session_dir": first["session_dir"],
        "metadata": first["metadata"],
        "timesheet_json": [s.name for s in scan["sheets"]],
        "n_timesheets": n_sheets,
        "ignored": scan["ignored"],
    }
    write_json(OUTPUT / venue / "raw" / "ingest.json", result)

    # ---- VALIDATION GATE (data-driven) ----
    ok = n_sheets >= 1 and any(r["ok"] for r in recordings)
    print("-" * 64)
    print(f"[ingest] VALIDATE: recordings={len(recordings)} "
          f"({sum(r['ok'] for r in recordings)} ok)  timesheets={n_sheets}")
    for r in recordings:
        print(f"         {r['zip_name']}: ok={r['ok']} span={r['span'].get('dur_s')}s")
    print(f"[ingest] STATUS: {'PASS' if ok else 'CHECK'}")
    print("-" * 64)
    result["validation_pass"] = ok
    return result


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "gateway-kartplex")
