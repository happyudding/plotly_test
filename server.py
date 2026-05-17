"""Flask blueprint — debug mode (single 'current' dataset).

Endpoints:
  GET  /                       — redirect to /view/current
  GET  /view/<id>              — serve cumulative.html for a dataset
  GET  /api/<id>/chart/<sid>   — serve per-subject JSON
  GET  /api/<id>/build_version — version for client cache invalidation

Run `python build.py [dataset_id]` first to populate output/datasets/<id>/.
The default dataset_id is 'current', and / redirects there.

Memory model: zero per request (sendfile). All builds are CLI-triggered.
"""
from pathlib import Path

from flask import Blueprint, abort, jsonify, redirect, send_from_directory

from config import DATASETS_DIR

bp = Blueprint("cumulative", __name__)

DEFAULT_DATASET = "current"


@bp.get("/")
def index():
    return redirect(f"/view/{DEFAULT_DATASET}", code=302)


@bp.get("/view/<id>")
def view(id):
    if not _is_safe_id(id):
        abort(400)
    path = DATASETS_DIR / id / "cumulative.html"
    if not path.exists():
        abort(404, f"Dataset '{id}' not built. Run: python build.py {id}")
    resp = send_from_directory(DATASETS_DIR / id, "cumulative.html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.get("/api/<id>/chart/<int:sid>")
def chart(id, sid):
    if not _is_safe_id(id):
        abort(400)
    path = DATASETS_DIR / id / "charts" / f"{sid}.json"
    if not path.exists():
        abort(404)
    resp = send_from_directory(DATASETS_DIR / id / "charts", f"{sid}.json")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.get("/api/<id>/build_version")
def build_version(id):
    if not _is_safe_id(id):
        abort(400)
    path = DATASETS_DIR / id / "build_version.txt"
    if not path.exists():
        abort(404)
    version = path.read_text(encoding="utf-8").strip()
    return jsonify({"version": version, "dataset_id": id})


def _is_safe_id(id: str) -> bool:
    if not id or len(id) > 80:
        return False
    return all(c.isalnum() or c in "-_" for c in id)
