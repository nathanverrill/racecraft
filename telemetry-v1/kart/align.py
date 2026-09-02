import numpy as np
det = np.array([43.88,41.16,49.11,41.52,41.47,41.92,41.83,40.54,41.11,43.72,41.32,40.67,54.2,46.77,42.92])
off = np.array([42.450,41.136,49.209,41.834,41.564,42.189,41.056,40.968,42.535,42.583,40.519,53.899,41.600,46.750])
for start in range(len(det) - 13):
    w = det[start:start+14]
    rmse = np.sqrt(np.mean((w - off) ** 2))
    print(f"offset {start}: RMSE {rmse:.3f}s   first3={np.round(w[:3],2)}")