# CLAUDE.md

Paris nighttime urban heat island (UHI) mapped with a Random Forest trained on
Netatmo citizen stations and IGN BD TOPO features. See README.md for the full story.

## Methodological invariants (do not change casually)

- **Target = anomaly**: station temperature minus the hourly median across all
  reporting stations (notebook cell "8 - Compute the hourly anomaly"). Never train on
  absolute temperature.
- **Validation = spatial block CV**: `GroupKFold(5)` over 0.02° lat/lon blocks.
  Never report random k-fold as the model's score; it is shown only as the leaky contrast.
- **Regime = calm nocturnal**: the model is valid only for calm (and nominally clear)
  nights. Do not present it as a general temperature model.
- **Forward collection**: the Netatmo API exposes no history for third-party stations.
  Data exists only because the collector ran; a gap in cron is a permanent gap in data.

## Never commit

- `collector/netatmo_tokens.json` (client_id, client_secret, refresh_token)
- `data/uhi_netatmo.sqlite` and any `*.sqlite*`
- derived CSVs (`station_features.csv`, `station_target.csv`, `grid_prediction_*.csv`)
- the BD TOPO archive / `*.gpkg`
- raw station identifiers (Netatmo MAC addresses) in notebook outputs: mask them

Only `data/README.md` is tracked under `data/`. Figures meant for the README go in
`docs/images/`. Check `git status --ignored` before any commit.

## Shared feature code

- Station features (`features/compute_features.py`) and grid features
  (`model/predict_grid.py`) MUST both go through `features/bdtopo.py`
  (`load_bdtopo_layers`, `compute_buffer_features`, `BUFFERS_M`, layer names).
  Never reimplement feature logic in one script: if they drift, the map is silently wrong.
- `mean_height_*` NaN (no building in buffer) is filled with 0 in both training and grid.
- The map model excludes `altitude` (not available on the grid): 10 features vs the
  11 validated in the notebook. The map model has no separate validation score.

## Changing a data-construction parameter

Parameters: `WIND_MAX`, `CLOUD_MAX`, `MIN_HOURS`, `CORE_HOURS`, `MIN_NIGHTS`,
`STD_MAX`, `ANOM_LIMIT`, `BLOCK_SIZE_DEG`, `BUFFERS_M`, any QC rule.

Any change must be reported as: **station count + MAE/RMSE (spatial CV)
+ both baselines (mean, nearest station) on the same dataset**. A lower RMSE on a
smaller or easier dataset is not an improvement. Current reference (README
"Results"): 3621 stations, RF spatial RMSE 1.143 vs mean 1.273 vs nearest 1.529.

Do not change thresholds, features or model hyperparameters
(`n_estimators=300, min_samples_leaf=3, random_state=42`) as part of a cleanup.

## Run order and outputs

| Step | Command | Produces |
|---|---|---|
| 0 | cron: `collector/netatmo_collector.py` every 15 min | `data/uhi_netatmo.sqlite` (stations, observations), `data/collector.log` |
| - | `python collector/netatmo_collector.py --status` | health check, no output file |
| - | `python exploration/plot_temperatures.py --days N` | `data/temperature_overview.png` |
| 1 | `python features/compute_features.py` | table `station_features` + `data/station_features.csv` |
| 2 | `notebooks/night_selection.ipynb` | metrics, figures, `data/station_target.csv` (last code cell) |
| 3 | `python model/predict_grid.py --resolution 200` | `data/grid_prediction_200m.csv` (+ features), `.png` |
| 4 | `python model/map_prediction.py --resolution 200` | `data/prediction_map_200m.html` |

- Scripts resolve paths from `PROJECT_ROOT = Path(__file__).resolve().parent.parent`;
  the notebook walks up from cwd to the directory holding `requirements.txt`.
- BD TOPO path: `BDTOPO_GPKG` env var, default in `features/bdtopo.py`.
- The notebook's last code cell reads `grid_prediction_200m.csv`, so it fails on a
  first run before step 3. Known, harmless.

## Deliberate vs missing

Deliberate (do not "fix" without discussion):
- `CLOUD_MAX = 100`: the cloud filter is inactive; nights are selected on wind only.
  The README says so in Limitations.
- Mean baseline is the global mean (not out-of-fold); nearest-station baseline uses
  the same spatial folds.
- No station coverage in Bois de Boulogne / Bois de Vincennes: extrapolated on purpose.

Open roadmap items (missing, not bugs):
- Sky view factor from BD TOPO altitudes.
- More BD TOPO features: wall/roof materials, building use, dwelling counts.
- Neighbour-based QC (CrowdQC+).
- Conditional model with weather as input, to go beyond the calm-night regime.
- Open notebook notes: check what `dropna` drops in "12 - Assemble X and y";
  try water fraction at 100 m / 1000 m instead of `dist_water_m`; grainy map texture.
