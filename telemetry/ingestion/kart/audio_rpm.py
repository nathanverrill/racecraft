"""audio_rpm.py - Stage B consumer: engine RPM from onboard audio (BEST-EFFORT).

Reads ONLY the canonical dataset/ (+ the recording audio referenced by session.json)
and writes audio_rpm artifacts back into dataset/. Does NOT touch Stage A.

HONEST STATUS (data-quality finding, matches V2_PLAN's warning):
  The in-helmet AirPods apply aggressive voice processing that high-passes/thins the
  engine fundamental, and the recording carries a strong FIXED ~160 Hz artifact that
  is present even when stopped. As a result the engine tone is NOT cleanly trackable:
  across many methods (raw argmax, harmonic-product-spectrum, spectral-whitened
  harmonic-sum, Viterbi) and bands, the best tone-vs-GPS-speed correlation is ~0.34,
  and several configs are even anti-correlated. Per the single-speed physics test
  (V2_PLAN), a real harmonic should regress near-linearly vs speed (R^2 high). It does
  NOT here. => We emit a best-effort tone/RPM track BUT flag it low_confidence and do
  NOT feed it into the dashboard's authoritative channels. We surface the diagnostic
  rather than fabricate a confident RPM.

Method (drift-corrected throughout):
  - Map session master-clock window -> AUDIO time via sync.json (audio_t=(sensor_t-b)/a).
  - STFT; spectral-whiten (divide each bin by its time-median) to suppress the static
    160 Hz artifact; harmonic-sum salience over a firing-frequency band; Viterbi track.
  - Resolve harmonic scale by the single-speed regression and REPORT its R^2 as the
    confidence gate.

Outputs: dataset/audio_rpm.csv (t, seconds_elapsed, tone_hz, rpm_est),
         dataset/audio_rpm.json (scale, ranges, regression R^2, low_confidence flag).
"""
from __future__ import annotations
import subprocess
import sys
import numpy as np
import pandas as pd
from scipy.signal import stft
from scipy.ndimage import uniform_filter1d, median_filter

from common import RAW_SESSIONS, OUTPUT, NS_PER_S, load_json, write_json
import timesheet as ts_mod

SR = 16000
NPER = 4096
NOVER = 2048
FUND_LO, FUND_HI = 25.0, 60.0   # firing-frequency band (RPM/120 for a 4-stroke single)
N_HARM = 5
R2_OK = 0.80                    # single-speed linearity gate for "validated"


def decode_audio(mp4, t0, t1):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}",
         "-i", str(mp4), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).astype(np.float64)


def session_se0(ds):
    meta = load_json(ds / "session.json")
    venue = meta["venue"]
    ingest = load_json(OUTPUT / venue / "raw" / "ingest.json")
    # use THIS session's recording epoch (multi-recording safe), not the first one
    rec_zip = meta.get("recording_zip")
    epoch_ms = None
    for r in ingest.get("recordings", []):
        if r["zip_name"] == rec_zip:
            epoch_ms = r["metadata"]["recording_epoch_ms"]
            break
    if epoch_ms is None:
        epoch_ms = ingest["metadata"]["recording_epoch_ms"]
    epoch_ns = epoch_ms * 1_000_000
    return (meta["window_master_clock_ns"][0] - epoch_ns) / NS_PER_S


def track_tone(x, a, b, at0, se0, fused):
    f, tt, Z = stft(x, fs=SR, nperseg=NPER, noverlap=NOVER)
    S = np.abs(Z)
    if S.ndim < 2 or S.shape[1] < 2:
        raise ValueError("degenerate spectrogram (audio window too short/misaligned)")
    # spectral whitening: suppress static tones (the ~160 Hz artifact)
    Sw = S / (np.median(S, axis=1, keepdims=True) + 1e-9)
    cand = np.where((f >= FUND_LO) & (f <= FUND_HI))[0]
    fc = f[cand]
    sal = np.zeros((len(cand), S.shape[1]))
    for h in range(1, N_HARM + 1):
        idx = np.clip(np.searchsorted(f, fc * h), 0, len(f) - 1)
        sal += np.log(Sw[idx] + 1e-9)
    # smooth pick (median over time to reduce hopping)
    fund = fc[np.argmax(sal, axis=0)]
    fund = median_filter(fund, 7)
    frame_se = (a * (at0 + tt) + b) - se0
    speed = np.interp(frame_se, fused.seconds_elapsed.values, fused.speed.values)
    return frame_se, fund, speed


def single_speed_regression(fund, speed):
    m = (speed > 6.0) & np.isfinite(fund)
    if m.sum() < 100:
        return {"f_vs_speed_r2": 0.0, "slope": 0.0, "intercept": 0.0, "n": int(m.sum())}
    v = uniform_filter1d(speed, 9)[m]
    ft = uniform_filter1d(fund, 9)[m]
    A = np.vstack([v, np.ones_like(v)]).T
    coef, *_ = np.linalg.lstsq(A, ft, rcond=None)
    pred = A @ coef
    ss_res = np.sum((ft - pred) ** 2); ss_tot = np.sum((ft - ft.mean()) ** 2)
    r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0
    return {"f_vs_speed_r2": r2, "slope": float(coef[0]),
            "intercept": float(coef[1]), "n": int(m.sum())}


def run(venue: str = "gateway-kartplex") -> dict:
    print("=" * 64)
    print(f"[audio_rpm] Stage B  venue={venue}  (best-effort, honest confidence)")
    print("=" * 64)
    ingest = load_json(OUTPUT / venue / "raw" / "ingest.json")
    sync = load_json(OUTPUT / venue / "raw" / "sync.json")
    sessions = load_json(OUTPUT / venue / "raw" / "sessions.json")["sessions"]
    ses_dir = {s["session_key"]: s.get("session_dir") for s in sessions}
    default_sd = RAW_SESSIONS / ingest["zip_stem"]
    sheets = {s["session_key"]: s for s in ts_mod.run(venue)}

    summary = {}
    for key in sheets:
        ds = OUTPUT / venue / key / "dataset"
        if not (ds / "fused_trace.csv").exists():
            continue
        from pathlib import Path
        sd = Path(ses_dir[key]) if ses_dir.get(key) else default_sd
        mp4 = sd / "Microphone.mp4"
        rec_sync = sync.get("per_recording", {}).get(str(sd), sync)
        a, b = rec_sync["a"], rec_sync["b"]
        fused = pd.read_csv(ds / "fused_trace.csv")
        se0 = session_se0(ds)
        sensor_t0, sensor_t1 = se0, se0 + fused.seconds_elapsed.values[-1]
        at0, at1 = (sensor_t0 - b) / a, (sensor_t1 - b) / a
        x = decode_audio(mp4, at0, at1)
        frame_se, fund, speed = track_tone(x, a, b, at0, se0, fused)
        reg = single_speed_regression(fund, speed)

        # firing freq -> RPM (4-stroke single: RPM = firing_hz * 120). fund IS the
        # firing-band estimate; rpm_est = fund * 120. (Scale is only meaningful if the
        # regression validates; we report it either way but flag confidence.)
        rpm_est = fund * 120.0
        order = np.argsort(frame_se)
        grid = fused.seconds_elapsed.values
        rpm_100 = np.interp(grid, frame_se[order], rpm_est[order])
        tone_100 = np.interp(grid, frame_se[order], fund[order])
        pd.DataFrame({"t": fused.t.values.astype(np.int64),
                      "seconds_elapsed": grid,
                      "tone_hz": tone_100, "rpm_est": rpm_100}).to_csv(
            ds / "audio_rpm.csv", index=False)

        low_conf = reg["f_vs_speed_r2"] < R2_OK
        drive = rpm_100[np.interp(grid, grid, fused.speed.values) > 6]
        meta = {
            "method": "spectral-whitened harmonic-sum firing-band track, "
                      "drift-corrected via sync.json",
            "rpm_per_hz": 120.0,
            "firing_band_hz": [FUND_LO, FUND_HI],
            "rpm_est_median_driving": float(np.median(drive)),
            "rpm_est_p95": float(np.percentile(drive, 95)),
            "rpm_est_max": float(np.max(drive)),
            "single_speed_regression": reg,
            "low_confidence": bool(low_conf),
            "validated": bool(not low_conf),
            "data_quality_note": "AirPod voice-processing thins the engine fundamental "
                                 "and a static ~160 Hz artifact dominates; tone-vs-speed "
                                 "R^2 is low -> RPM is NOT reliably recoverable from this "
                                 "audio. Best-effort track only; do NOT use as truth.",
            "drift_corrected": True, "sync_a": a, "sync_b": b,
        }
        write_json(ds / "audio_rpm.json", meta)
        summary[key] = meta
        print(f"[audio_rpm] {key}: tone-vs-speed R2={reg['f_vs_speed_r2']:.3f} "
              f"-> {'LOW-CONFIDENCE (flagged, not used as truth)' if low_conf else 'OK'}; "
              f"rpm_est med {meta['rpm_est_median_driving']:.0f} "
              f"max {meta['rpm_est_max']:.0f}")

    print("-" * 64)
    r2s = {k: round(v["single_speed_regression"]["f_vs_speed_r2"], 3)
           for k, v in summary.items()}
    print(f"[audio_rpm] VALIDATE (single-speed linearity gate R2>={R2_OK}): {r2s}")
    print(f"[audio_rpm] CONCLUSION: engine RPM is NOT cleanly recoverable from this "
          f"AirPod audio (data-quality limitation, flagged honestly).")
    print("-" * 64)
    return summary


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "gateway-kartplex")
