"""
Facility Map Skill
Displays facilities on a US map with a summary table below
"""
from __future__ import annotations
import os
import json
import pandas as pd
from typing import Optional, List
import logging

from skill_framework import skill, SkillParameter, SkillInput, SkillOutput, SkillVisualization
from skill_framework.layouts import wire_layout
from answer_rocket import AnswerRocketClient

logger = logging.getLogger(__name__)

DATABASE_ID = os.getenv('DATABASE_ID', '3ECBF711-29B5-4C1E-9575-208621747E04')


@skill(
    name="Facility Map",
    description="Display facilities on a US map with location markers. Shows building locations, types, and details.",
    capabilities="Map visualization of facility locations, facility summary table, filtering by state/building use/ownership",
    parameters=[
        SkillParameter(
            name="other_filters",
            constrained_to="filters",
            is_multi=True,
            description="Filters to apply (e.g., state, building_use, own_lease)",
            default_value=[]
        ),
        SkillParameter(
            name="color_by",
            constrained_values=["building_use", "own_lease", "building_type", "state"],
            description="Dimension to color-code markers by",
            default_value="building_use"
        )
    ]
)
def facility_map(parameters: SkillInput):
    """Main skill function for facility map visualization"""

    filters = parameters.arguments.other_filters or []
    color_by = parameters.arguments.color_by or "building_use"

    # Query facility data
    sql_query = """
    SELECT
        BUILDING_NAME,
        BUILDING_TYPE,
        BUILDING_USE,
        CITY,
        STATE,
        FULL_ADDRESS,
        LATITUDE,
        LONGITUDE,
        OWN_LEASE,
        SQUARE_FEET,
        YEAR_BUILT
    FROM facility_map
    WHERE LATITUDE IS NOT NULL AND LONGITUDE IS NOT NULL
    """

    # Add filters
    if filters:
        for filter_item in filters:
            if isinstance(filter_item, dict) and 'dim' in filter_item and 'val' in filter_item:
                dim = filter_item['dim']
                values = filter_item['val']
                if isinstance(values, list):
                    values_str = "', '".join(str(v).upper() for v in values)
                    sql_query += f" AND UPPER({dim}) IN ('{values_str}')"

    try:
        client = AnswerRocketClient()
        result = client.data.execute_sql_query(DATABASE_ID, sql_query, row_limit=1000)

        if not result.success or not hasattr(result, 'df'):
            error_msg = result.error if hasattr(result, 'error') else 'Unknown error'
            raise Exception(f"Query failed: {error_msg}")

        df = result.df
        print(f"DEBUG: Retrieved {len(df)} facilities")

    except Exception as e:
        print(f"DEBUG: Query failed: {e}")
        return SkillOutput(
            final_prompt="Failed to retrieve facility data.",
            narrative="Error loading facility data.",
            visualizations=[]
        )

    if len(df) == 0:
        return SkillOutput(
            final_prompt="No facilities found matching the criteria.",
            narrative="No facility data available.",
            visualizations=[]
        )

    # Define color mapping based on color_by dimension
    color_maps = {
        "building_use": {
            "AMBULATORY": "#3b82f6",
            "ADMIN": "#10b981",
            "ACUTE": "#ef4444",
            "default": "#6b7280"
        },
        "own_lease": {
            "OWN": "#3b82f6",
            "LEASE": "#f59e0b",
            "OWN - CONDO": "#10b981",
            "default": "#6b7280"
        },
        "building_type": {
            "MULTI STORY": "#3b82f6",
            "SINGLE STORY": "#10b981",
            "default": "#6b7280"
        },
        "state": {
            "MA": "#3b82f6",
            "NH": "#10b981",
            "default": "#6b7280"
        }
    }

    colors = color_maps.get(color_by, color_maps["building_use"])

    # Build map points data
    map_points = []
    for _, row in df.iterrows():
        color_value = str(row.get(color_by.upper(), '')).upper()
        marker_color = colors.get(color_value, colors.get("default", "#6b7280"))

        map_points.append({
            "name": row.get('BUILDING_NAME', 'Unknown'),
            "lat": float(row['LATITUDE']),
            "lon": float(row['LONGITUDE']),
            "color": marker_color,
            "building_use": row.get('BUILDING_USE', ''),
            "building_type": row.get('BUILDING_TYPE', ''),
            "city": row.get('CITY', ''),
            "state": row.get('STATE', ''),
            "address": row.get('FULL_ADDRESS', ''),
            "own_lease": row.get('OWN_LEASE', ''),
            "square_feet": row.get('SQUARE_FEET', 0)
        })

    # Build legend items
    legend_items = []
    for key, color in colors.items():
        if key != "default":
            legend_items.append(f'<span style="display:inline-block;width:12px;height:12px;background:{color};border-radius:50%;margin-right:6px;"></span>{key}')
    legend_html = ' &nbsp;&nbsp; '.join(legend_items)

    # Group facilities by color (building_use) for separate series
    series_by_color = {}
    for point in map_points:
        color = point['color']
        use = point['building_use']
        if use not in series_by_color:
            series_by_color[use] = {
                'name': use,
                'color': color,
                'data': []
            }
        series_by_color[use]['data'].append({
            'x': point['lon'],
            'y': point['lat'],
            'z': 10,
            'name': point['name'],
            'city': point['city'],
            'state': point['state'],
            'building_type': point['building_type'],
            'building_use': point['building_use'],
            'own_lease': point['own_lease'],
            'square_feet': point['square_feet']
        })

    bubble_series = list(series_by_color.values())

    # Calculate bounds for axis
    all_lons = [p['lon'] for p in map_points]
    all_lats = [p['lat'] for p in map_points]
    lon_min, lon_max = min(all_lons) - 0.1, max(all_lons) + 0.1
    lat_min, lat_max = min(all_lats) - 0.05, max(all_lats) + 0.05

    # Build mappoint series for Highcharts Maps
    map_series_data = []
    for use, series_data in series_by_color.items():
        map_series_data.append({
            "type": "mappoint",
            "name": use,
            "color": series_data['color'],
            "data": [{
                "name": p['name'],
                "lat": p['y'],
                "lon": p['x'],
                "city": p.get('city', ''),
                "state": p.get('state', ''),
                "building_type": p.get('building_type', ''),
                "building_use": p.get('building_use', ''),
                "own_lease": p.get('own_lease', ''),
                "square_feet": p.get('square_feet', 0)
            } for p in series_data['data']],
            "marker": {
                "radius": 8,
                "lineWidth": 2,
                "lineColor": "#ffffff"
            }
        })

    # Highcharts Maps configuration
    map_config = {
        "chart": {
            "type": "map",
            "map": "countries/us/us-all"
        },
        "title": {
            "text": ""
        },
        "mapNavigation": {
            "enabled": True,
            "enableMouseWheelZoom": True,
            "enableDoubleClickZoom": True,
            "buttonOptions": {
                "verticalAlign": "bottom"
            }
        },
        "drilldown": {
            "activeDataLabelStyle": {
                "color": "#FFFFFF",
                "textDecoration": "none",
                "textOutline": "1px #000000"
            },
            "drillUpButton": {
                "relativeTo": "spacingBox",
                "position": {
                    "x": 0,
                    "y": 60
                }
            }
        },
        "tooltip": {
            "useHTML": True,
            "headerFormat": "",
            "pointFormat": "<b>{point.name}</b><br/>{point.city}, {point.state}<br/>Type: {point.building_type}<br/>Use: {point.building_use}<br/>Ownership: {point.own_lease}<br/>Sq Ft: {point.square_feet:,.0f}"
        },
        "legend": {
            "enabled": True,
            "align": "right",
            "verticalAlign": "top",
            "layout": "vertical"
        },
        "credits": {
            "enabled": False
        },
        "series": [{
            "name": "US States",
            "borderColor": "#A0A0A0",
            "nullColor": "rgba(200, 200, 200, 0.3)",
            "showInLegend": False
        }] + map_series_data
    }

    print(f"DEBUG: Map config chart type: {map_config.get('chart', {})}")
    print(f"DEBUG: Number of series: {len(map_config['series'])}")
    print(f"DEBUG: First series: {map_config['series'][0]}")
    if len(map_config['series']) > 1:
        print(f"DEBUG: Second series type: {map_config['series'][1].get('type', 'no type')}")
        print(f"DEBUG: Second series data count: {len(map_config['series'][1].get('data', []))}")
    print(f"DEBUG: Full map_config JSON: {json.dumps(map_config, indent=2)[:2000]}...")

    # Build summary table
    table_rows = []
    for _, row in df.iterrows():
        sq_ft = row.get('SQUARE_FEET', 0)
        sq_ft_str = f"{sq_ft:,.0f}" if pd.notna(sq_ft) else "N/A"
        table_rows.append({
            "name": row.get('BUILDING_NAME', ''),
            "city": row.get('CITY', ''),
            "state": row.get('STATE', ''),
            "type": row.get('BUILDING_TYPE', ''),
            "use": row.get('BUILDING_USE', ''),
            "ownership": row.get('OWN_LEASE', ''),
            "sq_ft": sq_ft_str
        })

    # Create layout with map and table
    layout = {
        "layoutJson": {
            "type": "Document",
            "style": {"padding": "20px", "fontFamily": "system-ui, -apple-system, sans-serif"},
            "children": [
                {
                    "name": "Header",
                    "type": "Paragraph",
                    "text": f"Facility Locations ({len(df)} facilities)",
                    "style": {"fontSize": "24px", "fontWeight": "bold", "marginBottom": "10px", "color": "#1e293b"}
                },
                {
                    "name": "Legend",
                    "type": "Paragraph",
                    "text": f"Color by {color_by.replace('_', ' ').title()}: {legend_html}",
                    "style": {"fontSize": "14px", "marginBottom": "20px", "color": "#64748b"}
                },
                {
                    "name": "FacilityMapChart",
                    "type": "HighchartsChart",
                    "children": "",
                    "minHeight": "450px",
                    "options": map_config,
                    "extraStyles": "border-radius: 8px; margin-bottom: 20px;"
                },
                {
                    "name": "TableHeader",
                    "type": "Paragraph",
                    "text": "Facility Details",
                    "style": {"fontSize": "18px", "fontWeight": "bold", "marginBottom": "15px", "color": "#1e293b"}
                },
                {
                    "name": "FacilityTable",
                    "type": "FlexContainer",
                    "children": "",
                    "direction": "column",
                    "extraStyles": "display: grid; grid-template-columns: 2fr 1fr 0.5fr 1fr 1fr 1fr 1fr; gap: 0; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden;"
                },
                {
                    "name": "TH_Name",
                    "type": "Paragraph",
                    "children": "",
                    "text": "Building Name",
                    "parentId": "FacilityTable",
                    "style": {"padding": "12px", "fontWeight": "bold", "backgroundColor": "#f8fafc", "borderBottom": "2px solid #e2e8f0"}
                },
                {
                    "name": "TH_City",
                    "type": "Paragraph",
                    "children": "",
                    "text": "City",
                    "parentId": "FacilityTable",
                    "style": {"padding": "12px", "fontWeight": "bold", "backgroundColor": "#f8fafc", "borderBottom": "2px solid #e2e8f0"}
                },
                {
                    "name": "TH_State",
                    "type": "Paragraph",
                    "children": "",
                    "text": "State",
                    "parentId": "FacilityTable",
                    "style": {"padding": "12px", "fontWeight": "bold", "backgroundColor": "#f8fafc", "borderBottom": "2px solid #e2e8f0"}
                },
                {
                    "name": "TH_Type",
                    "type": "Paragraph",
                    "children": "",
                    "text": "Type",
                    "parentId": "FacilityTable",
                    "style": {"padding": "12px", "fontWeight": "bold", "backgroundColor": "#f8fafc", "borderBottom": "2px solid #e2e8f0"}
                },
                {
                    "name": "TH_Use",
                    "type": "Paragraph",
                    "children": "",
                    "text": "Use",
                    "parentId": "FacilityTable",
                    "style": {"padding": "12px", "fontWeight": "bold", "backgroundColor": "#f8fafc", "borderBottom": "2px solid #e2e8f0"}
                },
                {
                    "name": "TH_Ownership",
                    "type": "Paragraph",
                    "children": "",
                    "text": "Ownership",
                    "parentId": "FacilityTable",
                    "style": {"padding": "12px", "fontWeight": "bold", "backgroundColor": "#f8fafc", "borderBottom": "2px solid #e2e8f0"}
                },
                {
                    "name": "TH_SqFt",
                    "type": "Paragraph",
                    "children": "",
                    "text": "Sq Ft",
                    "parentId": "FacilityTable",
                    "style": {"padding": "12px", "fontWeight": "bold", "backgroundColor": "#f8fafc", "borderBottom": "2px solid #e2e8f0", "textAlign": "right"}
                }
            ]
        },
        "inputVariables": []
    }

    # Add table rows dynamically
    for i, row in enumerate(table_rows):
        bg_color = "#ffffff" if i % 2 == 0 else "#f8fafc"
        border_style = "1px solid #e2e8f0"
        layout["layoutJson"]["children"].extend([
            {"name": f"TD_Name_{i}", "type": "Paragraph", "children": "", "text": row["name"], "parentId": "FacilityTable", "style": {"padding": "10px 12px", "backgroundColor": bg_color, "borderBottom": border_style, "fontSize": "14px"}},
            {"name": f"TD_City_{i}", "type": "Paragraph", "children": "", "text": row["city"], "parentId": "FacilityTable", "style": {"padding": "10px 12px", "backgroundColor": bg_color, "borderBottom": border_style, "fontSize": "14px"}},
            {"name": f"TD_State_{i}", "type": "Paragraph", "children": "", "text": row["state"], "parentId": "FacilityTable", "style": {"padding": "10px 12px", "backgroundColor": bg_color, "borderBottom": border_style, "fontSize": "14px"}},
            {"name": f"TD_Type_{i}", "type": "Paragraph", "children": "", "text": row["type"], "parentId": "FacilityTable", "style": {"padding": "10px 12px", "backgroundColor": bg_color, "borderBottom": border_style, "fontSize": "14px"}},
            {"name": f"TD_Use_{i}", "type": "Paragraph", "children": "", "text": row["use"], "parentId": "FacilityTable", "style": {"padding": "10px 12px", "backgroundColor": bg_color, "borderBottom": border_style, "fontSize": "14px"}},
            {"name": f"TD_Ownership_{i}", "type": "Paragraph", "children": "", "text": row["ownership"], "parentId": "FacilityTable", "style": {"padding": "10px 12px", "backgroundColor": bg_color, "borderBottom": border_style, "fontSize": "14px"}},
            {"name": f"TD_SqFt_{i}", "type": "Paragraph", "children": "", "text": row["sq_ft"], "parentId": "FacilityTable", "style": {"padding": "10px 12px", "backgroundColor": bg_color, "borderBottom": border_style, "fontSize": "14px", "textAlign": "right"}}
        ])

    # Render layout
    print(f"DEBUG: Layout has {len(layout['layoutJson']['children'])} children")
    print(f"DEBUG: Map points count: {len(map_points)}")
    print(f"DEBUG: Bubble series count: {len(bubble_series)}")
    try:
        html = wire_layout(layout, {})
        print(f"DEBUG: wire_layout succeeded, HTML length: {len(html)}")
    except Exception as e:
        print(f"DEBUG: wire_layout failed: {e}")
        import traceback
        traceback.print_exc()
        html = f"<div>Error rendering layout: {e}</div>"

    # Summary for chat response
    summary = f"Showing {len(df)} facilities on the map. "
    if 'BUILDING_USE' in df.columns:
        use_counts = df['BUILDING_USE'].value_counts().to_dict()
        use_summary = ", ".join([f"{count} {use}" for use, count in use_counts.items()])
        summary += f"By use: {use_summary}."

    return SkillOutput(
        final_prompt=summary,
        narrative=None,
        visualizations=[
            SkillVisualization(title="Facility Map", layout=html)
        ]
    )
