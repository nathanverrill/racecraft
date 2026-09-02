"""Locate the hard wall impact and spins within the lap-12 region.

Wall hit = abrupt speed drop to ~0 + raw-accelerometer jolt.
Spin     = high yaw-rate / slip, speed dips but not to zero.

We scan a generous window covering lap 12 (~t=565..620 based on earlier
crossing analysis: crossing 11 @557.6, crossing 13 @652.5, so the big
spin lap spans ~557..652; the hardest event is inside).
"""
import numpy as np, pandas as pd
from loaders import load_imu

df = pd.read_csv("kart/fused_trace.csv")
imu = load_imu()

# raw accelerometer magnitude (user accel, gravity already separate) = jolt
acc_mag = np.sqrt(imu.ax**2 + imu.ay**2 + imu.az**2)
imu = imu.assign(acc_mag=acc_mag)

W = (df.seconds_elapsed >= 557) & (df.seconds_elapsed <= 652)
d = df[W].reset_index(drop=True)
iW = (imu.seconds_elapsed >= 557) & (imu.seconds_elapsed <= 652)
di = imu[iW].reset_index(drop=True)

# longitudinal deceleration from fused speed
spd = d.speed.values
t = d.seconds_elapsed.values
dvdt = np.gradient(spd, t)            # m/s^2 (negative = braking/impact)

# biggest sudden decel (impact candidate)
impact_i = np.argmin(dvdt)
print("=== HARD DECEL (wall-hit candidate) ===")
print(f"t={t[impact_i]:.2f}s  decel={dvdt[impact_i]:.1f} m/s^2  "
      f"speed {spd[impact_i]*3.6:.1f} km/h  E={d.E[impact_i]:.1f} N={d.N[impact_i]:.1f}")

# biggest raw accel jolt
jolt_i = di.acc_mag.idxmax()
print(f"\n=== PEAK ACCEL JOLT (raw IMU) ===")
print(f"t={di.seconds_elapsed[jolt_i]:.2f}s  |acc|={di.acc_mag[jolt_i]:.2f} m/s^2")

# near-stops (speed < 2 km/h)
stops = d[d.speed*3.6 < 2.0]
print(f"\n=== NEAR-STOPS (<2 km/h) in lap-12 region ===")
if len(stops):
    # group contiguous
    ts = stops.seconds_elapsed.values
    print("times:", np.round(ts[::5], 1))
    print(f"first stop t={ts[0]:.2f}s at E={stops.E.iloc[0]:.1f} N={stops.N.iloc[0]:.1f}")
else:
    print("none")

# top spins by |yaw_rate|
print(f"\n=== TOP YAW-RATE PEAKS (spins) ===")
yr = d.yaw_rate.abs().values
for i in np.argsort(yr)[-6:][::-1]:
    print(f"t={t[i]:.2f}s yaw={d.yaw_rate[i]:+.2f} rad/s speed={spd[i]*3.6:.1f}km/h E={d.E[i]:.1f} N={d.N[i]:.1f}")