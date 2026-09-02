"""Find when the kart is on pit-related paths so we can clip them out.

Pit hook is near E~5,N~0. Entry diagonal comes from bottom (N<-45 on the
far left). Identify the first gate crossing (start of lap 1) and last
crossing (end of last lap); everything outside is out/in/pit.
"""
import numpy as np, pandas as pd
from laps import crossings

df = pd.read_csv("kart/fused_trace.csv")
ct = crossings(df.E.values, df.N.values, df.seconds_elapsed.values,
               df.vE.values, df.vN.values)
print("gate crossings:", len(ct))
print("first crossing t=", round(ct[0],2), " last t=", round(ct[-1],2))
print("-> RACING window = [{:.2f}, {:.2f}]  ({:.1f}s, {:.1f} min)".format(
      ct[0], ct[-1], ct[-1]-ct[0], (ct[-1]-ct[0])/60))

# How much is before first / after last crossing?
t = df.seconds_elapsed.values
pre = (t < ct[0]).sum(); post = (t > ct[-1]).sum()
print(f"samples before lap1: {pre} ({pre/100:.1f}s)  after last: {post} ({post/100:.1f}s)")

# check for pit-hook visits MID session (E<15 and N between -10 and 15)
pit = (df.E < 15) & (df.N > -12) & (df.N < 18)
pit_t = t[pit]
if len(pit_t):
    print("\npit-hook region visited at t=", np.round(np.unique(np.round(pit_t,0)),0))
else:
    print("\nno pit-hook visits")