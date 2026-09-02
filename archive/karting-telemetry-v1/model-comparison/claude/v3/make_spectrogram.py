#!/usr/bin/env python3
"""
make_spectrogram.py  --  turn the engine audio into an uploadable image
=======================================================================

Decodes the Sensor Logger Microphone.mp4 (or any audio file) and renders a
spectrogram PNG you can upload, instead of the big audio file itself. The image
shows the engine note and its harmonics over time, plus a loudness strip on top
so the driving stints stand out from the idle / walking-around stretches.

Usage
-----
    python make_spectrogram.py /path/to/SessionFolder          # finds Microphone.mp4
    python make_spectrogram.py /path/to/Microphone.mp4
    python make_spectrogram.py /path/to/audio --fmax 6000 --out engine.png

Needs: numpy, matplotlib, and ffmpeg on PATH (ffmpeg ships with most setups;
otherwise `brew install ffmpeg` / `apt install ffmpeg` / download from ffmpeg.org).
"""

import argparse
import os
import subprocess
import sys
import tempfile
import wave

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def find_audio(path):
    if os.path.isfile(path):
        return path
    if os.path.isdir(path):
        for n in ("Microphone.mp4", "Microphone.m4a", "Microphone.caf",
                  "Microphone.3gp", "Microphone.wav"):
            for f in os.listdir(path):
                if f.lower() == n.lower():
                    return os.path.join(path, f)
        # any audio-ish file
        for f in sorted(os.listdir(path)):
            if f.lower().endswith((".mp4", ".m4a", ".caf", ".wav", ".mp3", ".3gp")):
                return os.path.join(path, f)
    return None


def decode_to_wav(src, sr):
    """Use ffmpeg to decode `src` to a temporary mono WAV at sample rate `sr`."""
    if not _have("ffmpeg"):
        sys.exit("ffmpeg not found on PATH. Install it (ffmpeg.org / brew / apt) and retry.")
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    cmd = ["ffmpeg", "-y", "-i", src, "-ac", "1", "-ar", str(sr), "-vn", tmp.name]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        sys.exit("ffmpeg failed to decode the audio:\n" + r.stderr.decode("utf-8", "replace")[-800:])
    return tmp.name


def _have(exe):
    from shutil import which
    return which(exe) is not None


def read_wav(path):
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        nframes = w.getnframes()
        sampwidth = w.getsampwidth()
        raw = w.readframes(nframes)
    dtype = {1: np.int8, 2: np.int16, 4: np.int32}.get(sampwidth, np.int16)
    x = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    if dtype != np.int8:
        x /= float(np.iinfo(dtype).max)
    else:
        x = (x - 128) / 128.0
    return x, sr


def spectrogram(x, sr, ncols=2000, nfft=2048, fmax=8000):
    """Memory-light overview spectrogram: one nfft window every `hop` samples.
    Returns (Sdb, rms_db, freqs, times)."""
    n = len(x)
    nfft = min(nfft, 1 << int(np.floor(np.log2(max(256, n)))))
    hop = max(1, (n - nfft) // max(1, ncols))
    starts = hop * np.arange(ncols)
    starts = starts[starts + nfft <= n]
    if len(starts) < 2:
        starts = np.array([0])
    win = np.hanning(nfft).astype(np.float32)
    idx = starts[:, None] + np.arange(nfft)[None, :]
    frames = x[idx] * win
    S = np.fft.rfft(frames, axis=1)
    mag = np.abs(S).T                                   # (freq, time)
    rms = np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1)) + 1e-9
    rms_db = 20 * np.log10(rms)
    freqs = np.fft.rfftfreq(nfft, 1.0 / sr)
    times = starts / sr
    # dB, normalised to peak, clipped for contrast
    Sdb = 20 * np.log10(mag + 1e-9)
    Sdb -= Sdb.max()
    Sdb = np.clip(Sdb, -90, 0)
    if fmax:
        keep = freqs <= fmax
        Sdb = Sdb[keep]; freqs = freqs[keep]
    return Sdb, rms_db, freqs, times


def main():
    ap = argparse.ArgumentParser(description="Render an engine-audio spectrogram PNG for upload.")
    ap.add_argument("path", help="Session folder or an audio file (Microphone.mp4)")
    ap.add_argument("--sr", type=int, default=22050, help="Decode sample rate (default 22050)")
    ap.add_argument("--fmax", type=int, default=8000, help="Max frequency shown, Hz (default 8000)")
    ap.add_argument("--cols", type=int, default=2000, help="Time resolution / image columns (default 2000)")
    ap.add_argument("--out", default=None, help="Output PNG (default: <audio>_spectrogram.png next to it)")
    args = ap.parse_args()

    src = find_audio(args.path)
    if not src:
        sys.exit(f"No audio file found at {args.path}")
    print(f"Audio: {src}")

    wav = decode_to_wav(src, args.sr)
    try:
        x, sr = read_wav(wav)
    finally:
        try:
            os.unlink(wav)
        except OSError:
            pass
    dur = len(x) / sr
    print(f"Decoded {dur:.1f}s @ {sr} Hz mono ({len(x):,} samples)")

    Sdb, rms_db, freqs, times = spectrogram(x, sr, args.cols, fmax=args.fmax)
    tmin = times / 60.0

    fig = plt.figure(figsize=(14, 6.2), dpi=130)
    gs = fig.add_gridspec(2, 1, height_ratios=[1, 4], hspace=0.06)

    ax0 = fig.add_subplot(gs[0])
    ax0.plot(tmin, rms_db, lw=0.7, color="#19C3C9")
    ax0.fill_between(tmin, rms_db, rms_db.min(), color="#19C3C9", alpha=0.18)
    ax0.set_ylabel("loudness\n(dB)", fontsize=8)
    ax0.set_xlim(tmin.min(), tmin.max())
    ax0.tick_params(labelbottom=False, labelsize=8)
    ax0.set_title(f"{os.path.basename(src)}   ·   {dur/60:.1f} min   ·   engine audio spectrogram",
                  fontsize=11, loc="left")
    ax0.grid(alpha=0.15)

    ax1 = fig.add_subplot(gs[1], sharex=ax0)
    im = ax1.imshow(Sdb, origin="lower", aspect="auto", cmap="magma",
                    extent=[tmin.min(), tmin.max(), freqs.min(), freqs.max()/1000.0],
                    vmin=-90, vmax=0)
    ax1.set_ylabel("frequency (kHz)", fontsize=9)
    ax1.set_xlabel("time (minutes)", fontsize=9)
    ax1.tick_params(labelsize=8)
    cb = fig.colorbar(im, ax=[ax0, ax1], pad=0.01, fraction=0.035)
    cb.set_label("level (dB below peak)", fontsize=8)
    cb.ax.tick_params(labelsize=7)

    out = args.out or (os.path.splitext(src)[0] + "_spectrogram.png")
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    sz = os.path.getsize(out) / 1024
    print(f"\nWrote {out}  ({sz:.0f} KB)")
    print("Upload that PNG — it shows engine RPM/harmonics and where the driving stints are.")


if __name__ == "__main__":
    main()
