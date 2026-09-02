"""
Visualize the EKF-fused Position.csv against the raw GPS track.
Colors the fused racing line by speed.
"""

import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

EARTH_R = 6378137.0

# Usage: python3.11 plot_position.py [folder]   (e.g. session1)
BASE = sys.argv[1] if len(sys.argv) > 1 else "clean"
FUSED = f"{BASE}/Position.csv" if BASE != "clean" else "Position.csv"
LOC = f"{BASE}/Location.csv"
OUTIMG = f"{BASE}/position_plot.png" if BASE != "clean" else "position_plot.png"

fused = pd.read_csv(FUSED)
loc = pd.read_csv(LOC)
loc = loc[loc["horizontalAccuracy"] > 0].copy()

# Convert raw GPS to the same ENU frame as the fused output
lat0 = loc["latitude"].iloc[0]
lon0 = loc["longitude"].iloc[0]
cos_lat0 = np.cos(np.radians(lat0))
loc["E"] = np.radians(loc["longitude"] - lon0) * EARTH_R * cos_lat0
loc["N"] = np.radians(loc["latitude"] - lat0) * EARTH_R

fig, axes = plt.subplots(1, 2, figsize=(18, 9))

# --- Left: track shape, raw vs fused ---
ax = axes[0]
ax.plot(loc["E"], loc["N"], "o-", color="red", alpha=0.4,
        markersize=3, linewidth=0.8, label="Raw GPS (~1Hz)")
sc = ax.scatter(fused["E"], fused["N"], c=fused["speed"],
                cmap="viridis", s=4, label="EKF fused")
plt.colorbar(sc, ax=ax, label="Speed (m/s)")
ax.set_xlabel("East (m)")
ax.set_ylabel("North (m)")
ax.set_title(f"Karting Track ({BASE}): Raw GPS vs EKF Fused")
ax.set_aspect("equal")
ax.legend()
ax.grid(True, alpha=0.3)

# --- Right: speed over time ---
ax2 = axes[1]
t0 = fused["time"].iloc[0]
fused_t = (fused["time"] - t0) * 1e-9
ax2.plot(fused_t, fused["speed"], color="navy", linewidth=0.8,
         label="Fused speed")
if "speed" in loc.columns:
    gps_t = (loc["time"] - t0) * 1e-9
    gps_spd = loc["speed"].where(loc["speed"] >= 0)
    ax2.plot(gps_t, gps_spd, "o", color="red", alpha=0.4,
             markersize=3, label="Raw GPS speed")
ax2.set_xlabel("Time (s)")
ax2.set_ylabel("Speed (m/s)")
ax2.set_title("Speed Profile")
ax2.legend()
ax2.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(OUTIMG, dpi=120)
plt.show()
print(f"Saved {OUTIMG}")