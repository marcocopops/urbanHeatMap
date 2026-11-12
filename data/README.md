# data/

This directory is empty in the repository. Everything in it is generated locally
or downloaded, and is git-ignored. Raw Netatmo station data is not redistributed.

## What the scripts write here

| File | Written by |
|---|---|
| `uhi_netatmo.sqlite` | `collector/netatmo_collector.py`, plus the `station_features` table from `features/compute_features.py` |
| `collector.log`, `cron.log` | the collector and its cron job |
| `temperature_overview.png` | `exploration/plot_temperatures.py` |
| `station_features.csv` | `features/compute_features.py` |
| `station_target.csv` | `notebooks/night_selection.ipynb` |
| `grid_prediction_<res>m.csv`, `grid_prediction_<res>m.png` | `model/predict_grid.py` |
| `prediction_map_<res>m.html` | `model/map_prediction.py` |

## BD TOPO

The urban features need the IGN **BD TOPO**, GeoPackage format, Lambert-93,
Ile-de-France region (R11). Download it from
<https://geoservices.ign.fr/bdtopo>. The archive is several GB.

Either extract the 2026-06-15 edition at the project root, which is the default
location, or point to your file with an environment variable:

```bash
export BDTOPO_GPKG=/path/to/your/BDT_3-5_GPKG_LAMB93_R11.gpkg
```

The default path is defined at the top of `features/bdtopo.py`.
