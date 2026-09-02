import numpy as np, pandas as pd
from telemetry import BestRef, load, detect_flags, per_lap_sector_times
df, bounds = load()
ref = BestRef()
df2 = pd.read_csv(ref.__class__.__module__ and 'NUL' or '') if False else None
# load full clipped trace with derived acc_mag/yaw
full = pd.read_csv('../clipped/fused_trace.csv')
flag = detect_flags(full)
import numpy as np
print('flag counts: green', (flag==0).sum(), 'yellow', (flag==1).sum(), 'red', (flag==2).sum())
secs, sb, theo = per_lap_sector_times(full, bounds, ref)
print('session-best sectors:', np.round(sb,2), '-> theoretical best lap:', round(theo,3),'s')
print('actual best lap:', round(ref.best_time,3),'s')
print('per-lap sectors (first 3 laps):')
for i in range(3): print(f'  lap{i+1}:', np.round(secs[i],2))
