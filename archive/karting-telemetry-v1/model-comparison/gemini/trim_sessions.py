#!/usr/bin/env python3
import os
import pandas as pd
import subprocess

# Define the session time windows converted directly to seconds
SESSIONS = {
    "FP1": {"start_sec": 56.0,   "end_sec": 845.0},   # 0:56.0 - 14:05.0
    "FP2": {"start_sec": 1140.0, "end_sec": 2190.0}  # 19:00.0 - 36:30.0
}

def trim_csv(file_path, out_dir, start_s, end_s):
    try:
        df = pd.read_csv(file_path)
        if "seconds_elapsed" not in df.columns:
            return
        
        # Filter rows within the exact window based on elapsed timeline
        mask = (df["seconds_elapsed"] >= start_s) & (df["seconds_elapsed"] <= end_s)
        trimmed_df = df[mask].copy()
        
        # Normalize seconds_elapsed so each session baseline starts at 0.000
        trimmed_df["seconds_elapsed"] = trimmed_df["seconds_elapsed"] - start_s
        
        # Clean up noise: Round all floating point values to 3 decimal places
        for col in trimmed_df.columns:
            if trimmed_df[col].dtype in ['float64', 'float32']:
                trimmed_df[col] = trimmed_df[col].round(3)
                
        # Save to target session directory
        out_path = os.path.join(out_dir, os.path.basename(file_path))
        trimmed_df.to_csv(out_path, index=False)
    except Exception as e:
        print(f"Error processing {os.path.basename(file_path)}: {e}")

def trim_audio(audio_file, out_dir, session_name, start_s, end_s):
    out_audio_path = os.path.join(out_dir, "Microphone.mp4")
    duration = end_s - start_s
    
    # Run a fast, lossless stream-copy cut using ffmpeg
    cmd = [
        "ffmpeg", "-y", "-ss", str(start_s), "-t", str(duration),
        "-i", audio_file, "-c", "copy", out_audio_path
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        print(f"-> Successfully sliced audio for {session_name}")
    except FileNotFoundError:
        print(f"! Warning: ffmpeg not found on your system path. Skipped audio cut for {session_name}.")
    except subprocess.CalledProcessError:
        print(f"! Failed to slice audio file using ffmpeg for {session_name}.")

def main():
    current_dir = os.getcwd()
    print(f"Scanning directory: {current_dir}\n")
    
    # Locate all CSV targets and any matching video/audio container file
    csv_files = [f for f in os.listdir(current_dir) if f.lower().endswith(".csv") and f != "Metadata.csv"]
    audio_candidates = [f for f in os.listdir(current_dir) if f.lower() in ["microphone.mp4", "microphone.m4a"]]
    audio_file = audio_candidates[0] if audio_candidates else None

    if not csv_files:
        print("No Sensor Logger CSV files found in this folder.")
        return

    for name, bounds in SESSIONS.items():
        print(f"Creating session container: {name}...")
        target_dir = os.path.join(current_dir, name)
        os.makedirs(target_dir, exist_ok=True)
        
        # Handle Metadata.csv layout replication if present
        meta_path = os.path.join(current_dir, "Metadata.csv")
        if os.path.exists(meta_path):
            pd.read_csv(meta_path).to_csv(os.path.join(target_dir, "Metadata.csv"), index=False)

        # Truncate and clean all localized sensor charts
        for csv in csv_files:
            trim_csv(os.path.join(current_dir, csv), target_dir, bounds["start_sec"], bounds["end_sec"])
            
        # Cut accompanying audio stream to match timeline perfectly
        if audio_file:
            trim_audio(os.path.join(current_dir, audio_file), target_dir, name, bounds["start_sec"], bounds["end_sec"])
            
        print(f"Done. Cleaned dataset written to ./{name}/\n")

if __name__ == "__main__":
    main()