import numpy as np, pandas as pd
from loaders import load_imu
imu = load_imu()
acc = np.sqrt(imu.ax**2 + imu.ay**2 + imu.az**2).values
t = imu.seconds_elapsed.values
for thr in [15,20,25,30,40,50,60,70]:
    n = (acc>thr).sum()
    print(f"|acc|>{thr:>3} m/s^2 : {n:>5} samples")
print("\nmax jolt:", round(acc.max(),1), "at t=", round(t[acc.argmax()],2))
print("99.9th pct:", round(np.percentile(acc,99.9),1))
print("99.99th pct:", round(np.percentile(acc,99.99),1))
# show jolts > 50 clustered in time
big = np.where(acc>50)[0]
if len(big):
    print("\njolts >50 m/s^2 at times:", np.round(np.unique(np.round(t[big],1)),1))