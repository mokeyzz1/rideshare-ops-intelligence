"""
Preprocess TLC trip data to extract real demand patterns.
Run once to generate demand_patterns.json used by the dashboard.
"""

import json
import pandas as pd
from pathlib import Path

DATA_DIR = Path("data")
OUTPUT_FILE = DATA_DIR / "demand_patterns.json"

# Map month numbers to file suffixes
MONTH_FILES = {
    1: "fhvhv_tripdata_2025-01.parquet",
    6: "fhvhv_tripdata_2025-06.parquet",
    12: "fhvhv_tripdata_2025-12.parquet",
}

# Our 39 zones from ZONE_DATA in recommendations.py
ZONE_IDS = [
    5, 6, 7, 18, 21, 23, 38, 39, 41, 46, 61, 68, 69, 75, 79, 91, 97, 107, 129, 130,
    132, 136, 138, 145, 148, 158, 161, 163, 170, 178, 181, 183, 186, 229, 230, 234, 246, 256, 257
]


def process_month(month: int, filename: str) -> dict:
    """Extract hourly demand per zone for a given month."""
    filepath = DATA_DIR / filename
    print(f"Processing {filepath}...")

    df = pd.read_parquet(filepath, columns=["PULocationID", "pickup_datetime"])
    df = df[df["PULocationID"].isin(ZONE_IDS)]
    df["hour"] = pd.to_datetime(df["pickup_datetime"]).dt.hour

    # Count trips per zone per hour
    demand = df.groupby(["PULocationID", "hour"]).size().reset_index(name="trips")

    # Convert to nested dict: {zone_id: {hour: trips}}
    result = {}
    for zone_id in ZONE_IDS:
        zone_data = demand[demand["PULocationID"] == zone_id]
        result[int(zone_id)] = {
            int(row["hour"]): int(row["trips"])
            for _, row in zone_data.iterrows()
        }
        # Fill missing hours with 0
        for h in range(24):
            if h not in result[int(zone_id)]:
                result[int(zone_id)][h] = 0

    return result


def compute_hourly_multipliers(patterns: dict) -> dict:
    """Compute normalized hourly demand multipliers across all zones."""
    hourly_totals = {h: 0 for h in range(24)}

    for month_data in patterns.values():
        for zone_data in month_data.values():
            for hour, trips in zone_data.items():
                hourly_totals[int(hour)] += trips

    # Normalize so average = 1.0
    avg = sum(hourly_totals.values()) / 24
    return {h: round(total / avg, 3) for h, total in hourly_totals.items()}


def main():
    patterns = {}

    for month, filename in MONTH_FILES.items():
        patterns[month] = process_month(month, filename)

    # Compute overall hourly multipliers
    hourly_multipliers = compute_hourly_multipliers(patterns)

    output = {
        "patterns": {
            str(m): {
                str(z): {str(h): v for h, v in hours.items()}
                for z, hours in zones.items()
            }
            for m, zones in patterns.items()
        },
        "hourly_multipliers": {str(h): v for h, v in hourly_multipliers.items()},
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f)

    print(f"\nSaved to {OUTPUT_FILE}")
    print(f"Hourly multipliers: {hourly_multipliers}")

    # Show sample
    sample_zone = 161
    print(f"\nSample - Zone {sample_zone} (Midtown) January hourly demand:")
    jan_data = patterns[1][sample_zone]
    for h in range(24):
        bar = "█" * (jan_data[h] // 1000)
        print(f"  {h:02d}:00  {jan_data[h]:>6,}  {bar}")


if __name__ == "__main__":
    main()
