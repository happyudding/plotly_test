"""Build a single dataset under output/datasets/<id>/ from school CSV files.

Used by:
  - server.py /upload endpoint (FileStorage objects from Flask)
  - build.py CLI (paths from disk for testing)
"""
import json
import time
from pathlib import Path
from typing import Union

import plotly.colors as pcolors

import page_builder
from chart_payload import build_payload
from config import DATASETS_DIR
from data_loader import load_table
from preprocess import cumulative_distribution_full, to_numeric_clean

COLOR_PALETTE = pcolors.qualitative.Plotly


def _save_upload(src, dest_path: Path) -> None:
    """Accept either a werkzeug FileStorage or a filesystem path."""
    if hasattr(src, "save"):
        src.save(str(dest_path))
    else:
        path = Path(src)
        dest_path.write_bytes(path.read_bytes())


def build_dataset(
    dataset_id: str,
    inputs: dict[str, Union[str, Path, object]],
) -> dict:
    """
    Build a dataset.

    Args:
        dataset_id: unique identifier (e.g. timestamp_hash). Used as directory name.
        inputs: dict[filename, source]. filename should end with `.csv`. source is
                either a path (str/Path) or a Flask FileStorage. The portion before
                `_school` (case-insensitive) becomes the school's display name.

    Returns:
        {"dataset_id", "build_version", "n_subjects", "n_schools", "elapsed_s"}
    """
    t0 = time.perf_counter()
    out_dir = DATASETS_DIR / dataset_id
    input_dir = out_dir / "input"
    charts_dir = out_dir / "charts"
    out_dir.mkdir(parents=True, exist_ok=True)
    input_dir.mkdir(exist_ok=True)
    charts_dir.mkdir(exist_ok=True)

    # 1) Save uploads to disk so they're auditable
    saved_paths: list[Path] = []
    for filename, src in inputs.items():
        safe_name = Path(filename).name  # strip any directory
        if not safe_name.lower().endswith(".csv"):
            continue
        dest = input_dir / safe_name
        _save_upload(src, dest)
        saved_paths.append(dest)

    if not saved_paths:
        raise ValueError("No valid CSV uploads received (need .csv extension)")

    # 2) Load schools and compute color map
    schools = {p.stem: load_table(p) for p in sorted(saved_paths)}
    school_names = list(schools.keys())
    color_map = {
        name: COLOR_PALETTE[i % len(COLOR_PALETTE)]
        for i, name in enumerate(school_names)
    }

    first = schools[school_names[0]]
    n_subjects = len(first.subjects)

    # 3) Build per-subject sharded JSON files (full-resolution, no LOD)
    for idx in range(n_subjects):
        traces = []
        for name in school_names:
            data = schools[name]
            values = to_numeric_clean(data.scores.iloc[:, idx])
            xs, ys = cumulative_distribution_full(values)
            traces.append({
                "school": name,
                "color": color_map[name],
                "xs": xs,
                "ys": ys,
            })

        payload = build_payload(
            idx,
            first.subjects[idx],
            first.units[idx] if idx < len(first.units) else "",
            first.lo_limits[idx] if idx < len(first.lo_limits) else None,
            first.hi_limits[idx] if idx < len(first.hi_limits) else None,
            traces,
        )
        (charts_dir / f"{idx}.json").write_text(json.dumps(payload), encoding="utf-8")

    # 4) Write HTML + version
    build_version = str(int(time.time()))
    (out_dir / "build_version.txt").write_text(build_version, encoding="utf-8")

    schools_info = [
        {"name": name, "color": color_map[name]} for name in school_names
    ]
    page_builder.write_html(
        out_dir / "cumulative.html",
        first.subjects,
        schools_info,
        dataset_id=dataset_id,
        build_version=build_version,
    )

    elapsed = time.perf_counter() - t0
    return {
        "dataset_id": dataset_id,
        "build_version": build_version,
        "n_subjects": n_subjects,
        "n_schools": len(school_names),
        "schools": school_names,
        "elapsed_s": round(elapsed, 2),
    }
