import numpy as np
det=np.array([41.33,41.98,49.24,42.0,42.44,40.98,50.55,42.21,41.5,41.27,41.39,42.06,41.96,41.54])
off=np.array([42.137,49.038,42.323,42.243,41.240,50.536,42.228,41.164,41.195,41.700,41.884,42.035,41.632])
for s in range(len(det)-12):
    w=det[s:s+13]
    print(f"offset {s}: RMSE {np.sqrt(np.mean((w-off)**2)):.3f}s  first3={np.round(w[:3],1)}")
