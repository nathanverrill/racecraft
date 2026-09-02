"""Probe the real start/finish location (user red arrow ~E12,N-12) to set
the gate position + crossing direction."""
import numpy as np, pandas as pd
df = pd.read_csv("kart/fused_trace.csv")
E,N,vE,vN = df.E.values, df.N.values, df.vE.values, df.vN.values
spd = np.hypot(vE,vN)

# samples near the red-arrow start/finish area
for cx,cy,r in [(12,-12,12),(15,-10,10),(8,-15,12)]:
    m = (np.hypot(E-cx, N-cy) < r) & (spd > 3)
    if m.sum()==0: 
        print(f'center ({cx},{cy}) r{r}: no samples'); continue
    md = np.array([vE[m].mean(), vN[m].mean()]); md/=np.linalg.norm(md)
    print(f'center ({cx},{cy}) r{r}: n={m.sum()} mean_dir=({md[0]:.2f},{md[1]:.2f}) '
          f'mean_spd={spd[m].mean()*3.6:.0f}km/h E[{E[m].min():.0f},{E[m].max():.0f}] N[{N[m].min():.0f},{N[m].max():.0f}]')