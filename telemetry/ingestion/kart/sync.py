"""sync.py - Stage A Step 4 (audio<->sensor clock sync).

Fit  sensor_t = a*audio_t + b  between the audio container clock and the sensor
master clock, by measuring how the LAG between two loudness envelopes GROWS across
the recording (the 0.193% audio-clock drift = a growing lag, not a constant offset):

  - SENSOR clock: Microphone.csv dBFS (seconds_elapsed, ~9.5 Hz) -> linear amplitude
  - AUDIO  clock: RMS envelope of Microphone.mp4 (ffmpeg PCM), framed @ FS_ENV Hz

Method:
  1) Build both envelopes on a uniform FS_ENV grid.
  2) Slide a short AUDIO window across the SENSOR envelope in several places spanning
     the whole recording; at each, cross-correlate to get  lag = sensor_t - audio_t.
  3) Robustly regress  lag(audio_t) = (a-1)*audio_t + b  (Theil-Sen / least squares on
     high-score windows). Slope => (a-1) (the drift), intercept => b.

EXPECT a ~ 1.0019 (sensor runs ~0.193% longer than audio; lag grows ~+4.2s over ~36min).
Low-confidence (few good windows / poor scores) -> flag; do NOT fabricate.

Output: output/<venue>/raw/sync.json
"""
from __future__ import annotations
import subprocess
import sys
import numpy as np
import pandas as pd

from common import RAW_SESSIONS, OUTPUT, write_json, load_json

FS_ENV = 50.0          # envelope grid Hz (finer => better lag resolution: 0.02s)
WIN_S = 120.0          # audio window length for each local lag measurement
STEP_S = 60.0          # spacing between window starts
SEARCH_S = 12.0        # +/- search range for lag (covers max drift)
MIN_SCORE = 0.30       # keep windows with normalized xcorr peak above this


def audio_rms_envelope(mp4_path, fs_env=FS_ENV):
    sr = 16000
    cmd = ["ffmpeg", "-v", "error", "-i", str(mp4_path),
           "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    hop = int(round(sr / fs_env))
    n = len(x) // hop
    x = x[: n * hop].reshape(n, hop)
    rms = np.sqrt(np.mean(x.astype(np.float64) ** 2, axis=1) + 1e-12)
    t = np.arange(n) / fs_env
    return t, rms


def sensor_loudness_envelope(mic_csv, fs_env=FS_ENV):
    mic = pd.read_csv(mic_csv)
    se = mic.seconds_elapsed.values.astype(float)
    amp = 10.0 ** (mic.dBFS.values.astype(float) / 20.0)
    t = np.arange(se.min(), se.max(), 1.0 / fs_env)
    env = np.interp(t, se, amp)
    return t, env


def _z(x):
    x = x - x.mean()
    s = x.std()
    return x / s if s > 0 else x


def local_lag(t_aud, env_aud, t_sen, env_sen, t0, win_s, search_s, fs):
    """Return (lag_seconds = sensor_t - audio_t at ~t0, normalized peak score)."""
    ai = (t_aud >= t0) & (t_aud < t0 + win_s)
    aw = _z(env_aud[ai])
    if len(aw) < 50:
        return None
    lo = t0 - search_s
    hi = t0 + win_s + search_s
    si = (t_sen >= lo) & (t_sen < hi)
    sw = _z(env_sen[si])
    if len(sw) < len(aw) + 2:
        return None
    cc = np.correlate(sw, aw, mode="valid")  # len = len(sw)-len(aw)+1
    k = int(np.argmax(cc))
    score = float(cc[k] / len(aw))
    sens_start = t_sen[si][0]
    matched_sensor_t = sens_start + k / fs       # sensor time aligned to audio t0
    lag = matched_sensor_t - t0                  # sensor_t - audio_t
    return lag, score


def run(venue: str = "gateway-kartplex") -> dict:
    print("=" * 64)
    print(f"[sync] STEP 4  venue={venue}")
    print("=" * 64)
    ingest = load_json(OUTPUT / venue / "raw" / "ingest.json")
    sessions = load_json(OUTPUT / venue / "raw" / "sessions.json")["sessions"]

    # sync is recording-level; fit once per unique recording that actually hosts a
    # matched session (so we don't waste time on recordings with no telemetry match).
    from pathlib import Path
    roots = {}
    for ses in sessions:
        root = ses.get("session_dir") or str(RAW_SESSIONS / ingest["zip_stem"])
        roots[root] = ses.get("recording", Path(root).name)

    per_recording = {}
    for root, name in roots.items():
        print(f"[sync] recording: {name}")
        per_recording[root] = _fit_one(Path(root), venue, name)

    # default = first recording's fit (back-compat); full map under per_recording
    first_root = next(iter(roots))
    result = dict(per_recording[first_root])
    result["per_recording"] = per_recording
    write_json(OUTPUT / venue / "raw" / "sync.json", result)
    return result


def _fit_one(sd, venue, name) -> dict:
    t_aud, env_aud = audio_rms_envelope(sd / "Microphone.mp4")
    t_sen, env_sen = sensor_loudness_envelope(sd / "Microphone.csv")
    audio_dur = float(t_aud[-1] + 1.0 / FS_ENV)
    mic_span = float(t_sen[-1] - t_sen[0])
    print(f"[sync] audio dur={audio_dur:.2f}s  mic.csv span={mic_span:.2f}s  "
          f"fs_env={FS_ENV}Hz")
    print(f"[sync] naive ratio mic_span/audio_dur={mic_span/audio_dur:.5f} "
          f"(~{(mic_span/audio_dur-1)*100:.3f}% expected drift)")

    # measure local lag across the whole recording
    starts = np.arange(t_aud[0], audio_dur - WIN_S, STEP_S)
    ts, lags, scores = [], [], []
    for s0 in starts:
        res = local_lag(t_aud, env_aud, t_sen, env_sen, s0, WIN_S, SEARCH_S, FS_ENV)
        if res is None:
            continue
        lag, sc = res
        ts.append(s0 + WIN_S / 2.0)   # center time of the window (audio clock)
        lags.append(lag)
        scores.append(sc)
    ts = np.array(ts); lags = np.array(lags); scores = np.array(scores)
    good = scores >= MIN_SCORE
    print(f"[sync] lag windows: {len(ts)} total, {good.sum()} with score>={MIN_SCORE}")
    for tt, lg, sc in zip(ts, lags, scores):
        mark = "*" if sc >= MIN_SCORE else " "
        print(f"   {mark} t~{tt:7.1f}s  lag={lg:+.3f}s  score={sc:.3f}")

    tg, lg = ts[good], lags[good]
    if len(tg) < 3:
        a, b, r = 1.0, float(np.median(lags)) if len(lags) else 0.0, 0.0
        low_conf = True
        slope = 0.0
    else:
        # weighted least squares: lag = slope*audio_t + b0 ; a = 1+slope
        W = scores[good]
        A = np.vstack([tg, np.ones_like(tg)]).T
        Wm = np.diag(W)
        coef = np.linalg.lstsq(A.T @ Wm @ A, A.T @ Wm @ lg, rcond=None)[0]
        slope, b = float(coef[0]), float(coef[1])
        a = 1.0 + slope
        pred = A @ coef
        ss_res = np.sum(W * (lg - pred) ** 2)
        ss_tot = np.sum(W * (lg - np.average(lg, weights=W)) ** 2)
        r = float(np.sqrt(max(0.0, 1 - ss_res / ss_tot))) if ss_tot > 0 else 0.0
        low_conf = (r < 0.5) or (float(np.mean(W)) < 0.4)

    print(f"[sync] FIT: sensor_t = {a:.6f}*audio_t + {b:.4f}   "
          f"(drift {slope*100:+.3f}%/clock, fit R={r:.3f})")

    result = {
        "venue": venue,
        "recording": name,
        "method": "growing-lag regression: local xcorr(Microphone.csv dBFS amp, "
                  "audio RMS env) across recording; WLS lag=(a-1)*audio_t+b",
        "model": "sensor_t = a*audio_t + b",
        "a": a, "b": b, "fit_R": r,
        "drift_pct": slope * 100.0,
        "audio_dur_s": audio_dur, "mic_span_s": mic_span,
        "naive_ratio": mic_span / audio_dur,
        "n_windows_used": int(good.sum()),
        "mean_window_score": float(np.mean(scores[good])) if good.any() else 0.0,
        "fs_env_hz": FS_ENV,
        "low_confidence": bool(low_conf),
    }

    drift_ok = 0.0010 <= slope <= 0.0030
    print(f"[sync] {name} VALIDATE: drift={slope*100:.3f}% in_range={drift_ok} "
          f"fit_R={r:.3f} windows={int(good.sum())} low_conf={low_conf} "
          f"{'PASS' if (drift_ok and not low_conf) else 'CHECK'}")
    return result


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "gateway-kartplex")
