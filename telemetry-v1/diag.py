import numpy as np, pandas as pd

BASE = "clean"
accel = pd.read_csv(f"{BASE}/Accelerometer.csv").sort_values("time")
grav  = pd.read_csv(f"{BASE}/Gravity.csv").sort_values("time")
orient= pd.read_csv(f"{BASE}/Orientation.csv").sort_values("time")
loc   = pd.read_csv(f"{BASE}/Location.csv")

print("=== shapes ===")
print("accel", accel.shape, "grav", grav.shape, "orient", orient.shape, "loc", loc.shape)

print("\n=== accel sample / stats (body frame) ===")
print(accel[["x","y","z"]].describe().loc[["mean","std","min","max"]])
print("accel magnitude mean:", np.sqrt(accel.x**2+accel.y**2+accel.z**2).mean())

print("\n=== gravity stats ===")
print(grav[["x","y","z"]].describe().loc[["mean","std"]])
print("grav magnitude mean:", np.sqrt(grav.x**2+grav.y**2+grav.z**2).mean())

print("\n=== orientation columns ===", list(orient.columns))
print(orient.head(3).to_string())
q = orient[["qw","qx","qy","qz"]] if "qw" in orient.columns else None
if q is not None:
    print("quat norm mean:", np.sqrt((q**2).sum(axis=1)).mean())

# Interpolate gravity onto accel timebase, subtract -> linear accel (body)
t = accel.time.values.astype(float)
def itp(df,c): return np.interp(t, df.time.values.astype(float), df[c].values)
lx = accel.x.values - itp(grav,"x")
ly = accel.y.values - itp(grav,"y")
lz = accel.z.values - itp(grav,"z")
print("\n=== linear accel (accel - gravity), BODY frame ===")
print("mean: x=%.4f y=%.4f z=%.4f" % (lx.mean(), ly.mean(), lz.mean()))
print("std : x=%.4f y=%.4f z=%.4f" % (lx.std(), ly.std(), lz.std()))
print("mag mean (should be near 0 if at rest a lot):", np.sqrt(lx**2+ly**2+lz**2).mean())

# sample rates
print("\n=== sample rates (Hz) ===")
for name,df in [("accel",accel),("grav",grav),("orient",orient),("loc",loc)]:
    dt = np.diff(df.time.values.astype(float))*1e-9
    dt = dt[dt>0]
    print(f"{name}: {1/np.median(dt):.1f} Hz, n={len(df)}, dur={ (df.time.max()-df.time.min())*1e-9:.1f}s")

# GPS sanity
print("\n=== GPS speed/bearing valid counts ===")
for c in ["speed","bearing","horizontalAccuracy"]:
    if c in loc.columns:
        print(c, "valid(>=0):", int((loc[c]>=0).sum()), "of", len(loc), "range", loc[c].min(), loc[c].max())
