import os
import glob
import pandas as pd
import json
import numpy as np
from scipy.signal import savgol_filter
from scipy.interpolate import interp1d

# Look for our active processed logs
sync_files = glob.glob("processed_telemetry/sync_*.csv")
data_bundle = {}

print("🚀 Initializing Sensor Fusion Engine (IMU + GPS Integration)...")

# Load core files
accel_df = pd.read_csv("processed_telemetry/sync_Accelerometer.csv") if os.path.exists("processed_telemetry/sync_Accelerometer.csv") else None
loc_df = pd.read_csv("processed_telemetry/sync_Location.csv") if os.path.exists("processed_telemetry/sync_Location.csv") else None
gyro_df = pd.read_csv("processed_telemetry/sync_Gyroscope.csv") if os.path.exists("processed_telemetry/sync_Gyroscope.csv") else None
orient_df = pd.read_csv("processed_telemetry/sync_Orientation.csv") if os.path.exists("processed_telemetry/sync_Orientation.csv") else None

if accel_df is None or loc_df is None:
    print("❌ Critical Error: Missing Accelerometer.csv or Location.csv in processed_telemetry.")
    exit()

# Sort and clean baseline tracking timelines
accel_df = accel_df.sort_values('relative_sec').drop_duplicates(subset=['relative_sec'])
loc_df = loc_df.sort_values('relative_sec').drop_duplicates(subset=['relative_sec'])

# Use the highest frequency clock (the Accelerometer) as our master high-density timeline
master_time = accel_df['relative_sec'].values
total_points = len(master_time)

# --- SENSOR FUSION STEP 1: INTERPOLATE GPS TO HIGH FREQUENCY TIME GRID ---
# This creates matching point counts for every single millisecond row
def align_to_master(source_time, source_values, fill=0.0):
    f = interp1d(source_time, source_values, kind='linear', bounds_error=False, fill_value=fill)
    return np.nan_to_num(f(master_time), nan=fill)

raw_lon = align_to_master(loc_df['relative_sec'].values, loc_df['longitude'].values)
raw_lat = align_to_master(loc_df['relative_sec'].values, loc_df['latitude'].values)
raw_speed = align_to_master(loc_df['relative_sec'].values, loc_df['speed'].values) * 2.23694 # Convert m/s to MPH

# --- SENSOR FUSION STEP 2: USE GYRO & ACCELEROMETER FOR MATHEMATICAL SMOOTHING ---
# We use a Savitzky-Golay filter to smooth out the noisy GPS steps using the IMU's trajectory trends
window_size = 51 if total_points > 51 else (total_points // 2 * 2 + 1) # Must be odd
smooth_lon = savgol_filter(raw_lon, window_size, polyorder=3)
smooth_lat = savgol_filter(raw_lat, window_size, polyorder=3)
smooth_speed = savgol_filter(raw_speed, window_size, polyorder=3)

# Extract forward/lateral force channels
g_x = accel_df['x'].values / 9.80665
g_y = accel_df['y'].values / 9.80665

# --- SENSOR FUSION STEP 3: BUNDLE DENSE MATRICES ---
data_bundle["Location"] = {
    "time": master_time.tolist(),
    "lon": smooth_lon.tolist(),
    "lat": smooth_lat.tolist(),
    "speed": np.clip(smooth_speed, 0, None).tolist()
}

data_bundle["Accelerometer"] = {
    "time": master_time.tolist(),
    "x": accel_df['x'].tolist(),
    "y": accel_df['y'].tolist(),
    "throttle": np.clip(g_y, 0, None).tolist(),
    "brake": np.abs(np.clip(g_y, None, 0)).tolist()
}

if gyro_df is not None:
    gyro_df = gyro_df.sort_values('relative_sec').drop_duplicates(subset=['relative_sec'])
    data_bundle["Gyroscope"] = {
        "z": align_to_master(gyro_df['relative_sec'].values, gyro_df['z'].values).tolist()
    }

if orient_df is not None:
    orient_df = orient_df.sort_values('relative_sec').drop_duplicates(subset=['relative_sec'])
    data_bundle["Orientation"] = {
        "yaw": align_to_master(orient_df['relative_sec'].values, orient_df['yaw'].values).tolist()
    }

data_bundle["_metadata"] = {
    "total_points": total_points,
    "max_time": float(master_time.max())
}

with open("telemetry_data.json", "w") as f:
    json.dump(data_bundle, f)
print(f"🎉 Sensor Fusion complete! Generated {total_points} smooth high-density coordinate points.")