from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from src.db import connect
from src.visualization.pitch import make_pitch, match_minutes, per90


def render_progressive_passes(match_id: int, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                pp.start_x,
                pp.start_y,
                pp.end_x,
                pp.end_y,
                e.event_id,
                e.pass_outcome
            FROM marts.progressive_passes pp
            JOIN core.match_source_mapping msm
              ON msm.canonical_match_id = pp.match_id
            JOIN monitoring.match_publication_status mps
              ON mps.canonical_match_id = pp.match_id
             AND mps.publication_status = 'PUBLISHABLE'
            LEFT JOIN core.events e
              ON e.canonical_match_id = pp.match_id
             AND e.event_type = 'Pass'
             AND e.canonical_player_id IS NOT DISTINCT FROM pp.player_id
             AND ABS(e.x - pp.start_x) < 0.05
             AND ABS(e.y - pp.start_y) < 0.05
             AND ABS(e.end_x - pp.end_x) < 0.05
             AND ABS(e.end_y - pp.end_y) < 0.05
            WHERE msm.provider = 'statsbomb'
              AND msm.source_match_id = %s
            """,
            (str(match_id),),
        )
        rows = cur.fetchall()

        cur.execute(
            """
            SELECT COUNT(*)
            FROM marts.box_entries be
            JOIN core.match_source_mapping msm
              ON msm.canonical_match_id = be.match_id
            WHERE msm.provider = 'statsbomb'
              AND msm.source_match_id = %s
            """,
            (str(match_id),),
        )
        box_count = int(cur.fetchone()[0] or 0)
        minutes = match_minutes(conn, match_id)

    pitch = make_pitch()
    fig, ax = pitch.draw(figsize=(11, 7))
    ax.set_title(f"Progressive passes — StatsBomb match {match_id}")

    matched = 0
    completed = 0
    for start_x, start_y, end_x, end_y, event_id, pass_outcome in rows:
        if event_id is not None:
            matched += 1
            if pass_outcome is None:
                completed += 1
                color = "#1f77b4"
            else:
                color = "#d62728"
        else:
            color = "#7f7f7f"
        pitch.arrows(
            start_x,
            start_y,
            end_x,
            end_y,
            ax=ax,
            color=color,
            width=1.0,
            headwidth=3.5,
            alpha=0.65,
        )

    n = len(rows)
    if matched == 0:
        completion_label = "N/A"
    else:
        completion_label = f"{100.0 * completed / matched:.0f}%"

    prog_per90 = per90(n, minutes)
    box_per90 = per90(box_count, minutes)
    panel = (
        f"progressive: {n}\n"
        f"progressive / 90: {prog_per90:.1f}\n"
        f"completion %: {completion_label}\n"
        f"box entries / 90: {box_per90:.1f}\n"
        f"minutes used: {minutes:.0f}"
    )
    ax.text(
        1.02,
        0.5,
        panel,
        transform=ax.transAxes,
        va="center",
        ha="left",
        fontsize=10,
        family="monospace",
        bbox={"boxstyle": "round,pad=0.4", "facecolor": "#f5f7fa", "edgecolor": "#334e68"},
    )

    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path
