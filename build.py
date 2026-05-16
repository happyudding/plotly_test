import json
import time

import page_builder
from chart_payload import build_payload
from config import CHART_DATA_PATH, EXCEL_PATH, OUTPUT_DIR, OUTPUT_PATH
from data_loader import load_excel
from preprocess import cumulative_distribution, to_numeric_clean


def main() -> None:
    t0 = time.perf_counter()
    data = load_excel(EXCEL_PATH)
    n = len(data.subjects)
    print(f"Loaded {n} subjects, {len(data.scores)} student rows")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    payloads = []
    for idx in range(n):
        subject = data.subjects[idx]
        unit = data.units[idx] if idx < len(data.units) else ""
        lo = data.lo_limits[idx] if idx < len(data.lo_limits) else None
        hi = data.hi_limits[idx] if idx < len(data.hi_limits) else None

        values = to_numeric_clean(data.scores.iloc[:, idx])
        xs, ys = cumulative_distribution(values)

        payloads.append(build_payload(idx, subject, unit, lo, hi, xs, ys))

    CHART_DATA_PATH.write_text(json.dumps(payloads), encoding="utf-8")
    print(f"Wrote {CHART_DATA_PATH}")

    page_builder.write_html(OUTPUT_PATH, data.subjects)
    print(f"Wrote {OUTPUT_PATH}")
    print(f"Done in {time.perf_counter() - t0:.2f}s")


if __name__ == "__main__":
    main()
