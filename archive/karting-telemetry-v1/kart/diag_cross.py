import numpy as np, pandas as pd
from laps import crossings
df = pd.read_csv("kart/fused_trace.csv")
ct = crossings(df.E.values, df.N.values, df.seconds_elapsed.values,
               df.vE.values, df.vN.values)
print("num crossings:", len(ct))
for i, c in enumerate(ct):
    gap = ct[i] - ct[i-1] if i > 0 else 0
    print(f"{i:>2}  t={c:8.2f}  gap={gap:6.2f}")
# cumulative official boundaries (start at first crossing)
off = np.array([42.450,41.136,49.209,41.834,41.564,42.189,41.056,40.968,42.535,42.583,40.519,53.899,41.600,46.750])
bnd = ct[0] + np.concatenate([[0], np.cumsum(off)])
print("\nexpected official boundary times (from first crossing):")
print(np.round(bnd, 2))