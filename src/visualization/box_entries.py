from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from mplsoccer import Pitch

from src.db import connect


def render_box_entries(match_id: int, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT start_x, start_y, end_x, end_y, action_type, is_cross
            FROM marts.box_entries be
            JOIN core.match_source_mapping msm
              ON msm.canonical_match_id = be.match_id
            WHERE msm.provider = 'statsbomb'
              AND msm.source_match_id = %s
            """,
            (str(match_id),),
        )
        rows = cur.fetchall()

    pitch = Pitch(pitch_type="statsbomb", line_zorder=2)
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
