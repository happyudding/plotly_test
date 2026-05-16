import json
import time

import plotly.colors as pcolors

import page_builder
from chart_payload import build_payload
from config import (
    CHART_DATA_PATH,
    INPUT_DIR,
    OUTPUT_DIR,
    OUTPUT_PATH,
    SCHOOL_FILES_GLOB,
)
from data_loader import load_table
from preprocess import cumulative_distribution, to_numeric_clean

COLOR_PALETTE = pcolors.qualitative.Plotly


def main() -> None:
    t0 = time.perf_counter()

    school_paths = sorted(INPUT_DIR.glob(SCHOOL_FILES_GLOB))
    if not school_paths:
        raise SystemExit(
            f"No files match {SCHOOL_FILES_GLOB!r} in {INPUT_DIR}. "
            f"Place school files (e.g. a_school.csv) and re-run."
        )

    schools = {p.stem: load_table(p) for p in school_paths}
    school_names = list(schools.keys())
    color_map = {
        name: COLOR_PALETTE[i % len(COLOR_PALETTE)]
        for i, name in enumerate(school_names)
    }
    print(f"Loaded {len(school_names)} schools: {', '.join(school_names)}")
    for name, data in schools.items():
        print(f"  {name}: {len(data.subjects)} subjects, {len(data.scores)} student rows")

    first = schools[school_names[0]]
    n = len(first.subjects)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    payloads = []
    for idx in range(n):
        traces = []
        for name in school_names:
            data = schools[name]
            values = to_numeric_clean(data.scores.iloc[:, idx])
            xs, ys = cumulative_distribution(values)
            traces.append({
                "school": name,
                "color": color_map[name],
                "xs": xs,
                "ys": ys,
            })

        payloads.append(build_payload(
            idx,
            first.subjects[idx],
            first.units[idx] if idx < len(first.units) else "",
            first.lo_limits[idx] if idx < len(first.lo_limits) else None,
            first.hi_limits[idx] if idx < len(first.hi_limits) else None,
            traces,
        ))

    CHART_DATA_PATH.write_text(json.dumps(payloads), encoding="utf-8")
    print(f"Wrote {CHART_DATA_PATH}")

    schools_info = [
        {"name": name, "color": color_map[name]} for name in school_names
    ]
    page_builder.write_html(OUTPUT_PATH, first.subjects, schools_info)
    print(f"Wrote {OUTPUT_PATH}")
    print(f"Done in {time.perf_counter() - t0:.2f}s")


if __name__ == "__main__":
    main()
