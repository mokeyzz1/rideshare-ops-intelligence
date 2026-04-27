# Project Summary: RideFlow Ops

## The Problem

NYC rideshare demand is not centered only in Manhattan, but wait times are still shortest there. Brooklyn accounts for 27% of pickups but riders wait longer. This suggests supply is better aligned to Manhattan than to high-demand outer-borough zones.

---

## Part 1: Data Analysis (Notebook)

### Dataset
- **Source:** NYC TLC For-Hire Vehicle High Volume trip records
- **Size:** 62.4 million trips
- **Period:** January, June, December 2025
- **Files:** ~1.5GB of parquet data

### Key Findings

#### 1. Borough Distribution
| Borough | Pickup Share | Median Wait |
|---------|--------------|-------------|
| Manhattan | 36.5% | 3.0 min |
| Brooklyn | 27.2% | 3.4 min |
| Queens | 21.8% | 3.6 min |
| Bronx | 12.9% | 4.2 min |
| Staten Island | 1.6% | 4.6 min |

#### 2. NYE Surge Patterns
New Year's Eve demand peaks 8-10 PM in **residential neighborhoods**, not Manhattan:

| Zone | NYE vs Normal |
|------|---------------|
| Stuyvesant Heights | +209% |
| Bushwick South | +183% |
| Bedford | +150% |
| Crown Heights North | +141% |

#### 3. Supply Gap Zones
High volume + above-average wait times:
- LaGuardia Airport: 1.2M trips, 5.8 min avg wait
- JFK Airport: 1.0M trips, 5.8 min avg wait
- Crown Heights North, East New York, Bushwick South

#### 4. Time Patterns
- Peak demand: 6-9 PM (multiplier: 1.45-1.50)
- Lowest demand: 4-5 AM (multiplier: 0.32-0.35)
- Overnight (4 AM): Highest wait times even with low demand

---

## Part 2: Dashboard Development

### What We Built
A real-time operations dashboard that visualizes supply-demand imbalances and provides repositioning recommendations.

### Components

#### 1. KPI Cards
- Active Drivers (~750-800 at peak)
- Rides in Progress (~230 at peak)
- Zones Undersupplied (~18-22 at peak)
- Revenue at Risk (~$1,100-1,500/hr at peak)

#### 2. Live Supply-Demand Map
- 39 NYC zones across all boroughs
- Color-coded: Critical (red), Low Supply (amber), Balanced (green), Oversupply (blue)
- Wait time displayed in each zone marker
- Driver positions as green dots

#### 3. Action Queue
- Prioritized recommendations (URGENT/HIGH/MED)
- Target zone and source zone
- Drivers needed and revenue impact
- Sorted by revenue at risk

#### 4. Charts
- Demand vs Supply (24-hour)
- Average Wait Time by Zone (top 8 worst)
- Revenue at Risk Over Time

#### 5. Playback Mode
- Simulate through 24 hours
- Watch supply-demand changes by hour
- 4-second intervals

---

## Part 3: Technical Implementation

### Data Pipeline
```
TLC Parquet Files (62M trips, 1.5GB)
    ↓
preprocess_demand.py
    ↓
demand_patterns.json (34KB)
    ↓
Dashboard (real-time)
```

### Driver Simulation
1,500 simulated drivers with 5 behavioral types:

| Type | % | Behavior |
|------|---|----------|
| Normal | 83% | Accept rides proportional to demand |
| Surge Gamer | 8% | Cluster in high-demand zones, 40% lower acceptance |
| Cherry Picker | 4% | Only accept trips > 3 miles |
| Ghost | 3% | Show available but 5% acceptance |
| Efficient | 2% | Follow demand signals, 95% acceptance |

### Recommendation Engine
Calculates repositioning recommendations by:
1. Getting real demand from TLC data
2. Getting supply from simulated driver positions
3. Calculating wait time: `base_wait × (demand / capacity)`
4. Finding oversupplied source zones nearby
5. Computing revenue impact from reduced abandonment

### Tech Stack
- **Dash** - Web framework
- **Plotly** - Interactive charts and maps
- **Pandas/NumPy** - Data processing
- **PyArrow** - Parquet file reading
- **Gunicorn** - Production server

---

## Part 4: Deployment

### Platform: Render
- Free tier with auto-sleep
- Auto-deploy from GitHub
- ~30 sec cold start

### Live URL
https://rideshare-ops-intelligence.onrender.com

### GitHub
https://github.com/mokeyzz1/rideshare-ops-intelligence

---

## Project Structure

```
├── README.md
├── PROJECT_SUMMARY.md
├── requirements.txt
├── render.yaml
├── app.py                    # Dashboard
├── driver_simulator.py       # 1,500 driver simulation
├── recommendations.py        # Repositioning engine
├── preprocess_demand.py      # TLC data preprocessing
├── notebooks/
│   └── analysis.ipynb        # Exploratory analysis
├── data/
│   └── demand_patterns.json  # Preprocessed demand
└── assets/
    ├── style.css
    └── screenshot.png
```

---

## What Makes This Portfolio-Worthy

1. **Real data** - 62M trips, not sample/fake data
2. **End-to-end** - Analysis → Preprocessing → Simulation → Visualization
3. **Original findings** - NYE surge in Brooklyn residential, not Manhattan
4. **Production-ready** - Deployed, not just a notebook
5. **Clean UI** - Dark theme, custom styling, not default Dash look
