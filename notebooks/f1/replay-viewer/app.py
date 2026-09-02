import fastf1 as ff1
import pandas as pd
from flask import Flask, jsonify
from flask_cors import CORS
import logging
import os

# --- Configuration ---
logging.basicConfig(level=logging.INFO)

CACHE_DIR = 'cache'

# Create the cache directory if it doesn't exist and enable FastF1 cache
try:
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)
        logging.info(f"Created cache directory at: {CACHE_DIR}")
    ff1.Cache.enable_cache(CACHE_DIR)
    logging.info(f"FastF1 cache enabled at: {CACHE_DIR}")
except Exception as e:
    logging.warning(f"Could not enable FastF1 cache: {e}")

app = Flask(__name__)
CORS(app)

# --- In-Memory Cache ---
session_cache = {}

# --- Helper Functions ---

def get_session_data(year, event, session_type):
    """
    Load a FastF1 session, with simple in-memory caching.
    """
    cache_key = f"{year}-{event}-{session_type}"
    if cache_key in session_cache:
        logging.info(f"Returning cached session data for {cache_key}")
        return session_cache[cache_key]

    logging.info(f"Loading session data for {cache_key}...")
    try:
        session = ff1.get_session(year, event, session_type)
        session.load(telemetry=True, laps=True, weather=False)
        session_cache[cache_key] = session
        logging.info(f"Session data for {cache_key} loaded and cached.")
        return session
    except Exception as e:
        logging.error(f"Failed to load session for {cache_key}: {e}")
        return None


def get_team_colors(session):
    """
    Map driver abbreviation (TLA) -> team color as hex (e.g., '#00D2BE').
    Uses the driver's fastest lap TeamColor where possible; falls back to white.
    """
    colors = {}
    laps = session.laps
    for drv_num in session.drivers:
        try:
            drv = session.get_driver(drv_num)
            tla = drv.get('Abbreviation') or drv.get('Tla') or drv.get('Code')
            if not tla:
                continue
            drv_laps = laps.pick_driver(tla)
            if drv_laps.empty:
                colors[tla] = "#FFFFFF"
                continue
            fastest = drv_laps.pick_fastest()
            team_color = fastest.get('TeamColor')
            colors[tla] = f"#{team_color}" if team_color else "#FFFFFF"
        except Exception:
            # Be robust to missing data
            try:
                tla = session.get_driver(drv_num).get('Abbreviation', str(drv_num))
                colors[tla] = "#FFFFFF"
            except Exception:
                pass
    return colors


# --- Routes ---

@app.route('/api/track-layout/<int:year>/<event>')
def get_track_layout(year, event):
    logging.info(f"Received request for track layout: {year}, {event}")
    try:
        session = get_session_data(year, event, 'R')  # Race
        if session is None:
            raise Exception("Session could not be loaded.")

        fastest_lap = session.laps.pick_fastest()
        if fastest_lap is None or fastest_lap.empty:
            raise Exception("No fastest lap available for this session.")

        # Newer FastF1 may support use_z, older ones won't.
        try:
            track = fastest_lap.get_pos_data(use_z=True)
        except TypeError:
            track = fastest_lap.get_pos_data()

        available = [c for c in ['X', 'Y', 'Z'] if c in track.columns]
        if not available:
            raise Exception("Position data missing expected columns (X/Y[/Z]).")

        track_data = track[available].to_dict(orient='records')
        return jsonify(track_data)

    except Exception as e:
        logging.exception("Error building track layout")
        return jsonify({"error": f"Could not process track layout: {str(e)}"}), 500


@app.route('/api/race-telemetry/<int:year>/<event>')
def get_race_telemetry(year, event):
    logging.info(f"Received request for race telemetry: {year}, {event}")
    try:
        session = get_session_data(year, event, 'R')  # Race
        if session is None:
            raise Exception("Session could not be loaded.")

        logging.info(f"Processing telemetry for {year} {event} Race...")

        all_drivers_telemetry = {}
        team_colors = get_team_colors(session)

        # session.drivers is typically a list of driver numbers; get TLA per driver
        for drv_num in session.drivers:
            try:
                driver = session.get_driver(drv_num)
                tla = driver.get('Abbreviation') or driver.get('Tla') or driver.get('Code')
                if not tla:
                    logging.warning(f"Skipping driver with missing TLA (num={drv_num})")
                    continue

                # Get all laps for this driver
                laps = session.laps.pick_driver(tla)
                if laps.empty:
                    continue

                # Get telemetry across all laps
                tel = laps.get_telemetry()
                if tel.empty:
                    continue

                # Keep only time + position columns; ensure Time is the index (TimedeltaIndex)
                pos_cols = ['X', 'Y'] + (['Z'] if 'Z' in tel.columns else [])
                tel_pos = tel[['Time'] + pos_cols].copy()
                tel_pos = tel_pos.set_index('Time')

                # Resample to 1-second intervals on TimedeltaIndex
                tel_resampled = tel_pos.resample('1S').interpolate('linear').ffill().bfill()

                def safe_float(val):
                    try:
                        return float(val)
                    except Exception:
                        return None

                # Build JSON-friendly structure
                def row_to_point(idx, row):
                    base = {
                        "time": int(idx.total_seconds()),
                        "x": safe_float(row['X']),
                        "y": safe_float(row['Y']),
                    }
                    if 'Z' in tel_resampled.columns:
                        base["z"] = safe_float(row['Z'])
                    return base

                driver_data = {
                    "tla": tla,
                    "color": team_colors.get(tla, "#FFFFFF"),
                    "telemetry": [row_to_point(idx, row) for idx, row in tel_resampled.iterrows()],
                }

                all_drivers_telemetry[tla] = driver_data
                logging.info(f"Processed telemetry for {tla}")
            except Exception as e:
                logging.warning(f"Could not process telemetry for driver {drv_num}: {e}")

        logging.info("Finished processing all telemetry.")
        return jsonify(all_drivers_telemetry)

    except Exception as e:
        logging.error(f"Failed to get race telemetry: {e}")
        return jsonify({"error": f"Could not process race telemetry: {str(e)}"}), 500


# --- Run the App ---
if __name__ == '__main__':
    """
    To run this:
    1) pip install Flask flask-cors fastf1 pandas
    2) python app.py
    3) Open http://127.0.0.1:8081
    """
    app.run(debug=True, host="0.0.0.0", port=8081)
