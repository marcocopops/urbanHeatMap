"""
Interactive map of the predicted heat anomaly.

Renders the grid predictions as coloured cells over a real basemap, so the
model output can be checked against actual parks, forests and built-up areas.

Produces a self-contained HTML file: open it in a browser, toggle layers,
zoom around.

------------------------------------------------------------------------------
Requirements:
    pip install -r requirements.txt

Inputs:
    data/grid_prediction_<res>m.csv   from predict_grid.py
    data/uhi_netatmo.sqlite           for the optional station overlay

Usage:
    python model/map_prediction.py --resolution 200
------------------------------------------------------------------------------
"""

import argparse
import sqlite3
from pathlib import Path

import folium
import pandas as pd
from branca.colormap import LinearColormap
from folium.plugins import Fullscreen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_FILE = DATA_DIR / "uhi_netatmo.sqlite"

# Metres per degree at Paris latitude, used to size the cells.
M_PER_DEG_LAT = 111_320
M_PER_DEG_LON = 73_500


def add_grid_layer(fmap, grid, resolution, colormap, feature_cols):
    """Draw one rectangle per grid cell, coloured by predicted anomaly."""
    half_lat = resolution / M_PER_DEG_LAT / 2
    half_lon = resolution / M_PER_DEG_LON / 2

    layer = folium.FeatureGroup(name="Predicted anomaly", show=True)
    for row in grid.itertuples(index=False):
        # Compact HTML table: prediction first, then the features behind it
        rows = "".join(
            f"<tr><td style='padding-right:8px'>{c}</td>"
            f"<td style='text-align:right'>{getattr(row, c):.3f}</td></tr>"
            for c in feature_cols
        )
        tooltip = (
            f"<b>{row.prediction:+.2f} °C</b>"
            f"<table style='font-size:11px;margin-top:4px'>{rows}</table>"
        )
        folium.Rectangle(
            bounds=[[row.lat - half_lat, row.lon - half_lon],
                    [row.lat + half_lat, row.lon + half_lon]],
            color=None,
            fill=True,
            fill_color=colormap(row.prediction),
            fill_opacity=0.55,
            weight=0,
            tooltip=folium.Tooltip(tooltip, sticky=True),
        ).add_to(layer)
    layer.add_to(fmap)


def add_station_layer(fmap, colormap):
    """Optional overlay: the stations the model was trained on."""
    target_csv = DATA_DIR / "station_target.csv"
    if not target_csv.exists():
        return
    con = sqlite3.connect(DB_FILE)
    coords = pd.read_sql("SELECT station_id, lat, lon FROM stations", con)
    con.close()
    obs = pd.read_csv(target_csv).merge(coords, on="station_id")

    layer = folium.FeatureGroup(name="Observed stations", show=False)
    for r in obs.itertuples(index=False):
        folium.CircleMarker(
            location=[r.lat, r.lon],
            radius=3,
            color="#333333",
            weight=0.5,
            fill=True,
            fill_color=colormap(r.anomaly_mean),
            fill_opacity=0.9,
            tooltip=f"observed {r.anomaly_mean:+.2f} °C",
        ).add_to(layer)
    layer.add_to(fmap)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resolution", type=int, default=200)
    args = parser.parse_args()

    csv_in = DATA_DIR / f"grid_prediction_{args.resolution}m.csv"
    grid = pd.read_csv(csv_in)
    print(f"{len(grid)} cells loaded from {csv_in.name}")

    # Symmetric colour scale around zero so warm/cool read correctly.
    limit = max(abs(grid.prediction.min()), abs(grid.prediction.max()))
    colormap = LinearColormap(
        colors=["#2166ac", "#67a9cf", "#f7f7f7", "#ef8a62", "#b2182b"],
        vmin=-limit, vmax=limit,
        caption="Predicted nighttime temperature anomaly (°C)",
    )

    fmap = folium.Map(
        location=[grid.lat.mean(), grid.lon.mean()],
        zoom_start=12,
        tiles="CartoDB positron",
    )
    # A second basemap makes it easy to check predictions against real land cover.
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(fmap)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Satellite", show=False,
    ).add_to(fmap)

    feature_cols = [c for c in grid.columns if c not in ("lat", "lon", "prediction")]
    print(f"{len(feature_cols)} features available in tooltips")

    add_grid_layer(fmap, grid, args.resolution, colormap, feature_cols)
    add_station_layer(fmap, colormap)

    colormap.add_to(fmap)
    Fullscreen().add_to(fmap)
    folium.LayerControl(collapsed=False).add_to(fmap)

    html_out = DATA_DIR / f"prediction_map_{args.resolution}m.html"
    fmap.save(html_out)
    print(f"Wrote {html_out}")


if __name__ == "__main__":
    main()