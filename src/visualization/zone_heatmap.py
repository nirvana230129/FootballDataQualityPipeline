from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import Normalize

from src.db import connect
from src.visualization.pitch import load_zones, make_pitch


def render_zone_heatmap(match_id: int, output_path: Path) -> Path:
    """Heatmap of start locations for possessions that end with a shot."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.start_x, p.start_y, p.start_zone
            FROM marts.possessions p
            JOIN core.match_source_mapping msm
              ON msm.canonical_match_id = p.match_id
            JOIN monitoring.match_publication_status mps
              ON mps.canonical_match_id = p.match_id
             AND mps.publication_status = 'PUBLISHABLE'
            WHERE msm.provider = 'statsbomb'
              AND msm.source_match_id = %s
              AND p.has_shot IS TRUE
              AND p.start_x IS NOT NULL
              AND p.start_y IS NOT NULL
            """,
            (str(match_id),),
        )
        points = cur.fetchall()
        zones = load_zones(conn)

    pitch = make_pitch()
    fig, ax = pitch.draw(figsize=(10, 7))
    ax.set_title(f"Shot-ending possession starts — StatsBomb match {match_id}")

    # Bin counts by named zone rectangles from config.
    counts: dict[str, int] = {name: 0 for name, *_ in zones}
    for start_x, start_y, start_zone in points:
        if start_zone and start_zone in counts:
            counts[start_zone] += 1
        else:
            for name, x_min, x_max, y_min, y_max in zones:
                if x_min <= start_x < x_max and y_min <= start_y < y_max:
                    counts[name] += 1
                    break

    max_count = max(counts.values()) if counts else 0
    norm = Normalize(vmin=0, vmax=max(max_count, 1))
    cmap = plt.get_cmap("YlOrRd")

    for name, x_min, x_max, y_min, y_max in zones:
        value = counts.get(name, 0)
        color = cmap(norm(value))
        ax.fill(
            [x_min, x_max, x_max, x_min],
            [y_min, y_min, y_max, y_max],
            color=color,
            alpha=0.55,
            zorder=1,
            linewidth=0,
        )
        if value > 0:
            ax.text(
                (x_min + x_max) / 2,
                (y_min + y_max) / 2,
                str(value),
                ha="center",
                va="center",
                fontsize=8,
                color="#102a43",
                zorder=3,
            )

    if points:
        xs = np.array([p[0] for p in points], dtype=float)
        ys = np.array([p[1] for p in points], dtype=float)
        ax.scatter(xs, ys, s=12, c="#102a43", alpha=0.35, zorder=4)

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    fig.colorbar(sm, ax=ax, fraction=0.03, pad=0.02, label="shot-ending starts")

    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path
