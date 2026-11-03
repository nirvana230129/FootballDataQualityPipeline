from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from src.db import connect
from src.visualization.pitch import make_pitch


def render_box_entries(match_id: int, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT be.start_x, be.start_y, be.end_x, be.end_y, be.action_type, be.is_cross
            FROM marts.box_entries be
            JOIN core.match_source_mapping msm
              ON msm.canonical_match_id = be.match_id
            JOIN monitoring.match_publication_status mps
              ON mps.canonical_match_id = be.match_id
             AND mps.publication_status = 'PUBLISHABLE'
            WHERE msm.provider = 'statsbomb'
              AND msm.source_match_id = %s
            """,
            (str(match_id),),
        )
        rows = cur.fetchall()

    pitch = make_pitch()
    fig, ax = pitch.draw(figsize=(10, 7))
    ax.set_title(f"Box entries — StatsBomb match {match_id}")

    for start_x, start_y, end_x, end_y, action_type, is_cross in rows:
        color = "#d62728" if is_cross else ("#1f77b4" if action_type == "PASS" else "#2ca02c")
        pitch.arrows(
            start_x,
            start_y,
            end_x,
            end_y,
            ax=ax,
            color=color,
            width=1.2,
            headwidth=4,
            alpha=0.7,
        )

    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path
