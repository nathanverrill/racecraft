"""Switch config to SESSION 1, re-run pipeline, render dashboard.
Written to run after the session-2 render completes (shares clipped/ & _frames/).
"""
import re, subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
cfg = HERE / "session_config.py"

# --- rewrite ACTIVE block to session 1 ---
txt = cfg.read_text()
s1 = '''SESSION = "session1_240pm"
WINDOW_START = 56.0
WINDOW_END   = 845.0
OFFICIAL = [42.450,41.136,49.209,41.834,41.564,42.189,41.056,
            40.968,42.535,42.583,40.519,53.899,41.600,46.750]
BEST_LAP = 11'''
# replace everything between the ACTIVE marker and the SESSION 1 ref comment
txt = re.sub(r"# ===== ACTIVE SESSION =====.*?(?=\n# ===== SESSION 1)",
             "# ===== ACTIVE SESSION =====\n" + s1 + "\n\n",
             txt, flags=re.S)
cfg.write_text(txt)
print("config -> session 1")

py = str(HERE.parent / ".venv/bin/python")
def run(args):
    print("RUN", args)
    subprocess.run([py] + args, cwd=str(HERE.parent), check=True)

# clear pycache so new config is picked up
for p in HERE.rglob("__pycache__"):
    subprocess.run(["rm", "-rf", str(p)])

run(["kart/fuse.py"])
run(["kart/laps.py"])
run(["kart/clip_session.py"])
run(["kart/dashboard.py", "--start", "0", "--end", "608.7",
     "--out", "session1_240pm_dashboard.mp4", "--fps", "30"])
print("SESSION 1 DONE")
