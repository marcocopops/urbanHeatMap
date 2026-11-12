"""
Urban features per station, from the IGN BD TOPO.

For each station in uhi_netatmo.sqlite, computes the features defined in
features/bdtopo.py (the altitude already comes from the `stations` table).

Writes the result to the `station_features` table of the same database, and to
data/station_features.csv for inspection.

------------------------------------------------------------------------------
Requirements:
    pip install -r requirements.txt
    BD TOPO GeoPackage: see BDTOPO_GPKG in features/bdtopo.py and data/README.md

Usage:
    python features/compute_features.py

Rough duration: a few minutes for ~3000 stations.
------------------------------------------------------------------------------
"""

import sqlite3
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))  # lets `features.bdtopo` resolve when run as a script

from features.bdtopo import CRS_METRIC, compute_buffer_features, load_bdtopo_layers

DATA_DIR = PROJECT_ROOT / "data"
DB_FILE = DATA_DIR / "uhi_netatmo.sqlite"
CSV_OUT = DATA_DIR / "station_features.csv"


def load_stations():
    """Stations (id, lat, lon, altitude) -> GeoDataFrame in Lambert-93."""
    con = sqlite3.connect(DB_FILE)
    df = pd.read_sql("SELECT station_id, lat, lon, altitude FROM stations", con)
    con.close()
    gdf = gpd.GeoDataFrame(
        df, geometry=gpd.points_from_xy(df.lon, df.lat), crs="EPSG:4326"
    )
    return gdf.to_crs(CRS_METRIC)


def main():
    stations = load_stations()
    print(f"{len(stations)} stations loaded.")

    buildings, vegetation, water = load_bdtopo_layers(stations)
    features = compute_buffer_features(stations, buildings, vegetation, water)

    out = stations[["station_id", "altitude"]].join(features)

    # Write both outputs: CSV + SQLite table (replaced on every run)
    out.to_csv(CSV_OUT, index=False)
    con = sqlite3.connect(DB_FILE)
    out.to_sql("station_features", con, if_exists="replace", index=False)
    con.close()

    print(f"\nWrote {CSV_OUT} + table station_features in {DB_FILE}")
    print(out.describe().round(2).to_string())


if __name__ == "__main__":
    main()
