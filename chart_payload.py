import json

import numpy as np
import plotly.io as pio

from figure_builder import build_subject_figure


def build_payload(
    subject_id: int,
    name: str,
    unit: str,
    lo: float | None,
    hi: float | None,
    low_traces: list[dict],
    full_traces: list[dict],
) -> dict:
    """
    Build a combined payload containing both:
      - low: pre-built Plotly figure JSON (data + layout) using downsampled CDFs
      - raw: per-school full CDF arrays + chart metadata, used by the server
             to synthesize the full-detail figure on demand
    """
    fig = build_subject_figure(low_traces, lo, hi, name, unit)
    fig_dict = json.loads(pio.to_json(fig))

    raw_traces = []
    for t in full_traces:
        xs = t["xs"]
        ys = t["ys"]
        raw_traces.append({
            "school": t["school"],
            "color": t["color"],
            "xs": xs.tolist() if isinstance(xs, np.ndarray) else list(xs),
            "ys": ys.tolist() if isinstance(ys, np.ndarray) else list(ys),
        })

    return {
        "id": subject_id,
        "name": name,
        "low": {
            "data": fig_dict["data"],
            "layout": fig_dict["layout"],
        },
        "raw": {
            "name": name,
            "unit": unit,
            "lo": None if lo is None or (isinstance(lo, float) and np.isnan(lo)) else float(lo),
            "hi": None if hi is None or (isinstance(hi, float) and np.isnan(hi)) else float(hi),
            "traces": raw_traces,
        },
    }
