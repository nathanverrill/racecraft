import os
import glob
import pandas as pd
import numpy as np

# 1. Scan and filter out zero-byte files
csv_files = glob.glob("*.csv")
valid_files = [f for f in csv_files if os.path.exists(f) and os.path.getsize(f) > 0]

global_start = None
data_dict = {}

# 2. Find the earliest master timestamp
for f in valid_files:
    try:
        df_head = pd.read_csv(f, nrows=1)
        if 'time' in df_head.columns:
            ts = df_head['time'].iloc[0]
            if global_start is None or ts < global_start:
                global_start = ts
    except:
        continue

print(f"Syncing all streams to global start: {global_start}")
os.makedirs("processed_telemetry", exist_ok=True)

# 3. Normalize timelines and calculate vectors
for f in valid_files:
    try:
        df = pd.read_csv(f)
        if 'time' in df.columns:
            df['relative_sec'] = (df['time'] - global_start) / 1e9
            
            # Feature engineering for F1 UI elements
            if 'Accelerometer' in f:
                # G-force vector magnitude calculation
                df['g_total'] = np.sqrt(df['x']**2 + df['y']**2 + df['z']**2) / 9.81
            elif 'Location' in f and 'speed' in df.columns:
                # Convert meters/sec to MPH for the dial
                df['speed_mph'] = df['speed'] * 2.23694
                
            df.to_csv(f"processed_telemetry/sync_{f}", index=False)
            print(f"Saved synchronized: {f}")
    except Exception as e:
        print(f"Could not parse {f}: {e}")