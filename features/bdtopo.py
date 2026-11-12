"""
BD TOPO feature logic shared by station features and grid features.

The model only makes sense if grid features are computed exactly like the
training features: same layers, same buffers, same projection. Both
features/compute_features.py and model/predict_grid.py import from this module,
so the two can never drift apart.

Features computed around each point:
  - built_frac_{100,250,500}   fraction of the buffer covered by buildings
  - mean_height_{100,250,500}  mean building height, weighted by footprint area
  - veg_frac_{100,250,500}     fraction of the buffer covered by vegetation
  - dist_water_m               distance to the nearest water surface

------------------------------------------------------------------------------
Data: IGN BD TOPO in GeoPackage format, Ile-de-France region (R11). See
data/README.md for the download link. Layers used: batiment,
zone_de_vegetation, surface_hydrographique. Check their exact names with:
    ogrinfo your_file.gpkg | grep -i <name>
------------------------------------------------------------------------------
"""

import os
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ------------------------------------------------------------------------------
# BD TOPO LOCATION: set the BDTOPO_GPKG environment variable to your .gpkg file.
# The default is where the 2026-06-15 Ile-de-France archive lands when extracted
# at the project root.
# ------------------------------------------------------------------------------
DEFAULT_BDTOPO_GPKG = (
    PROJECT_ROOT
    / "BDTOPO_3-5_TOUSTHEMES_GPKG_LAMB93_R11_2026-06-15"
    / "BDTOPO"
    / "1_DONNEES_LIVRAISON_2026-06-00419"
    / "BDT_3-5_GPKG_LAMB93_R11_ED2026-06-15"
    / "BDT_3-5_GPKG_LAMB93_R11-ED2026-06-15.gpkg"
)
BDTOPO_GPKG = Path(os.environ.get("BDTOPO_GPKG", DEFAULT_BDTOPO_GPKG))

LAYER_BUILDINGS = "batiment"
LAYER_VEGETATION = "zone_de_vegetation"
LAYER_WATER = "surface_hydrographique"

CRS_METRIC = "EPSG:2154"   # Lambert-93, the metric projection for France
BUFFERS_M = [100, 250, 500]


def load_layer(layer, bbox_geom, columns=None):
    """Load a BD TOPO layer, limited to the useful extent to save memory."""
    gdf = gpd.read_file(BDTOPO_GPKG, layer=layer, bbox=bbox_geom)
    if gdf.crs is None or gdf.crs.to_epsg() != 2154:
        gdf = gdf.to_crs(CRS_METRIC)
    if columns:
        keep = [c for c in columns if c in gdf.columns] + ["geometry"]
        gdf = gdf[keep]
    # Repair invalid geometries (common in large reference datasets)
    gdf["geometry"] = gdf.geometry.buffer(0)
    return gdf


def load_bdtopo_layers(points):
    """
    Load the buildings, vegetation and water layers around `points`.

    The extent is the points' bounding box plus a margin of the largest buffer,
    which avoids truncated polygons at the edges.
    """
    minx, miny, maxx, maxy = points.total_bounds
    margin = max(BUFFERS_M) + 100
    bbox_geom = box(minx - margin, miny - margin, maxx + margin, maxy + margin)

    print("Loading BD TOPO layers (this can take a while)...")
    buildings = load_layer(LAYER_BUILDINGS, bbox_geom, columns=["hauteur"])
    vegetation = load_layer(LAYER_VEGETATION, bbox_geom)
    water = load_layer(LAYER_WATER, bbox_geom)
    print(f"  buildings: {len(buildings)} | vegetation: {len(vegetation)}"
          f" | water: {len(water)}")
    return buildings, vegetation, water


def coverage_stats(buffers, polygons, height_col=None, desc=None):
    """
    For each buffer: fraction of the area covered by the polygons and, if
    height_col is given, the mean height weighted by covered area.

    Method: spatial join (spatial index) followed by a pairwise intersection.
    A progress bar is shown when `desc` is given.
    """
    joined = gpd.sjoin(buffers, polygons, how="left", predicate="intersects")

    frac = pd.Series(0.0, index=buffers.index)
    hmean = pd.Series(float("nan"), index=buffers.index)

    groups = joined.groupby(level=0)
    for buf_idx, group in tqdm(groups, total=len(buffers), desc=desc, disable=desc is None):
        if group["index_right"].isna().all():
            continue  # no polygon in this buffer
        buf_geom = buffers.geometry.loc[buf_idx]
        polys = polygons.loc[group["index_right"].dropna().astype(int)]
        inter_areas = polys.geometry.intersection(buf_geom).area
        total = inter_areas.sum()
        frac.loc[buf_idx] = total / buf_geom.area
        if height_col and total > 0:
            h = polys[height_col].fillna(0)
            hmean.loc[buf_idx] = (h * inter_areas).sum() / total

    return frac, hmean


def compute_buffer_features(points, buildings, vegetation, water, show_progress=False):
    """
    Compute every urban feature for `points` (a GeoDataFrame in CRS_METRIC).

    Returns a DataFrame indexed like `points`.
    """
    out = pd.DataFrame(index=points.index)

    for r in BUFFERS_M:
        print(f"Buffers {r} m...")
        buffers = points.copy()
        buffers["geometry"] = points.geometry.buffer(r)

        bf, bh = coverage_stats(buffers, buildings, height_col="hauteur",
                                desc=f"built {r}m" if show_progress else None)
        vf, _ = coverage_stats(buffers, vegetation,
                               desc=f"veg {r}m" if show_progress else None)

        out[f"built_frac_{r}"] = bf
        out[f"mean_height_{r}"] = bh
        out[f"veg_frac_{r}"] = vf

    print("Distance to water...")
    near = gpd.sjoin_nearest(points, water[["geometry"]], distance_col="dist_water_m")
    # A point can match several equidistant polygons: keep the first one
    near = near[~near.index.duplicated(keep="first")]
    out["dist_water_m"] = near["dist_water_m"]

    return out
