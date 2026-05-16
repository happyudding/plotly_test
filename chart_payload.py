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
    xs: np.ndarray,
    ys: np.ndarray,
) -> dict:
    fig = build_subject_figure(xs, ys, lo, hi, name, unit)
    fig_dict = json.loads(pio.to_json(fig))
    return {
        "id": subject_id,
        "name": name,
        "data": fig_dict["data"],
        "layout": fig_dict["layout"],
    }
