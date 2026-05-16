import json
from pathlib import Path

from flask import Blueprint, abort, jsonify, send_from_directory

from config import CHART_DATA_PATH, OUTPUT_PATH

bp = Blueprint("cumulative", __name__)


def _load_chart_data() -> dict[int, dict]:
    try:
        with open(CHART_DATA_PATH, encoding="utf-8") as f:
            return {p["id"]: p for p in json.load(f)}
    except FileNotFoundError:
        print(f"WARNING: {CHART_DATA_PATH} not found. Run build.py first.")
        return {}


_chart_data: dict[int, dict] = _load_chart_data()
_html_dir = Path(OUTPUT_PATH).parent
_html_name = Path(OUTPUT_PATH).name


@bp.get("/")
def index():
    resp = send_from_directory(_html_dir, _html_name)
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


@bp.get("/api/chart/<int:subject_id>")
def get_chart(subject_id):
    payload = _chart_data.get(subject_id)
    if payload is None:
        abort(404)
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp
