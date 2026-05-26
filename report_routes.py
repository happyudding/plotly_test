import json
import re
import secrets
import shutil
import threading
import time
from pathlib import Path

from flask import abort, jsonify, request, send_file
from werkzeug.utils import secure_filename

import report_db
import report_s3
from config import INPUT_DIR, ROOT_DIR, REPORT_UPLOAD_DIR, SCHOOL_FILES_GLOB
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
    product_type = request.form.get("product_type") or None

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
        product_type=product_type,
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

    # S3 업로드 (CSV + derived + fail subject 썸네일만) 후 로컬 임시 파일 삭제
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
        "thumb_url_template": (f"/pe/report/thumb/{akey}/{{subject_id}}"
                               if akey and "thumbs_fail_set" in objects else None),
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


# ── per-subject SVG thumbnails ────────────────────────────────────────────────

@report_bp.get("/thumb/<analysis_key>/<int:sid>")
def get_thumb(analysis_key, sid):
    """과목별 SVG 썸네일을 S3에서 받아 반환. fail_items HTML이 <img>로 참조."""
    from flask import Response
    _validate_analysis_key(analysis_key)
    s3_key = report_s3.make_thumb_s3_key(analysis_key, sid)
    try:
        data = report_s3.download_bytes_from_s3(s3_key)
    except S3NotConfigured as exc:
        return jsonify({"error": f"S3 not configured: {exc}"}), 503
    except Exception:
        abort(404, "thumbnail not found")
    return Response(
        data,
        mimetype="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )


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


# ── Report Analysis index / view pages ───────────────────────────────────────

@report_bp.get("/")
def index_page():
    return send_file(ROOT_DIR / "report_analysis_index.html")


@report_bp.get("/view/<session_id>")
def view_page(session_id):
    _validate_session_id(session_id)
    return send_file(ROOT_DIR / "report_view.html")


@report_bp.post("/_analyze-only")
def debug_analyze_only():
    """빌드 없이 분석만 단독 실행 (build_dataset과의 충돌 격리용).
    동기 실행 — 결과 또는 에러를 즉시 반환."""
    debug_files = sorted(INPUT_DIR.glob(SCHOOL_FILES_GLOB))
    if not debug_files:
        abort(400, f"디버그 CSV 없음: {INPUT_DIR}/{SCHOOL_FILES_GLOB}")
    session_id = f"{int(time.time())}_analyzeonly_{secrets.token_hex(3)}"
    report_db.create_session(
        session_id=session_id,
        file_name=",".join(p.name for p in debug_files),
        file_path=str(INPUT_DIR),
        product_type=None,
    )
    try:
        result = get_or_compute_analysis(session_id, debug_files, {})
        return jsonify({
            "session_id": session_id,
            "analysis_key": result["analysis_key"],
            "reused": result["reused"],
            "rows": len(result["summary"]),
            "status": "ok",
        })
    except Exception as exc:
        import traceback
        return jsonify({
            "session_id": session_id,
            "status": "error",
            "error": str(exc),
            "trace": traceback.format_exc(),
        }), 500


@report_bp.get("/_threads")
def debug_threads():
    """모든 스레드의 stack trace 덤프. hang 진단용."""
    import sys, threading, traceback
    out = []
    tid_to_name = {t.ident: t.name for t in threading.enumerate()}
    for tid, frame in sys._current_frames().items():
        name = tid_to_name.get(tid, "?")
        out.append(f"=== Thread {tid} ({name}) ===")
        out.append("".join(traceback.format_stack(frame)))
    from flask import Response
    return Response("\n".join(out), mimetype="text/plain; charset=utf-8")


@report_bp.get("/api/history")
def history():
    product_type = request.args.get("product_type") or None
    process = request.args.get("process") or None
    product = request.args.get("product") or None
    revision = request.args.get("revision") or None
    rows = report_db.get_history(
        product_type=product_type,
        process=process,
        product=product,
        revision=revision,
    )
    return jsonify(rows)


@report_bp.post("/execute-debug")
def execute_debug():
    """로컬 디버그 CSV(a~c_school_updated_call.csv)로 전체 파이프라인 실행.
    cumulative dashboard 빌드 + report analysis DB/S3 저장을 동시 수행."""
    from dataset_builder import build_dataset
    from server import _build_lock, _build_status

    if request.is_json:
        body = request.get_json(silent=True, force=True) or {}
        product_type = body.get("product_type") or None
    else:
        product_type = request.form.get("product_type") or None

    debug_files = sorted(INPUT_DIR.glob(SCHOOL_FILES_GLOB))
    if not debug_files:
        abort(400, f"디버그 CSV 파일을 찾을 수 없음: {INPUT_DIR}/{SCHOOL_FILES_GLOB}")

    dataset_id = f"{int(time.time())}_{secrets.token_hex(3)}"
    session_id = f"{int(time.time())}_{secrets.token_hex(3)}"
    inputs = {p.name: p for p in debug_files}
    file_names = ",".join(p.name for p in debug_files)

    report_db.create_session(
        session_id=session_id,
        file_name=file_names,
        file_path=str(INPUT_DIR),
        product_type=product_type,
        dataset_id=dataset_id,
    )

    def _set_status(s):
        with _build_lock:
            _build_status[s["dataset_id"]] = s

    def _run_analysis():
        """report analysis를 빌드와 병렬로 실행."""
        import traceback
        print(f"[bg:{session_id}] analysis thread START", flush=True)
        try:
            result = get_or_compute_analysis(session_id, debug_files, {})
            analysis_key = result["analysis_key"]
            print(f"[bg:{session_id}] analysis done, S3 uploads next", flush=True)
            try:
                _upload_csvs_to_s3(debug_files, analysis_key)
                upload_derived_if_absent(
                    analysis_key, result["content_hash"], result["options_json"], debug_files,
                )
                print(f"[bg:{session_id}] S3 uploads done", flush=True)
            except S3NotConfigured:
                print(f"[bg:{session_id}] S3 not configured, skipping uploads", flush=True)
            except Exception as s3exc:
                print(f"[bg:{session_id}] S3 upload error: {s3exc}", flush=True)
                traceback.print_exc()
        except AnalysisLockTimeout as exc:
            print(f"[bg:{session_id}] LOCK TIMEOUT: {exc}", flush=True)
            report_db.update_session(session_id, status="failed", error_message=str(exc)[:500])
        except (AnalysisError, Exception) as exc:
            print(f"[bg:{session_id}] ANALYSIS FAIL: {type(exc).__name__}: {exc}", flush=True)
            traceback.print_exc()
            report_db.update_session(session_id, status="failed", error_message=str(exc)[:500])
        print(f"[bg:{session_id}] analysis thread END", flush=True)

    def _bg():
        # report analysis 와 cumulative dashboard 빌드를 병렬로 실행
        print(f"[bg:{session_id}] _bg start, spawning analysis thread", flush=True)
        analysis_thread = threading.Thread(target=_run_analysis, daemon=True)
        analysis_thread.start()

        try:
            _set_status({"dataset_id": dataset_id, "stage": "queued", "current": 0, "total": 0, "elapsed_s": 0})
            print(f"[bg:{session_id}] build_dataset START", flush=True)
            r = build_dataset(dataset_id, inputs, progress_cb=_set_status)
            print(f"[bg:{session_id}] build_dataset DONE in {r['elapsed_s']}s", flush=True)
            _set_status({
                "dataset_id": dataset_id, "stage": "done",
                "current": r["n_subjects"], "total": r["n_subjects"],
                "elapsed_s": r["elapsed_s"],
            })
        except Exception as exc:
            print(f"[bg:{session_id}] build_dataset FAIL: {exc}", flush=True)
            _set_status({"dataset_id": dataset_id, "stage": "error", "error": str(exc)})

        print(f"[bg:{session_id}] waiting for analysis thread to finish...", flush=True)
        analysis_thread.join()  # 빌드 완료 후 분석도 끝날 때까지 대기
        print(f"[bg:{session_id}] _bg END", flush=True)

    threading.Thread(target=_bg, daemon=True).start()

    return jsonify({
        "session_id": session_id,
        "dataset_id": dataset_id,
        "view_url": f"/view/{dataset_id}",
    })
