"""CLI: build a dataset from data/*_school*.csv for local testing.

Usage:
    python build.py [dataset_id]

If dataset_id is omitted, uses 'cli_test'. The result is placed under
output/datasets/<id>/ and viewable at http://127.0.0.1:8000/view/<id>
once the Flask server is running.
"""
import sys
from pathlib import Path

from config import INPUT_DIR, SCHOOL_FILES_GLOB
from dataset_builder import build_dataset


def main() -> None:
    dataset_id = sys.argv[1] if len(sys.argv) > 1 else "current"

    paths = sorted(INPUT_DIR.glob(SCHOOL_FILES_GLOB))
    if not paths:
        raise SystemExit(
            f"No files matching {SCHOOL_FILES_GLOB!r} in {INPUT_DIR}. "
            f"Drop CSVs there or upload via the web UI."
        )
    inputs = {p.name: p for p in paths}
    print(f"Building dataset '{dataset_id}' from {len(inputs)} files:")
    for name in inputs:
        print(f"  - {name}")

    result = build_dataset(dataset_id, inputs)
    print(f"\nDone: {result['n_subjects']} subjects, {result['n_schools']} schools, "
          f"{result['elapsed_s']}s")
    print(f"View at: http://127.0.0.1:8000/view/{dataset_id}")


if __name__ == "__main__":
    main()
