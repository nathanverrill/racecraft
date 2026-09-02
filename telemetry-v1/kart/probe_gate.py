"""Probe the right-side main straight to place the start/finish gate."""
import numpy as np, pandas as pd
df = pd.read_csv("kart/fused_trace.csv")
E, N = df.E.values, df.N.values
vE, vN = df.vE.values, df.vN.values
spd = np.hypot(vE, vN)

# Right straight: high East, mid North, moving mostly +North, fast
mask = (E > 78) & (N > 10) & (N < 110) & (spd > 8)
print("samples on candidate right straight:", mask.sum())
print("E range:", round(E[mask].min(),1), round(E[mask].max(),1))
print("N range:", round(N[mask].min(),1), round(N[mask].max(),1))
# dominant travel direction there
md = np.array([vE[mask].mean(), vN[mask].mean()])
md /= np.linalg.norm(md)
print("mean travel dir on right straight:", np.round(md,2), "(0,1)=North")
# suggested gate: middle of that straight
gE = E[mask].mean(); gN = N[mask].mean()
print(f"suggested gate center: E={gE:.1f} N={gN:.1f}")