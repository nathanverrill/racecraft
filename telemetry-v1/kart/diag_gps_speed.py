import numpy as np, pandas as pd
from loaders import load_location
loc = load_location()
w = loc[(loc.seconds_elapsed>=595)&(loc.seconds_elapsed<=625)]
print("raw GPS speed through the crash (1 Hz):")
print(f"{'t':>7} {'speed_kmh':>9} {'horizAcc':>8}")
for _,r in w.iterrows():
    print(f"{r.seconds_elapsed:>7.1f} {r.speed*3.6:>9.1f} {r.horizontalAccuracy:>8.2f}")