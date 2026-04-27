"""
Driver Simulator for NYC Rideshare Operations Intelligence

Simulates 8,000 drivers with different behavioral profiles based on
demand patterns discovered in the analysis notebook.
"""

import random
import uuid
from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from typing import Optional

# PostgreSQL is optional - only needed for save_driver_states_to_db()
try:
    import psycopg2
    from psycopg2.extras import execute_values
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False
    psycopg2 = None


class DriverType(Enum):
    NORMAL = "normal"              # 83% - accept rides proportional to demand
    SURGE_GAMER = "surge_gamer"    # 8% - cluster in high demand, 40% lower acceptance
    CHERRY_PICKER = "cherry_picker" # 4% - only accept trips > 3 miles
    GHOST = "ghost"                # 3% - show available but 5% acceptance
    EFFICIENT = "efficient"        # 2% - follow demand signals, 95% acceptance


class DriverStatus(Enum):
    OFFLINE = "offline"
    AVAILABLE = "available"
    EN_ROUTE = "en_route"
    ON_TRIP = "on_trip"


@dataclass
class Driver:
    driver_id: str
    driver_type: DriverType
    current_zone_id: int
    status: DriverStatus
    acceptance_rate: float
    shift_start: time
    shift_end: time
    total_trips_today: int = 0
    last_trip_end: Optional[datetime] = None

    def is_on_shift(self, current_time: datetime) -> bool:
        """Check if driver is currently on shift."""
        current = current_time.time()
        if self.shift_start <= self.shift_end:
            return self.shift_start <= current <= self.shift_end
        else:
            # Overnight shift (e.g., 10 PM to 6 AM)
            return current >= self.shift_start or current <= self.shift_end

    def will_accept_trip(self, trip_miles: float) -> bool:
        """Determine if driver accepts a trip based on type and trip characteristics."""
        if self.driver_type == DriverType.CHERRY_PICKER:
            if trip_miles < 3.0:
                return False
            return random.random() < self.acceptance_rate

        return random.random() < self.acceptance_rate


# Borough pickup distribution from notebook analysis
BOROUGH_DEMAND_DISTRIBUTION = {
    "Manhattan": 0.365,
    "Brooklyn": 0.272,
    "Queens": 0.218,
    "Bronx": 0.129,
    "Staten Island": 0.016,
}

# Top zones by pickup volume (from notebook Section 4)
# zone_id: (zone_name, borough, relative_weight within borough)
TOP_ZONES = {
    # Queens - dominated by airports
    138: ("LaGuardia Airport", "Queens", 0.25),
    132: ("JFK Airport", "Queens", 0.21),
    7: ("Astoria", "Queens", 0.12),
    129: ("Jackson Heights", "Queens", 0.10),
    145: ("Long Island City/Hunters Point", "Queens", 0.08),
    178: ("Ridgewood", "Queens", 0.06),
    130: ("Jamaica", "Queens", 0.06),

    # Manhattan - mix of entertainment and business
    230: ("Times Sq/Theatre District", "Manhattan", 0.08),
    79: ("East Village", "Manhattan", 0.08),
    161: ("Midtown Center", "Manhattan", 0.07),
    229: ("TriBeCa/Civic Center", "Manhattan", 0.07),
    68: ("East Chelsea", "Manhattan", 0.06),
    234: ("Union Sq", "Manhattan", 0.06),
    246: ("West Chelsea/Hudson Yards", "Manhattan", 0.06),
    170: ("Midtown South", "Manhattan", 0.05),
    107: ("Gramercy", "Manhattan", 0.05),
    148: ("Lower East Side", "Manhattan", 0.05),
    41: ("Central Harlem North", "Manhattan", 0.05),
    158: ("Meatpacking/West Village Nort", "Manhattan", 0.05),
    186: ("Penn Station/Madison Sq West", "Manhattan", 0.04),
    163: ("Midtown North", "Manhattan", 0.04),

    # Brooklyn - strong residential demand
    61: ("Crown Heights North", "Brooklyn", 0.12),
    75: ("East New York", "Brooklyn", 0.10),
    39: ("Bushwick South", "Brooklyn", 0.10),
    181: ("Park Slope", "Brooklyn", 0.09),
    97: ("Greenpoint", "Brooklyn", 0.08),
    256: ("Williamsburg (North Side)", "Brooklyn", 0.08),
    257: ("Williamsburg (South Side)", "Brooklyn", 0.07),
    21: ("Bedford", "Brooklyn", 0.07),
    91: ("Flatbush/Ditmas Park", "Brooklyn", 0.07),
    38: ("Bushwick North", "Brooklyn", 0.07),

    # Bronx
    18: ("Bedford Park", "Bronx", 0.15),
    46: ("Co-Op City", "Bronx", 0.12),
    136: ("Kingsbridge Heights", "Bronx", 0.12),
    183: ("Pelham Bay", "Bronx", 0.10),
    69: ("East Concourse/Concourse Village", "Bronx", 0.10),

    # Staten Island
    5: ("Arden Heights", "Staten Island", 0.20),
    6: ("Arrochar/Fort Wadsworth", "Staten Island", 0.15),
    23: ("Bloomfield/Emerson Hill", "Staten Island", 0.15),
}

# Hourly demand multipliers - load from real TLC data if available
def _load_hourly_multipliers():
    """Load real hourly multipliers from preprocessed TLC data."""
    from pathlib import Path
    import json
    patterns_file = Path(__file__).parent / "data" / "demand_patterns.json"
    if patterns_file.exists():
        with open(patterns_file) as f:
            data = json.load(f)
        return {int(h): v for h, v in data["hourly_multipliers"].items()}
    # Fallback to estimates
    return {
        0: 0.45, 1: 0.30, 2: 0.22, 3: 0.15, 4: 0.12, 5: 0.15,
        6: 0.25, 7: 0.45, 8: 0.60, 9: 0.55, 10: 0.55, 11: 0.60,
        12: 0.65, 13: 0.65, 14: 0.70, 15: 0.75, 16: 0.85, 17: 0.95,
        18: 1.00, 19: 0.95, 20: 0.90, 21: 0.85, 22: 0.75, 23: 0.60,
    }

HOURLY_DEMAND_MULTIPLIER = _load_hourly_multipliers()

# Supply gap zones identified in notebook Section 7
SUPPLY_GAP_ZONES = {
    138, 132,  # Airports - long waits
    61, 75, 39,  # Brooklyn residential - high demand, above-avg waits
    230, 161,  # Manhattan high-traffic
    41, 21,  # Crown Heights, Bedford
}


class DriverSimulator:
    """Simulate driver behavior based on demand patterns from analysis."""

    def __init__(self, db_connection_string: Optional[str] = None):
        self.drivers: dict[str, Driver] = {}
        self.db_conn_string = db_connection_string
        self._zone_to_borough = {zid: info[1] for zid, info in TOP_ZONES.items()}

    def _get_db_connection(self):
        """Get PostgreSQL connection."""
        if not self.db_conn_string:
            raise ValueError("Database connection string not configured")
        return psycopg2.connect(self.db_conn_string)

    def _generate_shift_times(self, driver_type: DriverType) -> tuple[time, time]:
        """Generate realistic shift start/end times based on driver type."""
        if driver_type == DriverType.EFFICIENT:
            # Efficient drivers work peak hours
            shifts = [
                (time(6, 0), time(14, 0)),   # Morning rush
                (time(14, 0), time(22, 0)),  # Evening rush
                (time(16, 0), time(0, 0)),   # Evening peak
            ]
        elif driver_type == DriverType.SURGE_GAMER:
            # Surge gamers target high-demand periods
            shifts = [
                (time(17, 0), time(1, 0)),   # Evening/night
                (time(20, 0), time(4, 0)),   # Late night
                (time(6, 0), time(10, 0)),   # Morning rush only
            ]
        elif driver_type == DriverType.GHOST:
            # Ghost drivers have erratic schedules
            start_hour = random.randint(0, 23)
            duration = random.randint(2, 6)
            end_hour = (start_hour + duration) % 24
            return time(start_hour, 0), time(end_hour, 0)
        else:
            # Normal and cherry picker - standard shifts
            shifts = [
                (time(6, 0), time(14, 0)),
                (time(7, 0), time(15, 0)),
                (time(8, 0), time(16, 0)),
                (time(14, 0), time(22, 0)),
                (time(15, 0), time(23, 0)),
                (time(16, 0), time(0, 0)),
                (time(18, 0), time(2, 0)),
                (time(22, 0), time(6, 0)),
            ]

        return random.choice(shifts)

    def _get_acceptance_rate(self, driver_type: DriverType) -> float:
        """Get base acceptance rate for driver type."""
        rates = {
            DriverType.NORMAL: random.uniform(0.75, 0.90),
            DriverType.SURGE_GAMER: random.uniform(0.35, 0.55),  # 40% lower
            DriverType.CHERRY_PICKER: random.uniform(0.70, 0.85),
            DriverType.GHOST: random.uniform(0.03, 0.07),  # ~5%
            DriverType.EFFICIENT: random.uniform(0.93, 0.97),  # ~95%
        }
        return rates[driver_type]

    def _select_initial_zone(self, driver_type: DriverType) -> int:
        """Select initial zone for driver based on type and demand distribution."""
        # First select borough based on demand distribution
        borough = random.choices(
            list(BOROUGH_DEMAND_DISTRIBUTION.keys()),
            weights=list(BOROUGH_DEMAND_DISTRIBUTION.values()),
            k=1
        )[0]

        # Get zones in this borough
        borough_zones = [
            (zid, info[2]) for zid, info in TOP_ZONES.items()
            if info[1] == borough
        ]

        if not borough_zones:
            # Fallback to any zone
            borough_zones = [(zid, info[2]) for zid, info in TOP_ZONES.items()]

        # Surge gamers prefer supply gap zones
        if driver_type == DriverType.SURGE_GAMER:
            gap_zones = [(zid, w) for zid, w in borough_zones if zid in SUPPLY_GAP_ZONES]
            if gap_zones:
                borough_zones = gap_zones

        # Efficient drivers spread more evenly
        if driver_type == DriverType.EFFICIENT:
            zone_ids = [zid for zid, _ in borough_zones]
            return random.choice(zone_ids)

        # Weight by zone demand
        zone_ids = [zid for zid, _ in borough_zones]
        weights = [w for _, w in borough_zones]

        return random.choices(zone_ids, weights=weights, k=1)[0]

    def initialize_drivers(self, n: int = 8000) -> dict[str, Driver]:
        """
        Initialize n drivers with proper type distribution and placement.

        Distribution:
        - 83% normal
        - 8% surge gamers
        - 4% cherry pickers
        - 3% ghost drivers
        - 2% efficient drivers
        """
        type_distribution = [
            (DriverType.NORMAL, 0.83),
            (DriverType.SURGE_GAMER, 0.08),
            (DriverType.CHERRY_PICKER, 0.04),
            (DriverType.GHOST, 0.03),
            (DriverType.EFFICIENT, 0.02),
        ]

        types = []
        for dtype, pct in type_distribution:
            count = int(n * pct)
            types.extend([dtype] * count)

        # Fill remaining due to rounding
        while len(types) < n:
            types.append(DriverType.NORMAL)

        random.shuffle(types)

        self.drivers = {}
        for i, driver_type in enumerate(types):
            driver_id = f"DRV-{uuid.uuid4().hex[:8].upper()}"
            shift_start, shift_end = self._generate_shift_times(driver_type)

            driver = Driver(
                driver_id=driver_id,
                driver_type=driver_type,
                current_zone_id=self._select_initial_zone(driver_type),
                status=DriverStatus.OFFLINE,
                acceptance_rate=self._get_acceptance_rate(driver_type),
                shift_start=shift_start,
                shift_end=shift_end,
            )
            self.drivers[driver_id] = driver

        print(f"Initialized {len(self.drivers)} drivers:")
        type_counts = {}
        for d in self.drivers.values():
            type_counts[d.driver_type.value] = type_counts.get(d.driver_type.value, 0) + 1
        for dtype, count in sorted(type_counts.items()):
            print(f"  {dtype}: {count} ({count/n*100:.1f}%)")

        return self.drivers

    def simulate_hour(
        self,
        hour: int,
        month: str,
        demand_data: Optional[dict] = None,
        current_date: Optional[datetime] = None
    ) -> dict:
        """
        Simulate driver behavior for a given hour.

        Args:
            hour: Hour of day (0-23)
            month: Month string ('jan', 'jun', 'dec')
            demand_data: Optional dict of zone_id -> demand count
            current_date: Current datetime for shift checking

        Returns:
            Dict with simulation results
        """
        if current_date is None:
            current_date = datetime.now().replace(hour=hour, minute=0, second=0)

        demand_multiplier = HOURLY_DEMAND_MULTIPLIER.get(hour, 0.5)

        # Monthly adjustment (December higher, June lower from notebook)
        month_multiplier = {"jan": 1.0, "jun": 0.90, "dec": 1.08}.get(month, 1.0)

        results = {
            "hour": hour,
            "month": month,
            "drivers_online": 0,
            "drivers_available": 0,
            "drivers_on_trip": 0,
            "zone_supply": {},
            "movements": [],
        }

        for driver in self.drivers.values():
            # Check if on shift
            if driver.is_on_shift(current_date):
                if driver.status == DriverStatus.OFFLINE:
                    driver.status = DriverStatus.AVAILABLE
                results["drivers_online"] += 1
            else:
                driver.status = DriverStatus.OFFLINE
                continue

            # Move drivers based on type
            new_zone = self._decide_movement(driver, hour, demand_data)
            if new_zone != driver.current_zone_id:
                results["movements"].append({
                    "driver_id": driver.driver_id,
                    "from_zone": driver.current_zone_id,
                    "to_zone": new_zone,
                })
                driver.current_zone_id = new_zone

            # Count by status
            if driver.status == DriverStatus.AVAILABLE:
                results["drivers_available"] += 1
            elif driver.status == DriverStatus.ON_TRIP:
                results["drivers_on_trip"] += 1

            # Track zone supply
            zone_id = driver.current_zone_id
            if zone_id not in results["zone_supply"]:
                results["zone_supply"][zone_id] = {"available": 0, "total": 0}
            results["zone_supply"][zone_id]["total"] += 1
            if driver.status == DriverStatus.AVAILABLE:
                results["zone_supply"][zone_id]["available"] += 1

        return results

    def _decide_movement(
        self,
        driver: Driver,
        hour: int,
        demand_data: Optional[dict]
    ) -> int:
        """Decide if and where a driver should move based on type."""
        current_zone = driver.current_zone_id

        # 70% of drivers stay put each hour
        if random.random() < 0.70:
            return current_zone

        current_borough = self._zone_to_borough.get(current_zone)

        if driver.driver_type == DriverType.SURGE_GAMER:
            # Move toward supply gap zones
            gap_zones = list(SUPPLY_GAP_ZONES)
            return random.choice(gap_zones)

        elif driver.driver_type == DriverType.EFFICIENT:
            # Move toward high demand zones not in gaps (better service)
            if demand_data:
                # Find zones with high demand but not oversupplied
                sorted_zones = sorted(demand_data.items(), key=lambda x: x[1], reverse=True)
                top_zones = [z for z, _ in sorted_zones[:10] if z not in SUPPLY_GAP_ZONES]
                if top_zones:
                    return random.choice(top_zones)
            # Default: stay in borough, move to high-demand zone
            borough_zones = [
                zid for zid, info in TOP_ZONES.items()
                if info[1] == current_borough
            ]
            return random.choice(borough_zones) if borough_zones else current_zone

        elif driver.driver_type == DriverType.CHERRY_PICKER:
            # Prefer airport zones (longer trips)
            airport_zones = [138, 132]  # LGA, JFK
            if random.random() < 0.4:
                return random.choice(airport_zones)
            return current_zone

        elif driver.driver_type == DriverType.GHOST:
            # Random movement
            all_zones = list(TOP_ZONES.keys())
            return random.choice(all_zones)

        else:  # NORMAL
            # Move within borough, slight preference for high-demand zones
            borough_zones = [
                (zid, info[2]) for zid, info in TOP_ZONES.items()
                if info[1] == current_borough
            ]
            if borough_zones:
                zone_ids = [zid for zid, _ in borough_zones]
                weights = [w for _, w in borough_zones]
                return random.choices(zone_ids, weights=weights, k=1)[0]
            return current_zone

    def calculate_zone_supply(self, zone_id: int, hour: int) -> dict:
        """
        Calculate available driver count for a zone at a given hour.

        Returns:
            Dict with supply metrics
        """
        current_time = datetime.now().replace(hour=hour, minute=0)

        available = 0
        total_on_shift = 0
        by_type = {}

        for driver in self.drivers.values():
            if driver.current_zone_id != zone_id:
                continue

            if not driver.is_on_shift(current_time):
                continue

            total_on_shift += 1
            dtype = driver.driver_type.value
            by_type[dtype] = by_type.get(dtype, 0) + 1

            if driver.status == DriverStatus.AVAILABLE:
                available += 1

        # Effective supply accounts for ghost drivers
        ghost_count = by_type.get("ghost", 0)
        effective_available = available - (ghost_count * 0.95)  # Ghosts rarely accept

        return {
            "zone_id": zone_id,
            "hour": hour,
            "total_on_shift": total_on_shift,
            "available": available,
            "effective_available": max(0, effective_available),
            "by_type": by_type,
        }

    def get_supply_demand_ratio(
        self,
        zone_id: int,
        hour: int,
        demand_count: Optional[int] = None
    ) -> dict:
        """
        Calculate supply/demand ratio for recommendation engine.

        Args:
            zone_id: Zone to calculate ratio for
            hour: Hour of day
            demand_count: Actual or estimated demand. If None, uses historical avg.

        Returns:
            Dict with ratio and recommendation signals
        """
        supply = self.calculate_zone_supply(zone_id, hour)

        # Estimate demand if not provided
        if demand_count is None:
            # Use hourly multiplier and zone weight as proxy
            zone_info = TOP_ZONES.get(zone_id)
            if zone_info:
                base_demand = zone_info[2] * 1000  # Scale factor
                demand_count = int(base_demand * HOURLY_DEMAND_MULTIPLIER.get(hour, 0.5))
            else:
                demand_count = 50  # Default

        effective_supply = supply["effective_available"]

        # Calculate ratio (higher = more supply per demand)
        if demand_count > 0:
            ratio = effective_supply / demand_count
        else:
            ratio = float('inf') if effective_supply > 0 else 0

        # Determine status
        if ratio < 0.5:
            status = "critical_undersupply"
            recommendation = "urgent_reposition"
        elif ratio < 0.8:
            status = "undersupply"
            recommendation = "suggest_reposition"
        elif ratio < 1.2:
            status = "balanced"
            recommendation = "maintain"
        elif ratio < 2.0:
            status = "oversupply"
            recommendation = "allow_drift"
        else:
            status = "excess_supply"
            recommendation = "encourage_reposition_out"

        return {
            "zone_id": zone_id,
            "zone_name": TOP_ZONES.get(zone_id, (None,))[0],
            "hour": hour,
            "supply": effective_supply,
            "demand": demand_count,
            "ratio": round(ratio, 3),
            "status": status,
            "recommendation": recommendation,
            "is_supply_gap_zone": zone_id in SUPPLY_GAP_ZONES,
        }

    def save_driver_states_to_db(self, timestamp: Optional[datetime] = None):
        """Save current driver states to PostgreSQL."""
        if not HAS_PSYCOPG2:
            raise ImportError("psycopg2 not installed. Run: pip install psycopg2-binary")

        if timestamp is None:
            timestamp = datetime.now()

        conn = self._get_db_connection()
        cur = conn.cursor()

        # Create table if not exists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS driver_states (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP NOT NULL,
                driver_id VARCHAR(20) NOT NULL,
                driver_type VARCHAR(20) NOT NULL,
                current_zone_id INTEGER NOT NULL,
                status VARCHAR(20) NOT NULL,
                acceptance_rate FLOAT NOT NULL,
                shift_start TIME NOT NULL,
                shift_end TIME NOT NULL,
                total_trips_today INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_driver_states_timestamp
            ON driver_states(timestamp);

            CREATE INDEX IF NOT EXISTS idx_driver_states_zone
            ON driver_states(current_zone_id, timestamp);
        """)

        # Prepare data
        records = [
            (
                timestamp,
                d.driver_id,
                d.driver_type.value,
                d.current_zone_id,
                d.status.value,
                d.acceptance_rate,
                d.shift_start,
                d.shift_end,
                d.total_trips_today,
            )
            for d in self.drivers.values()
        ]

        # Bulk insert
        execute_values(
            cur,
            """
            INSERT INTO driver_states
            (timestamp, driver_id, driver_type, current_zone_id, status,
             acceptance_rate, shift_start, shift_end, total_trips_today)
            VALUES %s
            """,
            records
        )

        conn.commit()
        cur.close()
        conn.close()

        print(f"Saved {len(records)} driver states at {timestamp}")

    def get_fleet_summary(self) -> dict:
        """Get summary statistics for the current fleet state."""
        summary = {
            "total_drivers": len(self.drivers),
            "by_type": {},
            "by_status": {},
            "by_borough": {},
        }

        for driver in self.drivers.values():
            # By type
            dtype = driver.driver_type.value
            summary["by_type"][dtype] = summary["by_type"].get(dtype, 0) + 1

            # By status
            status = driver.status.value
            summary["by_status"][status] = summary["by_status"].get(status, 0) + 1

            # By borough
            borough = self._zone_to_borough.get(driver.current_zone_id, "Unknown")
            summary["by_borough"][borough] = summary["by_borough"].get(borough, 0) + 1

        return summary


def main():
    """Demo the driver simulator."""
    print("=" * 60)
    print("NYC Rideshare Driver Simulator")
    print("=" * 60)

    # Initialize simulator (no DB for demo)
    sim = DriverSimulator()

    # Create 8000 drivers
    print("\n[1] Initializing drivers...")
    sim.initialize_drivers(n=8000)

    # Show fleet summary
    print("\n[2] Fleet summary:")
    summary = sim.get_fleet_summary()
    print(f"  Total drivers: {summary['total_drivers']}")
    print(f"  By borough:")
    for borough, count in sorted(summary["by_borough"].items(), key=lambda x: -x[1]):
        print(f"    {borough}: {count}")

    # Simulate an hour
    print("\n[3] Simulating 6 PM (peak hour)...")
    results = sim.simulate_hour(hour=18, month="dec")
    print(f"  Drivers online: {results['drivers_online']}")
    print(f"  Drivers available: {results['drivers_available']}")
    print(f"  Drivers on trip: {results['drivers_on_trip']}")
    print(f"  Driver movements: {len(results['movements'])}")

    # Check supply/demand for key zones
    print("\n[4] Supply/Demand ratios for key zones at 6 PM:")
    key_zones = [138, 61, 230, 75]  # LGA, Crown Heights N, Times Sq, East New York
    for zone_id in key_zones:
        ratio = sim.get_supply_demand_ratio(zone_id, hour=18)
        print(f"  {ratio['zone_name']}: ratio={ratio['ratio']:.2f}, "
              f"status={ratio['status']}, rec={ratio['recommendation']}")

    # Compare overnight
    print("\n[5] Simulating 4 AM (low supply)...")
    results_night = sim.simulate_hour(hour=4, month="dec")
    print(f"  Drivers online: {results_night['drivers_online']}")
    print(f"  Drivers available: {results_night['drivers_available']}")

    print("\n[6] Supply/Demand ratios at 4 AM:")
    for zone_id in key_zones:
        ratio = sim.get_supply_demand_ratio(zone_id, hour=4)
        print(f"  {ratio['zone_name']}: ratio={ratio['ratio']:.2f}, "
              f"status={ratio['status']}")

    print("\n" + "=" * 60)
    print("Simulation complete.")
    print("To save to PostgreSQL, configure db_connection_string and call")
    print("sim.save_driver_states_to_db()")
    print("=" * 60)


if __name__ == "__main__":
    main()
