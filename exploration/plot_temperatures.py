"""
Quick look at the collected temperature data.

Draws three stacked panels sharing a time axis:

  1. City temperature      : median across stations, with the 10th-90th
                             percentile band (the spatial spread).
  2. Inter-station spread  : p90 - p10, a rough proxy for the urban heat
                             island signal. Expect it to widen at night.
  3. Reporting stations    : how many stations reported each hour, i.e. a
                             data-health check for collection gaps.

Medians and percentiles are used instead of means: citizen weather stations
produce outliers (sun-exposed sensors), and rank statistics ignore them.

------------------------------------------------------------------------------
Requirements:
    pip install -r requirements.txt

Usage:
    python exploration/plot_temperatures.py            # last 7 days
    python exploration/plot_temperatures.py --days 30  # last 30 days
------------------------------------------------------------------------------
"""

import argparse
import sqlite3
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # render to file, no display server needed
import matplotlib.pyplot as plt
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_FILE = DATA_DIR / "uhi_netatmo.sqlite"
PNG_OUT = DATA_DIR / "temperature_overview.png"

LOCAL_TZ = "Europe/Paris"


def load_hourly(days):
    """
    Hourly mean temperature per station over the last `days` days.

    Aggregation happens in SQL so that only a few hundred thousand rows reach
    pandas rather than every raw observation.
    """
    since = int(time.time()) - days * 86400
    query = """
        SELECT station_id,
               CAST(measured_at / 3600 AS INTEGER) * 3600 AS hour_ts,
               AVG(temp_C) AS temp_C
        FROM observations
        WHERE temp_C IS NOT NULL
          AND measured_at >= ?
        GROUP BY station_id, hour_ts
    """
    con = sqlite3.connect(DB_FILE)
    df = pd.read_sql(query, con, params=(since,))
    con.close()

    # measured_at is a UTC epoch; convert to local time for readable axes.
    df["time"] = (pd.to_datetime(df["hour_ts"], unit="s", utc=True)
                    .dt.tz_convert(LOCAL_TZ))
    return df


def summarize(df):
    """Per-hour statistics across all stations."""
    g = df.groupby("time")["temp_C"]
    out = pd.DataFrame({
        "median": g.median(),
        "p10": g.quantile(0.10),
        "p90": g.quantile(0.90),
        "n_stations": g.size(),
    })
    out["spread"] = out["p90"] - out["p10"]
    return out


def plot(stats, days):
    fig, (ax1, ax2, ax3) = plt.subplots(
        3, 1, figsize=(13, 9), sharex=True,
        gridspec_kw={"height_ratios": [3, 2, 1]},
    )

    # --- Panel 1: city temperature -------------------------------------------
    ax1.fill_between(stats.index, stats["p10"], stats["p90"],
                     alpha=0.25, color="tab:orange",
                     label="10th-90th percentile (across stations)")
    ax1.plot(stats.index, stats["median"], color="tab:red", lw=1.5,
             label="Median across stations")
    ax1.set_ylabel("Temperature (°C)")
    ax1.set_title(f"Netatmo network overview - last {days} days")
    ax1.legend(loc="upper left")
    ax1.grid(alpha=0.3)

    # --- Panel 2: spread (UHI proxy) -----------------------------------------
    ax2.plot(stats.index, stats["spread"], color="tab:blue", lw=1.2)
    ax2.set_ylabel("Spread p90-p10 (°C)")
    ax2.grid(alpha=0.3)
    ax2.set_title("Inter-station spread (rough urban heat island proxy)",
                  fontsize=10)

    # --- Panel 3: data health ------------------------------------------------
    ax3.plot(stats.index, stats["n_stations"], color="tab:green", lw=1)
    ax3.set_ylabel("Stations")
    ax3.set_xlabel("Local time")
    ax3.grid(alpha=0.3)
    ax3.set_title("Stations reporting per hour", fontsize=10)

    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(PNG_OUT, dpi=130)
    print(f"Wrote {PNG_OUT}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7,
                        help="how many days back to plot (default: 7)")
    args = parser.parse_args()

    df = load_hourly(args.days)
    if df.empty:
        print("No data in the requested window.")
        return

    stats = summarize(df)
    print(f"{len(df)} station-hours | {df['station_id'].nunique()} stations "
          f"| {len(stats)} hourly points")
    print(stats[["median", "spread", "n_stations"]].describe().round(2).to_string())

    plot(stats, args.days)


if __name__ == "__main__":
    main()