import logging
from pathlib import Path
from datetime import datetime

import config

log = logging.getLogger(__name__)


def generate_chart(chart_data: dict) -> str | None:
    """Generate a Twitter-optimized chart image from chart_data.

    Charts are ALWAYS generated — this is mandatory for every post.

    Args:
        chart_data: dict with keys: chart_type, chart_title, data_points

    Returns:
        Path to the generated PNG image, or None if generation fails.
    """
    data_points = chart_data.get("data_points", [])
    if not data_points or len(data_points) < 2:
        log.warning("Not enough data points for chart — generating placeholder")
        return _generate_placeholder_chart(chart_data.get("chart_title", "Market Overview"))

    try:
        import plotly.graph_objects as go

        labels = [dp["label"] for dp in data_points]
        values = [dp["value"] for dp in data_points]
        chart_type = chart_data.get("chart_type", "bar")
        title = chart_data.get("chart_title", "")

        # Color palette — modern, dark theme friendly
        colors = [
            "#6366f1", "#8b5cf6", "#a78bfa", "#c4b5fd",
            "#818cf8", "#7c3aed", "#5b21b6", "#4f46e5",
            "#ec4899", "#f59e0b", "#10b981", "#06b6d4",
        ]

        fig = go.Figure()

        if chart_type in ("bar", "comparison"):
            fig.add_trace(go.Bar(
                x=labels,
                y=values,
                marker_color=colors[:len(labels)],
                text=[_format_value(v) for v in values],
                textposition="outside",
                textfont=dict(size=14, color="white"),
            ))
        elif chart_type == "line":
            fig.add_trace(go.Scatter(
                x=labels,
                y=values,
                mode="lines+markers+text",
                line=dict(color="#6366f1", width=3),
                marker=dict(size=10, color="#8b5cf6"),
                text=[_format_value(v) for v in values],
                textposition="top center",
                textfont=dict(size=12, color="white"),
                fill="tozeroy",
                fillcolor="rgba(99,102,241,0.1)",
            ))
        else:
            # Default to bar
            fig.add_trace(go.Bar(
                x=labels,
                y=values,
                marker_color=colors[:len(labels)],
                text=[_format_value(v) for v in values],
                textposition="outside",
                textfont=dict(size=14, color="white"),
            ))

        # Dark theme styling — Twitter optimized
        fig.update_layout(
            title=dict(
                text=title,
                font=dict(size=22, color="white", family="Arial Black"),
                x=0.5,
                xanchor="center",
            ),
            template="plotly_dark",
            paper_bgcolor="#0f0f0f",
            plot_bgcolor="#0f0f0f",
            font=dict(color="#e0e0e0", size=13),
            width=1200,
            height=675,
            margin=dict(l=60, r=60, t=80, b=60),
            xaxis=dict(
                tickfont=dict(size=12),
                gridcolor="#1a1a2e",
            ),
            yaxis=dict(
                tickfont=dict(size=12),
                gridcolor="#1a1a2e",
            ),
            showlegend=False,
        )

        # Add subtle watermark
        fig.add_annotation(
            text="TweetAgent",
            xref="paper", yref="paper",
            x=0.98, y=0.02,
            showarrow=False,
            font=dict(size=10, color="#333"),
            opacity=0.5,
        )

        # Save to charts directory
        chart_path = config.CHARTS_DIR / f"chart_{_timestamp()}.png"
        fig.write_image(str(chart_path), scale=2)

        log.info(f"Chart generated: {chart_path}")
        return str(chart_path)

    except Exception as e:
        log.error(f"Chart generation failed: {e}")
        return _generate_placeholder_chart(chart_data.get("chart_title", ""))


def _generate_placeholder_chart(title: str = "Data Visualization") -> str | None:
    """Generate a simple placeholder chart when data points are insufficient."""
    try:
        import plotly.graph_objects as go

        fig = go.Figure()
        fig.add_annotation(
            text=title or "Chart Coming Soon",
            xref="paper", yref="paper",
            x=0.5, y=0.5,
            showarrow=False,
            font=dict(size=28, color="white", family="Arial Black"),
        )
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#0f0f0f",
            plot_bgcolor="#0f0f0f",
            width=1200,
            height=675,
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
        )
        fig.add_annotation(
            text="TweetAgent",
            xref="paper", yref="paper",
            x=0.98, y=0.02,
            showarrow=False,
            font=dict(size=10, color="#333"),
            opacity=0.5,
        )

        chart_path = config.CHARTS_DIR / f"chart_{_timestamp()}.png"
        fig.write_image(str(chart_path), scale=2)
        log.info(f"Placeholder chart generated: {chart_path}")
        return str(chart_path)

    except Exception as e:
        log.error(f"Placeholder chart generation also failed: {e}")
        return None


def _format_value(v) -> str:
    """Format large numbers nicely (e.g. 1000000 → $1M)."""
    if not isinstance(v, (int, float)):
        return str(v)
    if abs(v) >= 1_000_000_000:
        return f"${v / 1_000_000_000:.1f}B"
    if abs(v) >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if abs(v) >= 1_000:
        return f"${v / 1_000:.0f}K"
    return f"${v:,.0f}"


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")
