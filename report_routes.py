import json
import re
import secrets
import shutil
import time
from pathlib import Path

from flask import abort, jsonify, request
from werkzeug.utils import secure_filename

import report_db
import report_s3
from config import REPORT_UPLOAD_DIR
from report_analysis_service import (
    AnalysisError,
    AnalysisLockTimeout,
    get_or_compute_analysis,
    upload_derived_if_absent,
)
from report_extension import report_bp
from report_plot_service import PlotError, PlotLockTimeout, get_or_create_plot
from report_s3 import S3NotConfigured, S3ObjectCorrupted

_ANALYSIS_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def _validate_analysis_key(value):
    if not value or not _ANALYSIS_KEY_RE.match(value):
        abort(400, "invalid analysis_key")


def _validate_session_id(value):
    if not value or not _SESSION_ID_RE.match(value):
        abort(400, "invalid session_id")


def _parse_options(raw):
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        abort(400, "options must be valid JSON")


def _is_safe_csv_name(name):
    return bool(name) and name.lower().endswith(".csv")


def _resolve_under_upload_dir(path):
    base = REPORT_UPLOAD_DIR.resolve()
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        abort(400, "path traversal blocked")
    return resolved


def _upload_csvs_to_s3(saved_paths, analysis_key):
    """로컬 CSV를 S3에 올리고 report_csv_files에 기록."""
    for path in saved_paths:
        s3_key = report_s3.make_csv_s3_key(analysis_key, path.name)
        if not report_s3.s3_object_exists(s3_key):
            data = path.read_bytes()
            uri = report_s3.upload_bytes_to_s3(s3_key, data, "text/csv; charset=utf-8")
        else:
            uri = report_s3.make_s3_uri(s3_key)
            data = path.read_bytes() if path.exists() else b""
        report_db.upsert_csv_file(analysis_key, path.name, s3_key, uri, len(data))


@report_bp.post("/analyze")
def analyze():
    files = request.files.getlist("files")
    if not files:
        abort(400, "no files uploaded")

    options = _parse_options(request.form.get("options"))

    session_id = f"{int(time.time())}_{secrets.token_hex(3)}"
    REPORT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    session_dir = REPORT_UPLOAD_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    _resolve_under_upload_dir(session_dir)

    saved_paths = []
    saved_names = []
    for f in files:
        raw_name = f.filename or ""
        name = secure_filename(raw_name)
        if not _is_safe_csv_name(name):
            continue
        dest = session_dir / name
        f.save(str(dest))
        saved_paths.append(dest)
        saved_names.append(name)

    if not saved_paths:
        try:
            shutil.rmtree(session_dir, ignore_errors=True)
        except OSError:
            pass
        abort(400, "no valid CSV files (need .csv extension)")

    report_db.create_session(
        session_id=session_id,
        file_name=",".join(saved_names),
        file_path=str(session_dir),
    )

    try:
        result = get_or_compute_analysis(session_id, saved_paths, options)
    except AnalysisLockTimeout as exc:
        return jsonify({"session_id": session_id, "status": "busy", "error": str(exc)}), 503
    except AnalysisError as exc:
        report_db.update_session(session_id, status="failed", error_message=str(exc)[:1000])
        return jsonify({"session_id": session_id, "status": "failed", "error": str(exc)}), 400
    except Exception as exc:
        report_db.update_session(session_id, status="failed", error_message=str(exc)[:1000])
        return jsonify({"session_id": session_id, "status": "failed", "error": str(exc)}), 500

    analysis_key = result["analysis_key"]

    # S3 업로드 (CSV + derived) 후 로컬 임시 파일 삭제
    try:
        _upload_csvs_to_s3(saved_paths, analysis_key)
        upload_derived_if_absent(
            analysis_key, result["content_hash"], result["options_json"], saved_paths,
        )
    except S3NotConfigured:
        pass  # S3 미설정 환경에서는 로컬만
    except Exception:
        pass  # S3 실패가 분석 결과 반환을 막으면 안 됨
    finally:
        shutil.rmtree(session_dir, ignore_errors=True)

    return jsonify({
        "session_id": session_id,
        "analysis_key": analysis_key,
        "reused": result["reused"],
        "status": "reused" if result["reused"] else "done",
        "summary": result["summary"],
    })


@report_bp.get("/result/<session_id>")
def result(session_id):
    _validate_session_id(session_id)
    session = report_db.get_session(session_id)
    if not session:
        abort(404, "session not found")
    analysis_key = session.get("analysis_key")
    summary = report_db.get_summary_by_analysis_key(analysis_key) if analysis_key else []
    return jsonify({
        "session_id": session_id,
        "analysis_key": analysis_key,
        "status": session.get("status"),
        "file_name": session.get("file_name"),
        "error_message": session.get("error_message"),
        "summary": summary,
    })


@report_bp.get("/session/<session_id>")
def session_info(session_id):
    _validate_session_id(session_id)
    session = report_db.get_session(session_id)
    if not session:
        abort(404, "session not found")
    return jsonify(session)


@report_bp.get("/session/<session_id>/full")
def session_full(session_id):
    """세션 완전 복원에 필요한 모든 참조 반환."""
    _validate_session_id(session_id)
    session = report_db.get_session(session_id)
    if not session:
        abort(404, "session not found")
    akey = session.get("analysis_key")
    objects = {}
    if akey:
        for obj in report_db.get_all_object_infos(akey):
            objects[obj["object_type"]] = {
                "s3_uri": obj["s3_uri"],
                "s3_key": obj["s3_key"],
            }
    return jsonify({
        "session": session,
        "summary": report_db.get_summary_by_analysis_key(akey) if akey else [],
        "csv_files": report_db.get_csv_files(akey) if akey else [],
        "objects": objects,
        "annotations": report_db.get_annotations(session_id),
    })


@report_bp.post("/plot")
def plot_post():
    body = request.get_json(force=True, silent=True) or {}
    analysis_key = body.get("analysis_key")
    _validate_analysis_key(analysis_key)
    session_id = body.get("session_id")
    options = body.get("options")

    try:
        payload = get_or_create_plot(analysis_key, session_id=session_id, options=options)
    except S3NotConfigured as exc:
        return jsonify({"error": f"S3 not configured: {exc}"}), 503
    except S3ObjectCorrupted as exc:
        return jsonify({"error": f"S3 object corrupted: {exc}"}), 500
    except PlotLockTimeout as exc:
        return jsonify({"error": str(exc)}), 503
    except PlotError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(payload)


@report_bp.get("/plot/<analysis_key>")
def plot_get(analysis_key):
    _validate_analysis_key(analysis_key)
    try:
        payload = get_or_create_plot(analysis_key)
    except S3NotConfigured as exc:
        return jsonify({"error": f"S3 not configured: {exc}"}), 503
    except S3ObjectCorrupted as exc:
        return jsonify({"error": f"S3 object corrupted: {exc}"}), 500
    except PlotLockTimeout as exc:
        return jsonify({"error": str(exc)}), 503
    except PlotError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(payload)


# ── CSV ───────────────────────────────────────────────────────────────────────

@report_bp.get("/csv/<analysis_key>")
def list_csv(analysis_key):
    _validate_analysis_key(analysis_key)
    return jsonify(report_db.get_csv_files(analysis_key))


# ── fail_items / issue_table ──────────────────────────────────────────────────

@report_bp.get("/fail_items/<analysis_key>")
def get_fail_items(analysis_key):
    _validate_analysis_key(analysis_key)
    info = report_db.get_object_info(analysis_key, "fail_items")
    if not info:
        abort(404, "fail_items not found for this analysis_key")
    try:
        payload = report_s3.download_json_from_s3(info["s3_key"])
    except S3NotConfigured as exc:
        return jsonify({"error": f"S3 not configured: {exc}"}), 503
    except S3ObjectCorrupted as exc:
        return jsonify({"error": f"corrupted: {exc}"}), 500
    report_db.touch_object_info(analysis_key, "fail_items")
    return jsonify(payload)


@report_bp.get("/issue_table/<analysis_key>")
def get_issue_table(analysis_key):
    _validate_analysis_key(analysis_key)
    info = report_db.get_object_info(analysis_key, "issue_table")
    if not info:
        abort(404, "issue_table not found for this analysis_key")
    try:
        payload = report_s3.download_json_from_s3(info["s3_key"])
    except S3NotConfigured as exc:
        return jsonify({"error": f"S3 not configured: {exc}"}), 503
    except S3ObjectCorrupted as exc:
        return jsonify({"error": f"corrupted: {exc}"}), 500
    report_db.touch_object_info(analysis_key, "issue_table")
    return jsonify(payload)


# ── annotations ───────────────────────────────────────────────────────────────

@report_bp.post("/annotation")
def create_annotation():
    body = request.get_json(force=True, silent=True) or {}
    session_id = body.get("session_id", "")
    _validate_session_id(session_id)
    analysis_key = body.get("analysis_key")
    target = (body.get("target") or "").strip()
    content = (body.get("content") or "").strip()
    if not target or not content:
        abort(400, "target and content are required")
    ann_id = report_db.create_annotation(session_id, analysis_key, target, content)
    return jsonify({"id": ann_id, "session_id": session_id, "target": target}), 201


@report_bp.get("/annotation/<session_id>")
def list_annotations(session_id):
    _validate_session_id(session_id)
    return jsonify(report_db.get_annotations(session_id))


@report_bp.patch("/annotation/<int:aid>")
def update_annotation(aid):
    body = request.get_json(force=True, silent=True) or {}
    content = (body.get("content") or "").strip()
    if not content:
        abort(400, "content is required")
    report_db.update_annotation(aid, content)
    return jsonify({"id": aid, "updated": True})


@report_bp.delete("/annotation/<int:aid>")
def delete_annotation(aid):
    report_db.delete_annotation(aid)
    return jsonify({"id": aid, "deleted": True})
