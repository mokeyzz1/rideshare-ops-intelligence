from datetime import datetime

import dash
from dash import dcc, html, callback, Input, Output, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
import numpy as np

from driver_simulator import DriverSimulator
from recommendations import (
    get_repositioning_recommendations,
    get_zone_status,
    set_simulator,
    ZONE_DATA,
)

# Use current month instead of hardcoded value
CURRENT_MONTH = datetime.now().month

simulator = DriverSimulator()
simulator.initialize_drivers(n=1500)
set_simulator(simulator)

NYC_CENTER = {"lat": 40.7128, "lon": -73.9060}

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.SLATE], title="RideFlow Ops")
server = app.server

C = {
    "bg": "#0b1118",
    "panel": "#111923",
    "text": "#e6edf3",
    "muted": "#8b949e",
    "green": "#2ecc71",
    "red": "#ff4d4f",
    "amber": "#ff9f1c",
    "blue": "#2d9cdb",
}


def get_driver_positions(hour):
    current_time = datetime.now().replace(hour=hour, minute=0)
    rows = []

    for driver in simulator.drivers.values():
        if driver.current_zone_id not in ZONE_DATA:
            continue

        zone = ZONE_DATA[driver.current_zone_id]
        on_shift = driver.is_on_shift(current_time)

        rows.append({
            "lat": zone["lat"] + np.random.uniform(-0.003, 0.003),
            "lon": zone["lon"] + np.random.uniform(-0.003, 0.003),
            "status": "available" if on_shift else "offline",
        })

    return pd.DataFrame(rows)


def get_zone_metrics(hour):
    rows = []

    for zone_id, zone in ZONE_DATA.items():
        status = get_zone_status(zone_id, hour, CURRENT_MONTH)

        rows.append({
            "zone_name": zone["name"],
            "borough": zone["borough"],
            "lat": zone["lat"],
            "lon": zone["lon"],
            "supply": status["current_supply"],
            "demand": status["estimated_demand"],
            "wait_time": status["estimated_wait_time"],
            "status": status["status"],
        })

    return pd.DataFrame(rows)


def get_metrics(hour):
    current_time = datetime.now().replace(hour=hour, minute=0)

    active = sum(1 for d in simulator.drivers.values() if d.is_on_shift(current_time))
    zones_df = get_zone_metrics(hour)

    undersupplied = len(
        zones_df[zones_df["status"].isin(["undersupply", "critical_undersupply"])]
    )

    recs = get_repositioning_recommendations(hour, CURRENT_MONTH, n=10)
    revenue_risk = sum(r.revenue_impact for r in recs)

    return {
        "active": active,
        "rides": int(active * 0.3),
        "undersupplied": undersupplied,
        "revenue_risk": revenue_risk,
    }


def kpi(title, value_id, sub, color):
    return html.Div([
        html.Div(title, className="kpi-title"),
        html.Div(id=value_id, className="kpi-value", style={"color": color}),
        html.Div(sub, className="kpi-sub"),
    ], className="panel kpi")


app.layout = html.Div([

    dcc.Interval(id="tick", interval=5000, n_intervals=0),
    dcc.Interval(id="playback-tick", interval=4000, n_intervals=0, disabled=True),
    dcc.Store(id="playback-state", data={"playing": False, "hour": datetime.now().hour}),

    html.Div([

        html.Div([
            html.Div("RideFlow Ops", className="brand"),
            html.Div("Live Operations Dashboard", className="subtitle"),
        ], className="brand-row"),

        html.Div([
            html.Button("▶", id="play-btn", className="play-btn"),
            html.Div(id="playback-label", className="playback-label"),
        ], className="playback-control"),

        html.Div([
            html.Div(id="time-display", className="time-box"),
            html.Small(id="last-updated"),
        ], className="time-right"),

    ], className="header"),

    html.Div([
        kpi("Active Drivers", "m-active", "on shift", C["green"]),
        kpi("Rides in Progress", "m-rides", "estimated active rides", C["blue"]),
        kpi("Zones Undersupplied", "m-zones", "need more drivers", C["red"]),
        kpi("Revenue at Risk", "m-revenue", "estimated per hour", C["amber"]),
    ], className="kpi-grid"),

    html.Div([

        html.Div([
            html.Div([
                html.Div("Live Supply-Demand Map", className="panel-title"),
                html.Div([
                    html.Span([html.Span(className="dot", style={"background": C["red"]}), "Critical"]),
                    html.Span([html.Span(className="dot", style={"background": C["amber"]}), "Low Supply"]),
                    html.Span([html.Span(className="dot", style={"background": C["green"]}), "Balanced"]),
                    html.Span([html.Span(className="dot", style={"background": C["blue"]}), "Oversupply"]),
                ], className="legend"),
            ], className="panel-header"),
            dcc.Graph(id="map", className="map-graph", config={"displayModeBar": False}),
        ], className="panel"),

        html.Div([
            html.Div([
                html.Div("Action Queue", className="panel-title"),
            ], className="panel-header"),
            html.Div(id="action-table", className="action-wrap"),
        ], className="panel"),

    ], className="main-grid"),

    html.Div([

        html.Div([
            html.Div([html.Div("Demand vs Supply", className="panel-title")], className="panel-header"),
            dcc.Graph(id="demand-supply-chart", className="chart-graph", config={"displayModeBar": False}),
        ], className="panel"),

        html.Div([
            html.Div([html.Div("Average Wait Time by Zone", className="panel-title")], className="panel-header"),
            dcc.Graph(id="wait-time-chart", className="chart-graph", config={"displayModeBar": False}),
        ], className="panel"),

        html.Div([
            html.Div([html.Div("Revenue at Risk Over Time", className="panel-title")], className="panel-header"),
            dcc.Graph(id="revenue-chart", className="chart-graph", config={"displayModeBar": False}),
        ], className="panel"),

    ], className="chart-grid"),

], className="app")


@callback(
    Output("time-display", "children"),
    Input("tick", "n_intervals"),
    Input("playback-state", "data"),
)
def update_time(_, state):
    if state.get("playing"):
        hour = state.get("hour", 0)
        h = hour % 12 or 12
        return f"{h}:00 {'AM' if hour < 12 else 'PM'}"
    else:
        now = datetime.now()
        h = now.hour % 12 or 12
        return f"{h}:{now.minute:02d} {'AM' if now.hour < 12 else 'PM'}"


@callback(
    Output("playback-state", "data"),
    Output("playback-tick", "disabled"),
    Output("play-btn", "children"),
    Output("playback-label", "children"),
    Input("play-btn", "n_clicks"),
    State("playback-state", "data"),
    prevent_initial_call=True,
)
def toggle_playback(n_clicks, state):
    playing = not state.get("playing", False)
    hour = state.get("hour", datetime.now().hour)
    return (
        {"playing": playing, "hour": hour},
        not playing,
        "⏹" if playing else "▶",
        "SIMULATING" if playing else "LIVE",
    )


@callback(
    Output("playback-state", "data", allow_duplicate=True),
    Input("playback-tick", "n_intervals"),
    State("playback-state", "data"),
    prevent_initial_call=True,
)
def advance_playback(_, state):
    if not state.get("playing"):
        return state
    hour = (state.get("hour", 0) + 1) % 24
    return {"playing": True, "hour": hour}


def get_month_str(month):
    """Convert month number to string for simulator."""
    if month in [12, 1, 2]:
        return "dec"
    elif month in [6, 7, 8]:
        return "jun"
    return "jan"


def get_current_hour(state):
    """Get hour from playback state or real time."""
    if state and state.get("playing"):
        return state.get("hour", datetime.now().hour)
    return datetime.now().hour


@callback(
    Output("m-active", "children"),
    Output("m-rides", "children"),
    Output("m-zones", "children"),
    Output("m-revenue", "children"),
    Output("last-updated", "children"),
    Input("tick", "n_intervals"),
    Input("playback-state", "data"),
)
def update_metrics(_, state):
    hour = get_current_hour(state)

    # Run simulation every tick - drivers move between zones
    simulator.simulate_hour(hour, get_month_str(CURRENT_MONTH))

    m = get_metrics(hour)
    now = datetime.now().strftime("%I:%M:%S %p").lstrip("0")

    return (
        f"{m['active']:,}",
        f"{m['rides']:,}",
        str(m["undersupplied"]),
        f"${m['revenue_risk']:,.0f}/hr",
        f"Last updated: {now}",
    )


@callback(Output("map", "figure"), Input("tick", "n_intervals"), Input("playback-state", "data"))
def update_map(_, state):
    hour = get_current_hour(state)
    drivers = get_driver_positions(hour)
    zones = get_zone_metrics(hour)

    colors = {
        "critical_undersupply": C["red"],
        "undersupply": C["amber"],
        "balanced": C["green"],
        "oversupply": C["blue"],
        "excess_supply": C["blue"],
    }

    fig = go.Figure()

    for _, z in zones.iterrows():
        fig.add_trace(go.Scattermapbox(
            lat=[z["lat"]],
            lon=[z["lon"]],
            mode="markers+text",
            text=[f"{int(z['wait_time'])}"],
            textfont=dict(color="white", size=10),
            marker=dict(
                size=26 if z["status"] == "critical_undersupply" else 22,
                color=colors.get(z["status"], C["muted"]),
                opacity=0.9,
            ),
            hovertemplate=(
                f"<b>{z['zone_name']}</b><br>"
                f"{z['borough']}<br>"
                f"Demand: {z['demand']:.0f}<br>"
                f"Supply: {z['supply']:.0f}<br>"
                f"Wait: {z['wait_time']:.1f} min"
                "<extra></extra>"
            ),
            showlegend=False,
        ))

    active = drivers[drivers["status"] == "available"]

    if len(active) > 250:
        active = active.sample(250)

    fig.add_trace(go.Scattermapbox(
        lat=active["lat"],
        lon=active["lon"],
        mode="markers",
        marker=dict(size=4, color=C["green"], opacity=0.55),
        hoverinfo="skip",
        showlegend=False,
    ))

    fig.update_layout(
        mapbox=dict(
            style="carto-darkmatter",
            center=dict(lat=NYC_CENTER["lat"], lon=NYC_CENTER["lon"]),
            zoom=10.15,
        ),
        margin=dict(l=10, r=10, t=0, b=10),
        paper_bgcolor=C["panel"],
        plot_bgcolor=C["panel"],
    )

    return fig


@callback(Output("action-table", "children"), Input("tick", "n_intervals"), Input("playback-state", "data"))
def update_action_table(_, state):
    hour = get_current_hour(state)
    recs = get_repositioning_recommendations(hour, CURRENT_MONTH, n=8)

    rows = []

    for r in recs:
        # Priority based on wait time
        if r.estimated_wait_time >= 10:
            priority = "URGENT"
            priority_color = C["red"]
        elif r.estimated_wait_time >= 6:
            priority = "HIGH"
            priority_color = C["amber"]
        else:
            priority = "MED"
            priority_color = C["muted"]

        # Source zone (where to pull drivers from) - truncate long names
        if r.recommended_source_zone_id > 0:
            source = r.recommended_source_zone_name[:18] + "…" if len(r.recommended_source_zone_name) > 18 else r.recommended_source_zone_name
        else:
            source = "—"

        rows.append(html.Tr([
            html.Td(html.Span(priority, className="priority-badge", style={"background": priority_color})),
            html.Td(r.zone_name, className="zone-cell"),
            html.Td(source, style={"color": C["muted"]}),
            html.Td(f"+{r.drivers_needed}", style={"color": C["red"], "fontWeight": "800"}),
            html.Td(f"${r.revenue_impact:,.0f}", style={"color": C["amber"], "fontWeight": "800"}),
        ]))

    return html.Table([
        html.Thead(html.Tr([
            html.Th(""),
            html.Th("Zone"),
            html.Th("From"),
            html.Th("Need"),
            html.Th("Risk/hr"),
        ])),
        html.Tbody(rows),
    ], className="action-table")


def chart_layout(fig):
    fig.update_layout(
        paper_bgcolor=C["panel"],
        plot_bgcolor=C["panel"],
        font=dict(color=C["muted"], size=10),
        margin=dict(l=42, r=20, t=10, b=35),
        xaxis=dict(gridcolor="rgba(255,255,255,.08)", zeroline=False),
        yaxis=dict(gridcolor="rgba(255,255,255,.08)", zeroline=False),
        legend=dict(orientation="h", y=1.2, x=0),
    )
    return fig


@callback(Output("demand-supply-chart", "figure"), Input("tick", "n_intervals"), Input("playback-state", "data"))
def update_demand_supply(_, state):
    hour = get_current_hour(state)
    rows = []

    for h in range(24):
        zones = get_zone_metrics(h)
        rows.append({
            "hour": h,
            "demand": zones["demand"].sum(),
            "supply": zones["supply"].sum(),
        })

    df = pd.DataFrame(rows)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["hour"], y=df["demand"], mode="lines", name="Demand", line=dict(color=C["red"], width=2)))
    fig.add_trace(go.Scatter(x=df["hour"], y=df["supply"], mode="lines", name="Supply", line=dict(color=C["green"], width=2)))
    fig.add_vline(x=hour, line_dash="dash", line_color=C["muted"])

    return chart_layout(fig)


@callback(Output("wait-time-chart", "figure"), Input("tick", "n_intervals"), Input("playback-state", "data"))
def update_wait_time(_, state):
    hour = get_current_hour(state)
    zones = get_zone_metrics(hour).sort_values("wait_time", ascending=False).head(8)

    colors = [
        C["red"] if w >= 8 else C["amber"] if w >= 5 else C["green"]
        for w in zones["wait_time"]
    ]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=zones["zone_name"],
        y=zones["wait_time"],
        marker_color=colors,
        hovertemplate="<b>%{x}</b><br>Wait: %{y:.1f} min<extra></extra>",
    ))

    return chart_layout(fig)


@callback(Output("revenue-chart", "figure"), Input("tick", "n_intervals"), Input("playback-state", "data"))
def update_revenue_chart(_, state):
    hour = get_current_hour(state)
    rows = []

    for h in range(24):
        recs = get_repositioning_recommendations(h, CURRENT_MONTH, n=10)
        rows.append({
            "hour": h,
            "revenue": sum(r.revenue_impact for r in recs),
        })

    df = pd.DataFrame(rows)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["hour"],
        y=df["revenue"],
        mode="lines",
        name="Revenue Risk",
        line=dict(color=C["amber"], width=2),
        fill="tozeroy",
        fillcolor="rgba(255,159,28,.15)",
    ))

    fig.add_vline(x=hour, line_dash="dash", line_color=C["muted"])

    return chart_layout(fig)


if __name__ == "__main__":
    print("\nRideFlow Ops: http://localhost:8050\n")
    app.run(debug=True, host="0.0.0.0", port=8050)