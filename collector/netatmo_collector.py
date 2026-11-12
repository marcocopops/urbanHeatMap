"""
Netatmo collector: one pass per run, designed to be launched by cron.

On each run:
  1. gets a valid access token (via netatmo_auth.get_valid_token)
  2. queries getpublicdata tile by tile over AREA
  3. writes stations and observations to a SQLite database
     (automatic deduplication: UNIQUE(station_id, measured_at))
  4. writes a log line summarising the pass

Check the health of the collection:
    python collector/netatmo_collector.py --status

------------------------------------------------------------------------------
Requirements:
    pip install -r requirements.txt
    collector/netatmo_tokens.json set up (see netatmo_auth.py).

Cron line (every 15 min), adapt the path:
    */15 * * * * cd /path/to/urbanHeatMap && .venv/bin/python collector/netatmo_collector.py >> data/cron.log 2>&1
------------------------------------------------------------------------------
"""

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timezone

import requests

from netatmo_auth import get_valid_token

from pathlib import Path


# --- Configuration -----------------------------------------------------------

# COLLECTION area (wide: Paris + inner suburbs + margin).
AREA = {"lat_ne": 48.902, "lon_ne": 2.470, "lat_sw": 48.815, "lon_sw": 2.224}

TILE_SIZE = 0.05      # degrees
PAUSE_S = 1.0         # pause between tiles

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_FILE = DATA_DIR / "uhi_netatmo.sqlite"
LOG_FILE = DATA_DIR / "collector.log"

URL = "https://api.netatmo.com/api/getpublicdata"

# --- Database ----------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS stations (
    station_id TEXT PRIMARY KEY,
    lat        REAL NOT NULL,
    lon        REAL NOT NULL,
    altitude   REAL,
    last_seen  TEXT NOT NULL          -- last pass where the station appeared
);

CREATE TABLE IF NOT EXISTS observations (
    station_id  TEXT NOT NULL,
    measured_at INTEGER NOT NULL,     -- UNIX timestamp of the MEASUREMENT (key of 'res')
    fetched_at  TEXT NOT NULL,        -- ISO timestamp of OUR pass
    temp_C      REAL,
    humidity    REAL,
    pressure    REAL,
    rain_60min  REAL,
    rain_24h    REAL,
    wind_strength REAL,
    wind_angle    REAL,
    gust_strength REAL,
    UNIQUE (station_id, measured_at)  -- automatic deduplication across passes
);

CREATE INDEX IF NOT EXISTS idx_obs_time ON observations (measured_at);
"""


def open_db():
    con = sqlite3.connect(DB_FILE)
    con.executescript(SCHEMA)
    return con


# --- Fetching ----------------------------------------------------------------

def iter_tiles(area, size):
    lat = area["lat_sw"]
    while lat < area["lat_ne"]:
        lon = area["lon_sw"]
        while lon < area["lon_ne"]:
            yield {
                "lat_sw": round(lat, 6),
                "lon_sw": round(lon, 6),
                "lat_ne": round(min(lat + size, area["lat_ne"]), 6),
                "lon_ne": round(min(lon + size, area["lon_ne"]), 6),
            }
            lon += size
        lat += size


def fetch_tile(token, bbox, max_retries=4):
    headers = {"Authorization": f"Bearer {token}"}
    params = {**bbox, "required_data": "temperature", "filter": "true"}
    for attempt in range(max_retries):
        r = requests.get(URL, headers=headers, params=params, timeout=30)
        if r.status_code < 500:          # success, or non-transient error (4xx)
            r.raise_for_status()          # raises on 4xx (token, request...)
            return r.json().get("body", [])
        # 5xx: transient -> wait 2^attempt seconds and retry
        wait = 2 ** attempt               # 1, 2, 4, 8 s
        print(f"  {r.status_code} on this tile, retrying in {wait}s "
              f"(attempt {attempt + 1}/{max_retries})")
        time.sleep(wait)
    r.raise_for_status()                  # retries exhausted: let the error propagate


def parse_station(st):
    """-> (station info, observation); observation may be None."""
    lon, lat = st["place"]["location"]
    info = {
        "station_id": st["_id"],
        "lat": lat,
        "lon": lon,
        "altitude": st["place"].get("altitude"),
    }

    obs = {k: None for k in ("measured_at", "temp_C", "humidity", "pressure",
                             "rain_60min", "rain_24h",
                             "wind_strength", "wind_angle", "gust_strength")}

    for meas in st.get("measures", {}).values():
        types = meas.get("type", [])
        if "res" in meas and types:
            # type/res schema: temperature, humidity, pressure
            latest = max(meas["res"].keys())
            values = meas["res"][latest]
            mapping = {"temperature": "temp_C", "humidity": "humidity",
                       "pressure": "pressure"}
            for t, col in mapping.items():
                if t in types:
                    obs[col] = values[types.index(t)]
            # measured_at: use the timestamp of the temperature module
            if "temperature" in types:
                obs["measured_at"] = int(latest)
        else:
            # Flat keys: rain and wind
            for k in ("rain_60min", "rain_24h", "wind_strength",
                      "wind_angle", "gust_strength"):
                if k in meas:
                    obs[k] = meas[k]

    if obs["measured_at"] is None:
        return info, None
    return info, obs


# --- One collection pass -------------------------------------------------------

def run_pass():
    started = time.time()
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    token = get_valid_token()
    con = open_db()
    cur = con.cursor()

    n_stations, n_new_obs, n_tiles_ok, n_tiles_err = 0, 0, 0, 0

    for bbox in iter_tiles(AREA, TILE_SIZE):
        try:
            body = fetch_tile(token, bbox)
            n_tiles_ok += 1
        except requests.RequestException:
            n_tiles_err += 1
            continue  # a failed tile must not kill the pass

        for st in body:
            info, obs = parse_station(st)
            cur.execute(
                """INSERT INTO stations (station_id, lat, lon, altitude, last_seen)
                   VALUES (:station_id, :lat, :lon, :altitude, :now)
                   ON CONFLICT(station_id) DO UPDATE SET
                     lat=:lat, lon=:lon, altitude=:altitude, last_seen=:now""",
                {**info, "now": now_iso},
            )
            n_stations += 1
            if obs is not None:
                cur.execute(
                    """INSERT OR IGNORE INTO observations
                       (station_id, measured_at, fetched_at, temp_C, humidity,
                        pressure, rain_60min, rain_24h,
                        wind_strength, wind_angle, gust_strength)
                       VALUES (:station_id, :measured_at, :fetched_at, :temp_C,
                               :humidity, :pressure, :rain_60min, :rain_24h,
                               :wind_strength, :wind_angle, :gust_strength)""",
                    {**obs, "station_id": info["station_id"], "fetched_at": now_iso},
                )
                n_new_obs += cur.rowcount  # 1 if inserted, 0 if ignored as a duplicate

        time.sleep(PAUSE_S)

    con.commit()
    con.close()

    line = (f"{now_iso} tiles_ok={n_tiles_ok} tiles_err={n_tiles_err} "
            f"stations={n_stations} new_obs={n_new_obs} "
            f"duration_s={time.time() - started:.0f}")
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")
    print(line)


# --- Status --------------------------------------------------------------------

def show_status():
    con = open_db()
    cur = con.cursor()

    total = cur.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    stations = cur.execute("SELECT COUNT(*) FROM stations").fetchone()[0]
    last = cur.execute("SELECT MAX(measured_at) FROM observations").fetchone()[0]
    day_ago = int(time.time()) - 86400
    last24h = cur.execute(
        "SELECT COUNT(*) FROM observations WHERE measured_at > ?", (day_ago,)
    ).fetchone()[0]

    print(f"Total observations      : {total}")
    print(f"Known stations          : {stations}")
    print(f"Observations in 24 h    : {last24h}")
    if last:
        age_min = (time.time() - last) / 60
        print(f"Latest measurement      : {age_min:.0f} min ago")
        if age_min > 60:
            print("⚠  Over one hour without data: check cron / network / token.")
    else:
        print("No data yet.")
    con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true",
                        help="show the health of the collection instead of collecting")
    args = parser.parse_args()

    if args.status:
        show_status()
    else:
        try:
            run_pass()
        except Exception as e:
            # Any unexpected error is logged then re-raised: cron will run again.
            msg = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} FATAL {e!r}"
            with open(LOG_FILE, "a") as f:
                f.write(msg + "\n")
            print(msg, file=sys.stderr)
            raise