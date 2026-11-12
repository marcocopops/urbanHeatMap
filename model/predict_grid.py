"""
Predict the nighttime heat anomaly on a regular grid over Paris.

Pipeline:
  1. build a regular grid of points over the area of interest
  2. compute the SAME urban features as for stations (features/bdtopo.py)
  3. train a Random Forest on the station dataset
  4. predict on every grid cell
  5. export predictions with their input features (CSV) and a quick-look map (PNG)

------------------------------------------------------------------------------
Requirements:
    pip install -r requirements.txt

Inputs:
    data/uhi_netatmo.sqlite      table `station_features`
    data/station_target.csv      station_id, anomaly_mean  (exported by the last
                                 code cell of notebooks/night_selection.ipynb)
    BD TOPO GeoPackage           see BDTOPO_GPKG in features/bdtopo.py

Usage:
    python model/predict_grid.py --resolution 200
------------------------------------------------------------------------------
"""

import argparse
import sqlite3
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))  # lets `features.bdtopo` resolve when run as a script

from features.bdtopo import CRS_METRIC, compute_buffer_features, load_bdtopo_layers

DATA_DIR = PROJECT_ROOT / "data"
DB_FILE = DATA_DIR / "uhi_netatmo.sqlite"
TARGET_CSV = DATA_DIR / "station_target.csv"

# Area to map (Paris and inner suburbs), in WGS84 degrees.
AREA = {"lat_min": 48.75, "lat_max": 48.95, "lon_min": 2.20, "lon_max": 2.50}


def build_grid(resolution_m):
    """Regular grid of points over AREA, spaced `resolution_m` metres apart."""
    corners = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy(
            [AREA["lon_min"], AREA["lon_max"]],
            [AREA["lat_min"], AREA["lat_max"]],
        ),
        crs="EPSG:4326",
    ).to_crs(CRS_METRIC)

    minx, miny = corners.geometry.x.min(), corners.geometry.y.min()
    maxx, maxy = corners.geometry.x.max(), corners.geometry.y.max()

    xs = np.arange(minx, maxx, resolution_m)
    ys = np.arange(miny, maxy, resolution_m)
    xx, yy = np.meshgrid(xs, ys)

    grid = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy(xx.ravel(), yy.ravel()), crs=CRS_METRIC
    )
    grid["x"], grid["y"] = grid.geometry.x, grid.geometry.y
    print(f"Grid: {len(xs)} x {len(ys)} = {len(grid)} cells at {resolution_m} m")
    return grid


def compute_grid_features(grid):
    """
    Urban features for every grid cell.

    Altitude is a station attribute we don't have on the grid, so it is not
    computed here and the map model is trained without it (see main).
    """
    buildings, vegetation, water = load_bdtopo_layers(grid)
    return compute_buffer_features(grid, buildings, vegetation, water, show_progress=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resolution", type=int, default=200,
                        help="grid spacing in metres (default: 200)")
    args = parser.parse_args()

    # --- Training data ------------------------------------------------------
    con = sqlite3.connect(DB_FILE)
    feat = pd.read_sql("SELECT * FROM station_features", con)
    stations = pd.read_sql("SELECT station_id, lat, lon FROM stations", con)
    con.close()
    target = pd.read_csv(TARGET_CSV)

    train = feat.merge(target, on="station_id").merge(stations, on="station_id")
    for c in [c for c in train.columns if c.startswith("mean_height")]:
        train[c] = train[c].fillna(0)

    FEATURES = [c for c in train.columns
                if c.startswith(("built_frac", "veg_frac", "mean_height"))] \
               + ["dist_water_m"]          # altitude excluded: not available on grid
    train = train.dropna(subset=FEATURES + ["anomaly_mean"])
    print(f"Training on {len(train)} stations, {len(FEATURES)} features")

    rf = RandomForestRegressor(n_estimators=300, min_samples_leaf=3,
                               n_jobs=-1, random_state=42)
    rf.fit(train[FEATURES], train["anomaly_mean"])

    # --- Grid ---------------------------------------------------------------
    grid = build_grid(args.resolution)
    gfeat = compute_grid_features(grid)
    for c in [c for c in gfeat.columns if c.startswith("mean_height")]:
        gfeat[c] = gfeat[c].fillna(0)
    gfeat = gfeat[FEATURES].fillna(0)

    grid["prediction"] = rf.predict(gfeat)

    # Back to lat/lon for export and plotting
    grid_wgs = grid.to_crs("EPSG:4326")
    grid["lon"], grid["lat"] = grid_wgs.geometry.x, grid_wgs.geometry.y

    out_csv = DATA_DIR / f"grid_prediction_{args.resolution}m.csv"
    export = grid[["lat", "lon", "prediction"]].copy()
    for c in FEATURES:                      # keep the inputs alongside the output
        export[c] = gfeat[c].values
    export.to_csv(out_csv, index=False)
    print(f"Wrote {out_csv}")

    # --- Quick-look map -----------------------------------------------------
    fig, ax = plt.subplots(figsize=(12, 10))
    sc = ax.scatter(grid["lon"], grid["lat"], c=grid["prediction"],
                    cmap="RdYlBu_r", s=6, marker="s",
                    vmin=-2, vmax=2)
    ax.set_aspect(1 / 0.66)
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    ax.set_title(f"Predicted nighttime temperature anomaly (°C) - {args.resolution} m grid")
    plt.colorbar(sc, label="Anomaly (°C)")
    png = DATA_DIR / f"grid_prediction_{args.resolution}m.png"
    fig.savefig(png, dpi=140, bbox_inches="tight")
    print(f"Wrote {png}")


if __name__ == "__main__":
    main()