import numpy as np, pandas as pd
df = pd.read_csv("kart/fused_trace.csv")
m = (df.seconds_elapsed >= 600) & (df.seconds_elapsed <= 612)
d = df[m].reset_index(drop=True)

# IMU event: peak |lateral accel proxy| = speed*yaw and peak |yaw_rate|
latg = (d.speed * d.yaw_rate).abs()
t_yaw = d.seconds_elapsed[d.yaw_rate.abs().idxmax()]
t_latg = d.seconds_elapsed[latg.idxmax()]

# speed crater: time speed first drops below 3 m/s (~11 km/h)
below = d[d.speed < 3.0]
t_stop = below.seconds_elapsed.iloc[0] if len(below) else float('nan')

# position 'arrives': when dot velocity magnitude first ~0 (position settles)
# i.e. when consecutive positions stop moving much
dx = np.hypot(np.diff(d.E), np.diff(d.N))
moving = dx > 0.05  # m per 10ms
stop_idx = np.where(~moving)[0]
t_pos_settle = d.seconds_elapsed.iloc[stop_idx[0]] if len(stop_idx) else float('nan')

print(f"peak |yaw_rate|   at t={t_yaw:.2f}s")
print(f"peak lateral force at t={t_latg:.2f}s")
print(f"speed<3m/s (stop)  at t={t_stop:.2f}s")
print(f"position settles   at t={t_pos_settle:.2f}s")
print(f"\n--> position lag vs IMU event: {t_pos_settle - t_latg:+.2f}s")
print("\nspeed/pos near event:")
for _, r in d[(d.seconds_elapsed>=604)&(d.seconds_elapsed<=609)].iloc[::20].iterrows():
    print(f"  t={r.seconds_elapsed:6.2f} E={r.E:6.1f} N={r.N:6.1f} spd={r.speed*3.6:5.1f}km/h yaw={r.yaw_rate:+5.2f}")