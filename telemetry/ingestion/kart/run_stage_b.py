"""run_stage_b.py - chain all Stage B consumers for a venue (reads dataset/, writes
consumer artifacts; never touches Stage A).

  python kart/run_stage_b.py [venue]

Order: audio_rpm -> sectors_timing -> analytics -> coaching -> render_artifact
       -> build_dashboards (copies the interactive HTML + data into each render/ dir).
Video export is run separately (it's slow); see kart/stage_b/export_video.py.
"""
import sys

import audio_rpm
import sectors_timing
import analytics
import coaching
import render_artifact
import ghost
import narrate
import sector1_coaching
sys.path.insert(0, __file__.rsplit("/", 1)[0] + "/stage_b")
import build_dashboards  # noqa: E402
import build_home  # noqa: E402


def main(venue="gateway-kartplex"):
    audio_rpm.run(venue)        # engine RPM (flagged low-confidence)
    sectors_timing.run(venue)   # 3 sectors + per-lap sector table
    analytics.run(venue)        # consistency + clean-lap stats
    coaching.run(venue)         # debrief + strategy
    render_artifact.run(venue)  # 30Hz render.json + drift-corrected wav
    ghost.run(venue)
    sector1_coaching.run(venue)  # sector-1-specific coaching artifact            # ghost-battle (you vs ideal) data
    try:
        narrate.run(venue)      # TTS race-engineer narration (macOS say) -> narration.wav
    except Exception as e:
        print(f"[run_stage_b] narration skipped ({e})")
    build_dashboards.run(venue)  # interactive HTML into render/
    build_home.run(venue)        # regenerate the sessions home page (all venues)
    print("\n[run_stage_b] Stage B consumers complete for venue:", venue)
    print("[run_stage_b] View dashboards:")
    print(f"   ingestion/.venv/bin/python -m http.server 8800 -d ingestion/output/{venue}")
    print("[run_stage_b] Export video, e.g.:")
    print("   ingestion/.venv/bin/python ingestion/kart/stage_b/export_video.py \\")
    print(f"     ingestion/output/{venue}/<session>/dataset/render --html onboard.html --lap N")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "gateway-kartplex")
