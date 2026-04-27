"""
Repositioning Recommendation Engine for NYC Rideshare Operations

This module provides the decision engine for driver repositioning recommendations
based on supply/demand analysis from the notebook and simulated driver positions.

IMPORTANT ASSUMPTIONS AND LIMITATIONS:
--------------------------------------
1. Wait times are ESTIMATED, not measured. We use a proxy model:
   estimated_wait = base_wait * (demand_factor / supply_factor)
   where base_wait = 4 minutes (NYC average from industry reports)

2. Demand data comes from 2025 TLC trip records (62M trips analyzed).
   We assume historical patterns predict future demand.

3. Driver positions come from simulation, not real GPS data.
   The simulator models behavioral archetypes but real driver behavior varies.

4. Revenue impact is ESTIMATED using:
   - Average fare: $18.50 (from notebook analysis)
   - Missed trips estimated from excess wait time

5. Zone distances are Euclidean (straight-line), not actual road distances.
   Real repositioning time would be longer due to traffic and routing.

6. "Drivers needed" assumes linear relationship between supply and wait time.
   Reality is more complex (queuing theory would be more accurate).

Author: Generated for rideshare-ops-intelligence project

"""

from dataclasses import dataclass
from typing import Optional
from pathlib import Path
import json
import math

from driver_simulator import BOROUGH_DEMAND_DISTRIBUTION as BOROUGH_DEMAND_SHARE

# =============================================================================
# LOAD REAL DEMAND PATTERNS FROM TLC DATA
# =============================================================================
# Preprocessed from 62M trip records - see preprocess_demand.py

DEMAND_PATTERNS_FILE = Path(__file__).parent / "data" / "demand_patterns.json"

def _load_demand_patterns():
    """Load preprocessed demand patterns from TLC data."""
    if DEMAND_PATTERNS_FILE.exists():
        with open(DEMAND_PATTERNS_FILE) as f:
            data = json.load(f)
        return {
            "patterns": data["patterns"],
            "hourly_multipliers": {int(h): v for h, v in data["hourly_multipliers"].items()},
        }
    return None

_DEMAND_DATA = _load_demand_patterns()

# Use real hourly multipliers if available, otherwise fall back to estimates
if _DEMAND_DATA:
    HOURLY_DEMAND_MULTIPLIER = _DEMAND_DATA["hourly_multipliers"]
else:
    # Fallback hardcoded values (shouldn't be used if data is preprocessed)
    HOURLY_DEMAND_MULTIPLIER = {
        0: 0.9, 1: 0.65, 2: 0.45, 3: 0.35, 4: 0.3, 5: 0.35,
        6: 0.5, 7: 0.8, 8: 1.0, 9: 1.05, 10: 1.0, 11: 1.05,
        12: 1.1, 13: 1.1, 14: 1.1, 15: 1.15, 16: 1.2, 17: 1.4,
        18: 1.5, 19: 1.5, 20: 1.45, 21: 1.45, 22: 1.4, 23: 1.15,
    }


# =============================================================================
# ZONE DATA
# =============================================================================
# Zone data aligned with driver_simulator.py TOP_ZONES
# Coordinates are approximate centroids for distance calculations
#
# IMPORTANT: These zone IDs must match the simulator's TOP_ZONES

ZONE_DATA = {
    # Queens - airports and high-demand areas
    138: {"name": "LaGuardia Airport", "borough": "Queens", "lat": 40.7769, "lon": -73.8740},
    132: {"name": "JFK Airport", "borough": "Queens", "lat": 40.6413, "lon": -73.7781},
    7: {"name": "Astoria", "borough": "Queens", "lat": 40.7720, "lon": -73.9300},
    129: {"name": "Jackson Heights", "borough": "Queens", "lat": 40.7560, "lon": -73.8830},
    145: {"name": "Long Island City/Hunters Point", "borough": "Queens", "lat": 40.7420, "lon": -73.9580},
    178: {"name": "Ridgewood", "borough": "Queens", "lat": 40.7120, "lon": -73.9050},
    130: {"name": "Jamaica", "borough": "Queens", "lat": 40.7020, "lon": -73.7890},

    # Manhattan - entertainment and business districts
    230: {"name": "Times Sq/Theatre District", "borough": "Manhattan", "lat": 40.7580, "lon": -73.9855},
    79: {"name": "East Village", "borough": "Manhattan", "lat": 40.7265, "lon": -73.9815},
    161: {"name": "Midtown Center", "borough": "Manhattan", "lat": 40.7549, "lon": -73.9840},
    229: {"name": "TriBeCa/Civic Center", "borough": "Manhattan", "lat": 40.7163, "lon": -74.0086},
    68: {"name": "East Chelsea", "borough": "Manhattan", "lat": 40.7465, "lon": -73.9950},
    234: {"name": "Union Sq", "borough": "Manhattan", "lat": 40.7359, "lon": -73.9911},
    246: {"name": "West Chelsea/Hudson Yards", "borough": "Manhattan", "lat": 40.7530, "lon": -74.0020},
    170: {"name": "Midtown South", "borough": "Manhattan", "lat": 40.7488, "lon": -73.9780},
    107: {"name": "Gramercy", "borough": "Manhattan", "lat": 40.7368, "lon": -73.9845},
    148: {"name": "Lower East Side", "borough": "Manhattan", "lat": 40.7150, "lon": -73.9850},
    41: {"name": "Central Harlem North", "borough": "Manhattan", "lat": 40.8186, "lon": -73.9398},
    158: {"name": "Meatpacking/West Village West", "borough": "Manhattan", "lat": 40.7395, "lon": -74.0055},
    186: {"name": "Penn Station/Madison Sq West", "borough": "Manhattan", "lat": 40.7506, "lon": -73.9930},
    163: {"name": "Midtown North", "borough": "Manhattan", "lat": 40.7614, "lon": -73.9776},

    # Brooklyn - residential demand zones
    61: {"name": "Crown Heights North", "borough": "Brooklyn", "lat": 40.6740, "lon": -73.9420},
    75: {"name": "East New York", "borough": "Brooklyn", "lat": 40.6660, "lon": -73.8820},
    39: {"name": "Bushwick South", "borough": "Brooklyn", "lat": 40.6880, "lon": -73.9130},
    181: {"name": "Park Slope", "borough": "Brooklyn", "lat": 40.6720, "lon": -73.9800},
    97: {"name": "Greenpoint", "borough": "Brooklyn", "lat": 40.7270, "lon": -73.9510},
    256: {"name": "Williamsburg (North Side)", "borough": "Brooklyn", "lat": 40.7180, "lon": -73.9570},
    257: {"name": "Williamsburg (South Side)", "borough": "Brooklyn", "lat": 40.7100, "lon": -73.9630},
    21: {"name": "Bedford", "borough": "Brooklyn", "lat": 40.6872, "lon": -73.9418},
    91: {"name": "Flatbush/Ditmas Park", "borough": "Brooklyn", "lat": 40.6380, "lon": -73.9590},
    38: {"name": "Bushwick North", "borough": "Brooklyn", "lat": 40.7000, "lon": -73.9210},

    # Bronx
    18: {"name": "Bedford Park", "borough": "Bronx", "lat": 40.8700, "lon": -73.8860},
    46: {"name": "Co-Op City", "borough": "Bronx", "lat": 40.8740, "lon": -73.8290},
    136: {"name": "Kingsbridge Heights", "borough": "Bronx", "lat": 40.8740, "lon": -73.8990},
    183: {"name": "Pelham Bay", "borough": "Bronx", "lat": 40.8520, "lon": -73.8330},
    69: {"name": "East Concourse/Concourse Village", "borough": "Bronx", "lat": 40.8260, "lon": -73.9180},

    # Staten Island
    5: {"name": "Arden Heights", "borough": "Staten Island", "lat": 40.5560, "lon": -74.1880},
    6: {"name": "Arrochar/Fort Wadsworth", "borough": "Staten Island", "lat": 40.5990, "lon": -74.0690},
    23: {"name": "Bloomfield/Emerson Hill", "borough": "Staten Island", "lat": 40.6080, "lon": -74.0960},
}
# =============================================================================
# DEMAND DATA FROM NOTEBOOK ANALYSIS
# =============================================================================
# HOURLY_DEMAND_MULTIPLIER and BOROUGH_DEMAND_SHARE imported from driver_simulator.py
# to avoid duplication (single source of truth)

# Monthly demand multipliers (relative to peak month)
MONTHLY_DEMAND_MULTIPLIER = {
    1: 0.85,   # January
    2: 0.82,
    3: 0.88,
    4: 0.92,
    5: 0.95,
    6: 1.00,   # June - peak
    7: 0.98,
    8: 0.95,
    9: 0.92,
    10: 0.95,
    11: 0.98,
    12: 1.05,  # December - holiday surge
}

# Base hourly demand per zone (estimated from 62M trips / 265 zones / 8760 hours)
# This is a rough average; actual demand varies significantly by zone
BASE_HOURLY_DEMAND_PER_ZONE = 27  # trips per hour on average

# Zone-specific demand multipliers for key zones identified in notebook
# Supply gap zones have HIGH demand but historically HIGH wait times
ZONE_DEMAND_MULTIPLIER = {
    # Supply gap zones from notebook Section 7
    138: 3.5,  # LaGuardia Airport - very high demand, variable supply
    132: 4.0,  # JFK Airport - highest demand, supply challenges
    61: 2.2,   # Crown Heights North - residential, underserved
    231: 3.0,  # Times Square - tourist hub, high demand
    76: 1.8,   # East New York - residential, underserved
    37: 1.9,   # Bushwick South - residential, underserved
    161: 2.8,  # Midtown Center - business district

    # High-demand Manhattan zones
    162: 2.5,  # Midtown East
    163: 2.6,  # Midtown North
    164: 2.4,  # Midtown South
    237: 2.2,  # Upper East Side South
    236: 2.0,  # Upper East Side North
    170: 2.3,  # Murray Hill

    # Brooklyn high-demand zones
    97: 1.8,   # Fort Greene
    188: 1.7,  # Prospect Heights
    255: 1.9,  # Williamsburg North Side

    # Queens high-demand zones
    129: 1.6,  # Jackson Heights
    7: 1.7,    # Astoria
}


# =============================================================================
# CONSTANTS AND CONFIGURATION
# =============================================================================

# Target wait time in minutes (ops goal)
TARGET_WAIT_TIME = 5.0

# Base wait time in minutes (NYC industry average from TLC reports)
# ASSUMPTION: This is an estimate based on industry reports, not measured data
BASE_WAIT_TIME = 4.0

# Average fare in dollars (from notebook analysis)
# Source: Mean of fare distributions across all trips
AVERAGE_FARE = 18.50

# Trips per driver per hour capacity
# ASSUMPTION: A driver can complete ~2 trips per hour on average
# (accounting for pickup, ride, dropoff, repositioning)
TRIPS_PER_DRIVER_PER_HOUR = 2.0

# Driver availability rate (percentage of drivers actually accepting rides)
# ASSUMPTION: Not all drivers are available at any given moment
DRIVER_AVAILABILITY_RATE = 0.75


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class RepositioningRecommendation:
    """
    A single repositioning recommendation.

    All wait times and revenue impacts are ESTIMATES based on proxy models,
    not measured values. See module docstring for assumptions.
    """
    zone_id: int
    zone_name: str
    borough: str
    estimated_wait_time: float  # minutes - ESTIMATED from demand/supply model
    drivers_needed: int         # to hit TARGET_WAIT_TIME
    recommended_source_zone_id: int
    recommended_source_zone_name: str
    source_zone_borough: str
    distance_km: float          # Euclidean distance - actual drive time is longer
    estimated_new_wait_time: float  # minutes - ESTIMATED after repositioning
    revenue_impact: float       # dollars - ESTIMATED fares from reduced missed trips
    current_supply: int         # drivers currently in zone (from simulation)
    current_demand: float       # estimated hourly trips
    confidence: str             # "high", "medium", "low" based on data quality

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "zone_id": self.zone_id,
            "zone_name": self.zone_name,
            "borough": self.borough,
            "estimated_wait_time": round(self.estimated_wait_time, 1),
            "drivers_needed": self.drivers_needed,
            "recommended_source_zone": {
                "zone_id": self.recommended_source_zone_id,
                "zone_name": self.recommended_source_zone_name,
                "borough": self.source_zone_borough,
            },
            "distance_km": round(self.distance_km, 2),
            "estimated_new_wait_time": round(self.estimated_new_wait_time, 1),
            "revenue_impact": round(self.revenue_impact, 2),
            "current_supply": self.current_supply,
            "current_demand": round(self.current_demand, 1),
            "confidence": self.confidence,
        }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great-circle distance between two points in kilometers.

    Note: This is straight-line distance. Actual driving distance and time
    will be longer due to road network and traffic.

    Args:
        lat1, lon1: Coordinates of first point
        lat2, lon2: Coordinates of second point

    Returns:
        Distance in kilometers
    """
    R = 6371  # Earth's radius in kilometers

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def get_zone_demand(zone_id: int, hour: int, month: int) -> float:
    """
    Get hourly demand for a zone from real TLC trip data.

    Uses preprocessed demand patterns from 62M trip records when available.
    Demand is scaled to match our simulated fleet size (1500 drivers).
    Falls back to estimate model if data not available.

    Args:
        zone_id: TLC zone ID
        hour: Hour of day (0-23)
        month: Month (1-12)

    Returns:
        Trips per hour for this zone (scaled to fleet size)
    """
    if zone_id not in ZONE_DATA:
        return 0.0

    # Try to get real demand from preprocessed TLC data
    if _DEMAND_DATA:
        # Map month to available data (we have Jan=1, Jun=6, Dec=12)
        if month in [12, 1, 2]:
            data_month = "12"  # Winter
        elif month in [6, 7, 8]:
            data_month = "6"   # Summer
        else:
            data_month = "1"   # Spring/Fall use January

        zone_str = str(zone_id)
        hour_str = str(hour)

        patterns = _DEMAND_DATA["patterns"]
        if data_month in patterns and zone_str in patterns[data_month]:
            zone_data = patterns[data_month][zone_str]
            if hour_str in zone_data:
                # Real data is monthly total - normalize to daily average
                trips_per_month = zone_data[hour_str]
                trips_per_day = trips_per_month / 31

                # Scale to match our 1500-driver fleet
                # Real NYC has ~50,000 active drivers, we simulate 1,500
                # Use 0.12 to create realistic mix of under/over supplied zones
                fleet_scale = 0.12
                return trips_per_day * fleet_scale

    # Fallback to estimate model
    zone_info = ZONE_DATA[zone_id]
    borough = zone_info["borough"]

    base_demand = BASE_HOURLY_DEMAND_PER_ZONE
    borough_share = BOROUGH_DEMAND_SHARE.get(borough, 0.01)
    borough_zones = sum(1 for z in ZONE_DATA.values() if z["borough"] == borough)
    borough_factor = (borough_share * len(ZONE_DATA)) / max(borough_zones, 1)
    zone_multiplier = ZONE_DEMAND_MULTIPLIER.get(zone_id, 1.0)
    hourly_mult = HOURLY_DEMAND_MULTIPLIER.get(hour, 0.5)
    monthly_mult = MONTHLY_DEMAND_MULTIPLIER.get(month, 1.0)

    return base_demand * borough_factor * zone_multiplier * hourly_mult * monthly_mult


def estimate_wait_time(demand: float, supply: int) -> float:
    """
    Estimate wait time based on demand and supply.

    MODEL ASSUMPTIONS:
    - Base wait time is 4 minutes at balanced supply/demand
    - Wait time increases as demand/supply ratio increases
    - Uses simple linear model: wait = base * (demand / (supply * capacity))
    - Minimum wait time is 2 minutes (driver already nearby)
    - Maximum wait time is 20 minutes (after which riders cancel)

    This is a SIMPLIFIED model. Real wait times depend on:
    - Geographic distribution of drivers within zone
    - Traffic conditions
    - Driver acceptance behavior
    - Rider patience and cancellation rates

    Args:
        demand: Estimated trips per hour
        supply: Number of available drivers in zone

    Returns:
        Estimated wait time in minutes
    """
    if supply <= 0:
        return 20.0  # Max wait time

    # Effective supply (accounting for availability rate)
    effective_supply = supply * DRIVER_AVAILABILITY_RATE

    # Capacity: how many trips can these drivers handle per hour
    capacity = effective_supply * TRIPS_PER_DRIVER_PER_HOUR

    if capacity <= 0:
        return 20.0

    # Demand/supply ratio
    ratio = demand / capacity

    # Wait time model: base * ratio, clamped to reasonable range
    wait_time = BASE_WAIT_TIME * ratio

    return max(2.0, min(20.0, wait_time))


def calculate_drivers_needed(current_demand: float, current_supply: int,
                            target_wait: float = TARGET_WAIT_TIME) -> int:
    """
    Calculate how many additional drivers are needed to hit target wait time.

    ASSUMPTIONS:
    - Linear relationship between supply and wait time (simplified)
    - Target can be achieved by adding drivers

    Args:
        current_demand: Estimated trips per hour
        current_supply: Current number of drivers
        target_wait: Target wait time in minutes

    Returns:
        Number of additional drivers needed (0 if already at target)
    """
    # Work backwards: what supply gives us target wait?
    # target_wait = BASE_WAIT_TIME * (demand / (supply * availability * trips_per_hour))
    # Solving for supply:
    # supply = (BASE_WAIT_TIME * demand) / (target_wait * availability * trips_per_hour)

    if target_wait <= 0:
        return 0

    needed_capacity = (BASE_WAIT_TIME * current_demand) / target_wait
    needed_supply = needed_capacity / (DRIVER_AVAILABILITY_RATE * TRIPS_PER_DRIVER_PER_HOUR)

    additional_needed = int(math.ceil(needed_supply - current_supply))

    return max(0, additional_needed)


def calculate_revenue_impact(current_wait: float, new_wait: float,
                            demand: float) -> float:
    """
    Estimate revenue impact from reducing wait time.

    MODEL ASSUMPTIONS:
    - Longer wait times lead to trip abandonment
    - Abandonment rate increases linearly from 0% at 2min to 50% at 15min
    - Revenue recovered = abandoned_trips * average_fare

    This is HIGHLY ESTIMATED. Real abandonment depends on:
    - Rider urgency and alternatives
    - Surge pricing
    - Weather
    - Time of day

    Args:
        current_wait: Current estimated wait time (minutes)
        new_wait: Projected wait time after repositioning (minutes)
        demand: Hourly demand (trips)

    Returns:
        Estimated hourly revenue impact in dollars
    """
    def abandonment_rate(wait: float) -> float:
        """Estimate trip abandonment rate based on wait time."""
        if wait <= 2:
            return 0.0
        elif wait >= 15:
            return 0.5
        else:
            # Linear interpolation
            return 0.5 * (wait - 2) / (15 - 2)

    current_abandonment = abandonment_rate(current_wait)
    new_abandonment = abandonment_rate(new_wait)

    # Trips recovered per hour
    trips_recovered = demand * (current_abandonment - new_abandonment)

    # Revenue from recovered trips
    return trips_recovered * AVERAGE_FARE


# Global simulator instance (lazy-loaded)
_simulator = None


def set_simulator(sim):
    """Set the global simulator instance (for sharing with app.py)."""
    global _simulator
    _simulator = sim


def _get_simulator():
    """
    Get or create the global simulator instance.

    Returns:
        DriverSimulator instance or None if unavailable
    """
    global _simulator
    if _simulator is not None:
        return _simulator

    try:
        from driver_simulator import DriverSimulator
        _simulator = DriverSimulator()
        _simulator.initialize_drivers(n=8000)
        return _simulator
    except ImportError:
        return None


def get_supply_from_simulator(zone_id: int, hour: int) -> int:
    """
    Get current driver supply from the simulator.

    Attempts to use the driver_simulator module.
    Falls back to estimate if simulator not available.

    Args:
        zone_id: TLC zone ID
        hour: Hour of day

    Returns:
        Number of drivers in zone
    """
    sim = _get_simulator()

    if sim is not None:
        result = sim.calculate_zone_supply(zone_id, hour)
        # Use total_on_shift as supply proxy (drivers in zone during their shift)
        # Note: "available" would be 0 if simulate_hour hasn't run
        return result.get("total_on_shift", 0)

    # Fallback: estimate supply based on demand distribution
    # This is very rough - simulator is preferred
    if zone_id not in ZONE_DATA:
        return 0

    # Assume 8000 drivers distributed proportionally to demand
    total_drivers = 8000
    zone_demand = get_zone_demand(zone_id, hour, 6)  # Use June as baseline
    total_demand = sum(get_zone_demand(z, hour, 6) for z in ZONE_DATA.keys())

    if total_demand <= 0:
        return 0

    return int(total_drivers * zone_demand / total_demand)


def find_nearest_oversupplied_zone(target_zone_id: int, hour: int,
                                   month: int) -> Optional[tuple]:
    """
    Find the nearest zone with excess supply.

    A zone is considered oversupplied if:
    - Estimated wait time < 3 minutes (below target)
    - Has at least 2 available drivers to spare

    Args:
        target_zone_id: Zone needing drivers
        hour: Hour of day
        month: Month

    Returns:
        Tuple of (zone_id, distance_km, excess_drivers) or None
    """
    if target_zone_id not in ZONE_DATA:
        return None

    target = ZONE_DATA[target_zone_id]

    candidates = []

    for zone_id, zone_info in ZONE_DATA.items():
        if zone_id == target_zone_id:
            continue

        # Get supply and demand
        supply = get_supply_from_simulator(zone_id, hour)
        demand = get_zone_demand(zone_id, hour, month)
        wait_time = estimate_wait_time(demand, supply)

        # Check if oversupplied (wait time below target with margin)
        if wait_time < 3.0 and supply >= 2:
            # Calculate excess drivers that could be repositioned
            excess = max(0, supply - int(demand / (DRIVER_AVAILABILITY_RATE * TRIPS_PER_DRIVER_PER_HOUR)) - 1)

            if excess >= 1:
                distance = haversine_distance(
                    target["lat"], target["lon"],
                    zone_info["lat"], zone_info["lon"]
                )
                candidates.append((zone_id, distance, excess))

    if not candidates:
        return None

    # Sort by distance
    candidates.sort(key=lambda x: x[1])

    return candidates[0]


# =============================================================================
# MAIN RECOMMENDATION FUNCTION
# =============================================================================

def get_repositioning_recommendations(hour: int, month: int, n: int = 5) -> list:
    """
    Get top N zones needing driver repositioning.

    This function analyzes supply/demand across all NYC zones and returns
    recommendations for where to reposition drivers to reduce wait times.

    IMPORTANT CAVEATS:
    ------------------
    1. Wait times are ESTIMATED using a simplified linear model
    2. Driver positions come from simulation, not real data
    3. Revenue impact is ESTIMATED based on assumed abandonment rates
    4. Distances are Euclidean - actual repositioning takes longer
    5. Recommendations assume drivers will accept repositioning incentives

    Args:
        hour: Hour of day (0-23)
        month: Month (1-12)
        n: Number of recommendations to return (default 5)

    Returns:
        List of RepositioningRecommendation objects, sorted by revenue impact

    Example:
        >>> recs = get_repositioning_recommendations(hour=18, month=12, n=5)
        >>> for rec in recs:
        ...     print(f"{rec.zone_name}: need {rec.drivers_needed} drivers")
    """
    if not 0 <= hour <= 23:
        raise ValueError(f"Hour must be 0-23, got {hour}")
    if not 1 <= month <= 12:
        raise ValueError(f"Month must be 1-12, got {month}")

    undersupplied_zones = []

    # Analyze all zones
    for zone_id, zone_info in ZONE_DATA.items():
        # Get current supply and demand
        supply = get_supply_from_simulator(zone_id, hour)
        demand = get_zone_demand(zone_id, hour, month)

        # Skip very low demand zones
        if demand < 1:
            continue

        # Calculate wait time
        wait_time = estimate_wait_time(demand, supply)

        # Check if undersupplied
        if wait_time > TARGET_WAIT_TIME:
            drivers_needed = calculate_drivers_needed(demand, supply)

            if drivers_needed > 0:
                undersupplied_zones.append({
                    "zone_id": zone_id,
                    "zone_info": zone_info,
                    "wait_time": wait_time,
                    "drivers_needed": drivers_needed,
                    "supply": supply,
                    "demand": demand,
                })

    # Build recommendations
    recommendations = []

    for zone_data in undersupplied_zones:
        zone_id = zone_data["zone_id"]
        zone_info = zone_data["zone_info"]

        # Find nearest oversupplied zone
        source = find_nearest_oversupplied_zone(zone_id, hour, month)

        if source is None:
            # No source zone available - still include recommendation
            # but with no source
            source_zone_id = -1
            source_zone_name = "N/A - No oversupplied zones nearby"
            source_borough = "N/A"
            distance = 0.0
        else:
            source_zone_id, distance, _ = source
            source_info = ZONE_DATA[source_zone_id]
            source_zone_name = source_info["name"]
            source_borough = source_info["borough"]

        # Calculate new wait time if drivers are added
        new_supply = zone_data["supply"] + zone_data["drivers_needed"]
        new_wait_time = estimate_wait_time(zone_data["demand"], new_supply)

        # Calculate revenue impact
        revenue_impact = calculate_revenue_impact(
            zone_data["wait_time"],
            new_wait_time,
            zone_data["demand"]
        )

        # Determine confidence level
        # High: well-known high-demand zone with reliable patterns
        # Medium: typical zone with normal patterns
        # Low: edge cases or low-data zones
        if zone_id in ZONE_DEMAND_MULTIPLIER:
            confidence = "high"
        elif zone_data["demand"] > 10:
            confidence = "medium"
        else:
            confidence = "low"

        rec = RepositioningRecommendation(
            zone_id=zone_id,
            zone_name=zone_info["name"],
            borough=zone_info["borough"],
            estimated_wait_time=zone_data["wait_time"],
            drivers_needed=zone_data["drivers_needed"],
            recommended_source_zone_id=source_zone_id,
            recommended_source_zone_name=source_zone_name,
            source_zone_borough=source_borough,
            distance_km=distance,
            estimated_new_wait_time=new_wait_time,
            revenue_impact=revenue_impact,
            current_supply=zone_data["supply"],
            current_demand=zone_data["demand"],
            confidence=confidence,
        )

        recommendations.append(rec)

    # Sort by revenue impact (highest first)
    recommendations.sort(key=lambda x: x.revenue_impact, reverse=True)

    return recommendations[:n]


def print_recommendations(recommendations: list) -> None:
    """
    Pretty-print recommendations to console.

    Args:
        recommendations: List of RepositioningRecommendation objects
    """
    print("\n" + "=" * 80)
    print("DRIVER REPOSITIONING RECOMMENDATIONS")
    print("=" * 80)
    print("\nNOTE: All values are ESTIMATES based on historical data and simulation.")
    print("    See module docstring for assumptions and limitations.\n")

    for i, rec in enumerate(recommendations, 1):
        print(f"\n{'─' * 80}")
        print(f"#{i} {rec.zone_name} ({rec.borough})")
        print(f"{'─' * 80}")
        print("  Current state:")
        print(f"     • Estimated wait time: {rec.estimated_wait_time:.1f} min (target: {TARGET_WAIT_TIME} min)")
        print(f"     • Current supply: {rec.current_supply} drivers")
        print(f"     • Estimated demand: {rec.current_demand:.1f} trips/hour")
        print(f"     • Confidence: {rec.confidence}")

        print("\n  Recommendation:")
        print(f"     • Drivers needed: {rec.drivers_needed}")
        if rec.recommended_source_zone_id > 0:
            print(f"     • Source zone: {rec.recommended_source_zone_name} ({rec.source_zone_borough})")
            print(f"     • Distance: {rec.distance_km:.1f} km (straight-line)")
        else:
            print("     • Source zone: No oversupplied zones found nearby")

        print("\n  Projected impact:")
        print(f"     • New estimated wait: {rec.estimated_new_wait_time:.1f} min")
        print(f"     • Revenue impact: ${rec.revenue_impact:.2f}/hour (estimated)")

    print(f"\n{'=' * 80}")
    print(f"Total estimated hourly revenue impact: ${sum(r.revenue_impact for r in recommendations):.2f}")
    print("=" * 80 + "\n")


# =============================================================================
# ADDITIONAL UTILITIES
# =============================================================================

def get_zone_status(zone_id: int, hour: int, month: int) -> dict:
    """
    Get detailed status for a specific zone.

    Args:
        zone_id: TLC zone ID
        hour: Hour of day
        month: Month

    Returns:
        Dictionary with zone status details
    """
    if zone_id not in ZONE_DATA:
        return {"error": f"Zone {zone_id} not found"}

    zone_info = ZONE_DATA[zone_id]
    supply = get_supply_from_simulator(zone_id, hour)
    demand = get_zone_demand(zone_id, hour, month)
    wait_time = estimate_wait_time(demand, supply)

    # Determine status
    if wait_time > 10:
        status = "critical_undersupply"
    elif wait_time > TARGET_WAIT_TIME:
        status = "undersupply"
    elif wait_time < 3:
        status = "oversupply"
    else:
        status = "balanced"

    return {
        "zone_id": zone_id,
        "zone_name": zone_info["name"],
        "borough": zone_info["borough"],
        "hour": hour,
        "month": month,
        "current_supply": supply,
        "estimated_demand": round(demand, 1),
        "estimated_wait_time": round(wait_time, 1),
        "target_wait_time": TARGET_WAIT_TIME,
        "status": status,
        "drivers_needed": calculate_drivers_needed(demand, supply) if status in ["undersupply", "critical_undersupply"] else 0,
    }


def get_borough_summary(hour: int, month: int) -> dict:
    """
    Get supply/demand summary by borough.

    Args:
        hour: Hour of day
        month: Month

    Returns:
        Dictionary with borough-level summaries
    """
    summary = {}

    for borough in BOROUGH_DEMAND_SHARE.keys():
        borough_zones = [z for z, info in ZONE_DATA.items() if info["borough"] == borough]

        total_supply = sum(get_supply_from_simulator(z, hour) for z in borough_zones)
        total_demand = sum(get_zone_demand(z, hour, month) for z in borough_zones)

        undersupplied = 0
        oversupplied = 0
        balanced = 0

        for z in borough_zones:
            s = get_supply_from_simulator(z, hour)
            d = get_zone_demand(z, hour, month)
            wait = estimate_wait_time(d, s)

            if wait > TARGET_WAIT_TIME:
                undersupplied += 1
            elif wait < 3:
                oversupplied += 1
            else:
                balanced += 1

        summary[borough] = {
            "total_zones": len(borough_zones),
            "total_supply": total_supply,
            "total_demand": round(total_demand, 1),
            "undersupplied_zones": undersupplied,
            "balanced_zones": balanced,
            "oversupplied_zones": oversupplied,
        }

    return summary


# =============================================================================
# MAIN - DEMO
# =============================================================================

if __name__ == "__main__":
    print("\nRideshare Repositioning Recommendation Engine")
    print("=" * 50)

    # Demo: Get recommendations for 6 PM in December
    hour = 18  # 6 PM - peak hour
    month = 12  # December

    # Check if simulator is available
    sim = _get_simulator()
    if sim:
        print(f"\nUsing driver simulator with {len(sim.drivers)} drivers")
    else:
        print("\n⚠ Driver simulator not available, using demand-based estimates")

    print(f"\nAnalyzing supply/demand for {hour}:00 in month {month}...")

    # Get recommendations
    recs = get_repositioning_recommendations(hour=hour, month=month, n=5)

    # Print recommendations
    print_recommendations(recs)

    # Show borough summary
    print("\nBorough Summary:")
    print("-" * 50)
    summary = get_borough_summary(hour, month)
    for borough, stats in summary.items():
        print(f"\n{borough}:")
        print(f"  Zones: {stats['total_zones']} total")
        print(f"  Supply: {stats['total_supply']} drivers")
        print(f"  Demand: {stats['total_demand']} trips/hr")
        print(f"  Status: {stats['undersupplied_zones']} undersupplied, "
              f"{stats['balanced_zones']} balanced, "
              f"{stats['oversupplied_zones']} oversupplied")
