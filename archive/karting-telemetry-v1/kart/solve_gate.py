"""Find gate position on the right straight whose lap boundaries best match
the official timing sheet (per-lap RMSE), keeping crossings clean."""
import numpy as np, pandas as pd
from laps import crossings

OFF = np.array([42.450,41.136,49.209,41.834,41.564,42.189,41.056,
                40.968,42.535,42.583,40.519,53.899,41.600,46.750])
df = pd.read_csv("kart/fused_trace.csv")
E,N,t,vE,vN = df.E.values, df.N.values, df.seconds_elapsed.values, df.vE.values, df.vN.values

best=None
for gn in np.arange(5, 110, 3.0):          # slide gate along the right straight (North)
    for ge in np.arange(78, 90, 1.5):      # small East variation
        ct = crossings(E,N,t,vE,vN, gate_xy=np.array([ge,gn]), gate_dir=np.array([0.0,1.0]))
        if len(ct) < 15:                    # need >=14 laps (+ maybe out-lap)
            continue
        # try dropping leading out-lap or not
        for drop in (0,1):
            laps=np.diff(ct[drop:])
            if len(laps) < 14: continue
            w=laps[:14]
            rmse=np.sqrt(np.mean((w-OFF)**2))
            if best is None or rmse<best[0]:
                best=(rmse, ge, gn, drop, w.copy())

rmse,ge,gn,drop,w=best
print(f"BEST gate E={ge:.1f} N={gn:.1f} drop_outlap={drop}  RMSE={rmse:.3f}s")
print(f"{'Lap':>3} {'Detected':>9} {'Official':>9} {'Diff':>7}")
for i in range(14):
    print(f"{i+1:>3} {w[i]:>9.3f} {OFF[i]:>9.3f} {w[i]-OFF[i]:>+7.3f}")
np.save("kart/best_gate.npy", np.array([ge,gn,drop]))