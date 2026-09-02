import numpy as np, pandas as pd
df = pd.read_csv("kart/fused_trace.csv")
m = (df.seconds_elapsed >= 590) & (df.seconds_elapsed <= 615)
d = df[m]
print("around the t=598 crossing (spin region):")
print(f"{'t':>7} {'E':>7} {'N':>7} {'spd_kmh':>8} {'course':>7} {'yaw_rate':>9}")
for _, r in d.iloc[::10].iterrows():
    print(f"{r.seconds_elapsed:>7.1f} {r.E:>7.1f} {r.N:>7.1f} {r.speed*3.6:>8.1f} {r.course_deg:>7.0f} {r.yaw_rate:>9.2f}")
print("\nmin speed in window (km/h):", round(d.speed.min()*3.6,1))
print("max |yaw_rate| in window:", round(d.yaw_rate.abs().max(),2))