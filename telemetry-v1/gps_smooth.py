"""
GPS-only Kalman smoother (RTS) for clean, high-rate karting position.

Why GPS-only: the phone IMU's body-frame / quaternion convention makes accel
fusion unreliable here (pinwheeling track, inflated speed). The GPS stream is
clean (1 Hz, good accuracy, valid speed+bearing), so a forward-backward
Kalman (RTS) smoother gives a smooth, drift-free racing line and lets us
upsample to high frequency.

State x = [E, N, vE, vN]  (constant-velocity model)
Measurements: GPS position (E,N) always; GPS velocity (from speed+bearing) when valid.

Usage: python3.11 gps_smooth.py session1  [out_hz]
"""

import sys
import numpy as np
import pandas as pd

BASE = sys.argv[1] if len(sys.argv) > 1 else "clean"
OUT_HZ = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0
OUT = f"{BASE}/Position.csv" if BASE != "clean" else "Position.csv"
EARTH_R = 6378137.0

# ---- tunables ----


# Karts accelerate modestly; keep process accel realistic so velocity can't blow up.
PROC_ACCEL_STD = 1.0   # m/s^2 process noise (how much speed can change per step)
VEL_MEAS_STD = 0.5     # m/s  trust in GPS speed/bearing velocity (it is clean -> trust it)

loc = pd.read_csv(f"{BASE}/Location.csv")
loc = loc[loc["horizontalAccuracy"] > 0].copy().sort_values("time").reset_index(drop=True)

lat0 = loc["latitude"].iloc[0]
lon0 = loc["longitude"].iloc[0]
cos_lat0 = np.cos(np.radians(lat0))
loc["E"] = np.radians(loc["longitude"] - lon0) * EARTH_R * cos_lat0
loc["N"] = np.radians(loc["latitude"] - lat0) * EARTH_R

t = loc["time"].values.astype(np.float64) * 1e-9  # seconds
t = t - t[0]
n = len(loc)

# velocity measurements from speed + bearing where valid
speed = loc["speed"].values
bearing = loc["bearing"].values
has_vel = (speed >= 0) & (bearing >= 0)
br = np.radians(bearing)
vE_meas = speed * np.sin(br)   # bearing 0=N, clockwise
vN_meas = speed * np.cos(br)

# ---- forward Kalman ----
x = np.array([loc["E"].iloc[0], loc["N"].iloc[0], 0.0, 0.0])
P = np.diag([25.0, 25.0, 25.0, 25.0])
I4 = np.eye(4)

xs_f = np.zeros((n, 4))
Ps_f = np.zeros((n, 4, 4))
xs_pred = np.zeros((n, 4))
Ps_pred = np.zeros((n, 4, 4))
Fs = np.zeros((n, 4, 4))

for k in range(n):
    dt = t[k] - t[k-1] if k > 0 else 0.0
    F = np.array([[1,0,dt,0],[0,1,0,dt],[0,0,1,0],[0,0,0,1]], float)
    if dt > 0:
        q = PROC_ACCEL_STD**2
        G = np.array([0.5*dt*dt, 0.5*dt*dt, dt, dt])
        Q = np.outer(G, G) * q
        x = F @ x
        P = F @ P @ F.T + Q
    Fs[k] = F
    xs_pred[k] = x
    Ps_pred[k] = P

    # position update
    pstd = loc["horizontalAccuracy"].iloc[k]
    if has_vel[k]:
        H = np.array([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]], float)
        z = np.array([loc["E"].iloc[k], loc["N"].iloc[k], vE_meas[k], vN_meas[k]])
        R = np.diag([pstd**2, pstd**2, VEL_MEAS_STD**2, VEL_MEAS_STD**2])
    else:
        H = np.array([[1,0,0,0],[0,1,0,0]], float)
        z = np.array([loc["E"].iloc[k], loc["N"].iloc[k]])
        R = np.diag([pstd**2, pstd**2])
    y = z - H @ x
    S = H @ P @ H.T + R
    K = P @ H.T @ np.linalg.inv(S)
    x = x + K @ y
    P = (I4 - K @ H) @ P
    xs_f[k] = x
    Ps_f[k] = P

# ---- RTS backward smoother ----
xs_s = xs_f.copy()
Ps_s = Ps_f.copy()
for k in range(n-2, -1, -1):
    F = Fs[k+1]
    C = Ps_f[k] @ F.T @ np.linalg.inv(Ps_pred[k+1])
    xs_s[k] = xs_f[k] + C @ (xs_s[k+1] - xs_pred[k+1])
    Ps_s[k] = Ps_f[k] + C @ (Ps_s[k+1] - Ps_pred[k+1]) @ C.T

# ---- upsample smoothed track to OUT_HZ ----
t_hi = np.arange(t[0], t[-1], 1.0/OUT_HZ)
E_hi = np.interp(t_hi, t, xs_s[:,0])
N_hi = np.interp(t_hi, t, xs_s[:,1])
vE_hi = np.interp(t_hi, t, xs_s[:,2])
vN_hi = np.interp(t_hi, t, xs_s[:,3])
speed_hi = np.sqrt(vE_hi**2 + vN_hi**2)

out = pd.DataFrame({

    "time": t_hi,
    "E": E_hi, "N": N_hi,
    "vE": vE_hi, "vN": vN_hi,
    "speed": speed_hi,
    "latitude": lat0 + np.degrees(N_hi / EARTH_R),
    "longitude": lon0 + np.degrees(E_hi / (EARTH_R * cos_lat0)),
})

out = out.round({"time":3,"E":3,"N":3,"vE":3,"vN":3,"speed":3,"latitude":7,"longitude":7})
out.to_csv(OUT, index=False)
print(f"Wrote {len(out)} smoothed samples ({OUT_HZ} Hz) -> {OUT}")
print(f"Speed range: {speed_hi.min():.1f} - {speed_hi.max():.1f} m/s (GPS max was {speed[speed>=0].max():.1f})")
print(out.head())