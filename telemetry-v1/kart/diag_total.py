import numpy as np, pandas as pd
from laps import crossings
df = pd.read_csv("kart/fused_trace.csv")
ct = crossings(df.E.values, df.N.values, df.seconds_elapsed.values, df.vE.values, df.vN.values)
off = np.array([42.450,41.136,49.209,41.834,41.564,42.189,41.056,40.968,42.535,42.583,40.519,53.899,41.600,46.750])
print("detected crossings:", len(ct))
print("detected flying-lap total (cross[1]..cross[15]):", round(ct[-1]-ct[1], 2), "s  (14 laps)")
print("official 14-lap total:", round(off.sum(), 2), "s")
print("diff:", round((ct[-1]-ct[1]) - off.sum(), 2), "s")
print()
# Use detected crossings 1..15 as the 14 lap boundaries (drop crossing 0 = out-lap end)
laps = np.diff(ct[1:])
print("Aligning detected laps 1..14 (dropping out-lap):")
print(f"{'Lap':>3} {'Detected':>9} {'Official':>9} {'Diff':>7}")
for i in range(min(len(laps), 14)):
    print(f"{i+1:>3} {laps[i]:>9.3f} {off[i]:>9.3f} {laps[i]-off[i]:>+7.3f}")
n=min(len(laps),14)
print("\nRMSE:", round(np.sqrt(np.mean((laps[:n]-off[:n])**2)),3),"s")