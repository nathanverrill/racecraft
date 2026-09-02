"""Per-session configuration. Switch sessions by editing the ACTIVE block.

Same track (WWT Raceway / Kartplex T1) -> gate & sector fractions carry over;
only the time window, official lap times, and best lap change per session.
All times are `seconds_elapsed` (recording-relative).
"""
import numpy as np

# ----- start/finish gate (same track, validated session 1 RMSE 0.224s) -----
GATE_XY = np.array([12.0, -12.0])
GATE_DIR = np.array([-1.0, 0.0])      # West crossing
GATE_HALF_WIDTH = 12.0

# ----- sectors: S1 esses, S2 lead-in+straight, S3 hairpin+descent -----
SECTOR_FRAC = [0.0, 0.33, 0.63, 1.0]

# ===== ACTIVE SESSION =====
SESSION = "session1_240pm"
WINDOW_START = 56.0
WINDOW_END   = 845.0
OFFICIAL = [42.450,41.136,49.209,41.834,41.564,42.189,41.056,
            40.968,42.535,42.583,40.519,53.899,41.600,46.750]
BEST_LAP = 11


# ===== SESSION 1 (2:40 PM) - for reference =====
# WINDOW_START = 56.0; WINDOW_END = 845.0
# OFFICIAL = [42.450,41.136,49.209,41.834,41.564,42.189,41.056,
#             40.968,42.535,42.583,40.519,53.899,41.600,46.750]  # 14 laps
# BEST_LAP = 11   # 40.519s
