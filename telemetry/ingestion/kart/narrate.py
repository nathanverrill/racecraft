"""narrate.py - Stage B end: TTS race-engineer narration synced to the best-lap replay.

Builds narration BEATS from coaching.json + analytics.json + render.json, times them to
the best lap's corner apexes, synthesizes each with macOS `say` (offline, reproducible;
override via env KART_TTS), lays them on a timeline, DUCKS the drift-corrected engine
audio under speech, and writes:
  dataset/render/narration.wav   (engine ducked + voice, lap-window length)
  dataset/render/captions.json   (beat text + start/end for subtitles)

The narrated replay video is then exported with --audio narration.wav.
Honest: uses only validated facts (lap/sector times, consistency, impacts, cues).
"""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from common import OUTPUT, load_json, write_json
import timesheet as ts_mod


def say_to_wav(text, out_wav, voice=None):
    voice = voice or "Daniel"   # crisp British, broadcast-ish; fallback handled below
    aiff = out_wav.with_suffix(".aiff")
    try:
        subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
    except subprocess.CalledProcessError:
        subprocess.run(["say", "-o", str(aiff), text], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(aiff),
                    "-ar", "44100", "-ac", "1", str(out_wav)], check=True)
    aiff.unlink(missing_ok=True)
    # duration
    d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", str(out_wav)],
                       capture_output=True, text=True).stdout.strip()
    return float(d or 0)


def build_beats(D, C, ref_lap):
    A = D["analytics"]
    s = D["series"]
    idx = [i for i, l in enumerate(s["lap"]) if l == ref_lap]
    t = np.array(s["t"]); t0 = t[idx[0]]
    x = np.array(s["x"]); y = np.array(s["y"])
    apex_t = {}
    for ap in D["apexes"]:
        di = (x[idx] - ap["x"]) ** 2 + (y[idx] - ap["y"]) ** 2
        apex_t[ap["num"]] = float(t[idx[int(np.argmin(di))]] - t0)

    cue_lists = {c["num"]: c["cues"] for c in C.get("best_practice_cues", [])}
    score_by_turn = {tc["num"]: tc["consistency_score"] for tc in C["turn_consistency"]}
    tc_by_num = {tc["num"]: tc for tc in C["turn_consistency"]}

    def short_cue(num, used_phrases):
        """Pick a concise, NON-repeating cue for this turn; fall back to a data line."""
        for cue in cue_lists.get(num, []):
            short = cue.split(" — ")[-1] if " — " in cue else cue
            short = short.split(".")[0].strip().rstrip(",")
            # shorten common long phrases to punchy coaching
            short = short.replace("pick ONE reference (brake marker, apex kerb, exit point) and repeat it every lap",
                                  "lock one reference and repeat it")
            short = short.replace("commit to a repeatable minimum speed; trail-brake smoothly to the apex rather than braking different amounts each lap",
                                  "commit to one repeatable minimum speed")
            short = short.replace("aim to be at a wide-open throttle earlier; a good exit pays down the whole next straight",
                                  "get to full throttle earlier on exit")
            short = short.replace("Carry more minimum speed; brake later but lighter, get the car rotated and back to throttle earlier",
                                  "carry more minimum speed, brake lighter")
            short = short[:70]
            if short.lower() not in used_phrases:
                used_phrases.add(short.lower())
                return short
        tc = tc_by_num.get(num, {})
        return f"apex around {tc.get('apex_speed_mph_mean', 0):.0f}, make it repeatable"

    beats = []
    beats.append((0.0, f"Okay Nathan, kart nineteen. Best lap {A['actual_best_lap_s']:.1f}. "
                       f"Theoretical best {A['theoretical_best_lap_s']:.1f}. "
                       f"Here's where the time is."))
    weak = sorted(C["turn_consistency"], key=lambda c: c["consistency_score"])[:4]
    weak_nums = [w["num"] for w in weak]
    spoken = set(); used_phrases = set()
    for num in sorted(apex_t, key=lambda n: apex_t[n]):
        at = apex_t[num]
        if at < 2 or at > (A["actual_best_lap_s"] - 3):
            continue
        if num in weak_nums and num not in spoken:
            beats.append((at, f"Turn {num}. {short_cue(num, used_phrases)}."))
            spoken.add(num)
        if len(spoken) >= 3:
            break
    # closing
    opp = A["opportunity_ranking"][0]
    beats.append((A["actual_best_lap_s"] - 2.5,
                  f"Focus {opp['name'].split('(')[0].strip()}. "
                  f"About {opp['opportunity_s']:.1f} seconds there. Let's go again."))
    beats.sort()
    return beats


def run(venue="gateway-kartplex", voice=None):
    print("=" * 64); print(f"[narrate] Stage B  venue={venue}"); print("=" * 64)
    import os
    voice = voice or os.environ.get("KART_TTS_VOICE")
    sheets = {s["session_key"]: s for s in ts_mod.run(venue)}
    for key in sheets:
        ds = OUTPUT / venue / key / "dataset"
        rdir = ds / "render"
        if not (rdir / "render.json").exists():
            continue
        D = load_json(rdir / "render.json")
        C = load_json(ds / "coaching.json")
        ref = D["analytics"]["reference_lap"]
        # best-lap window (absolute session seconds)
        s = D["series"]; idx = [i for i, l in enumerate(s["lap"]) if l == ref]
        t = s["t"]; abs0, abs1 = t[idx[0]], t[idx[-1]]
        lap_dur = abs1 - abs0
        beats = build_beats(D, C, ref)

        tmp = Path(tempfile.mkdtemp())
        captions, inputs, filters = [], [], []
        # input 0 = engine audio window (extracted from session.wav)
        eng = tmp / "engine.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{abs0:.3f}",
                        "-t", f"{lap_dur:.3f}", "-i", str(rdir / "session.wav"),
                        "-ar", "44100", "-ac", "1", str(eng)], check=True)
        beat_wavs = []
        for bi, (bt, text) in enumerate(beats):
            bw = tmp / f"b{bi}.wav"
            dur = say_to_wav(text, bw, voice)
            beat_wavs.append((bt, dur, bw, text))
            captions.append({"t": round(bt, 2), "end": round(bt + dur, 2), "text": text})

        # mix: duck engine to -10dB, overlay each beat with adelay
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(eng)]
        for _, _, bw, _ in beat_wavs:
            cmd += ["-i", str(bw)]
        fc = "[0:a]volume=0.32[eng];"
        labels = ["[eng]"]
        for i, (bt, dur, bw, _) in enumerate(beat_wavs, start=1):
            delay = int(bt * 1000)
            fc += f"[{i}:a]adelay={delay}|{delay},volume=1.6[v{i}];"
            labels.append(f"[v{i}]")
        fc += "".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0[out]"
        out_wav = rdir / "narration.wav"
        cmd += ["-filter_complex", fc, "-map", "[out]", "-ar", "44100", "-ac", "2",
                str(out_wav)]
        subprocess.run(cmd, check=True)
        write_json(rdir / "captions.json",
                   {"session_key": key, "lap": ref, "lap_window_abs": [abs0, abs1],
                    "captions": captions})
        print(f"[narrate] {key}: {len(beats)} beats -> narration.wav ({lap_dur:.1f}s), captions.json")
        for c in captions:
            print(f"    {c['t']:5.1f}s  {c['text']}")
    print("-" * 64); print("[narrate] STATUS: PASS"); print("-" * 64)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "gateway-kartplex")
