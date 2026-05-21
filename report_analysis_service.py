import hashlib
import json
import math
import time
from pathlib import Path

import report_db
import report_s3
from config import (
    REPORT_LOCK_MAX_WAIT_SEC,
    REPORT_LOCK_POLL_SEC,
    REPORT_S3_BUCKET,
)
from data_loader import load_table
from table_builder import (
    _build_cpk,
    _build_fail_items,
    _build_yield,
    _fail_mask_for_table,
)

_CHUNK = 64 * 1024


class AnalysisError(RuntimeError):
    pass


class AnalysisLockTimeout(RuntimeError):
    pass


# ---------- hash / key helpers --------------------------------------------

def hash_files_streaming(file_paths):
    h = hashlib.sha256()
    for path in sorted(file_paths, key=lambda p: p.name):
        h.update(path.name.encode("utf-8"))
        h.update(b"\x00")
        with open(path, "rb") as f:
            while True:
                chunk = f.read(_CHUNK)
                if not chunk:
                    break
                h.update(chunk)
        h.update(b"\x00")
    return h.hexdigest()


def normalize_options(options):
    if options is None:
        options = {}
    return json.dumps(options, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def compute_analysis_key(content_hash, options_json):
    digest = hashlib.sha256()
    digest.update(content_hash.encode("utf-8"))
    digest.update(b":")
    digest.update(options_json.encode("utf-8"))
    return digest.hexdigest()


# ---------- numeric helpers ------------------------------------------------

def _to_float(value):
    if value is None or value == "N/A":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _try_int(value):
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f) or not f.is_integer():
        return None
    return int(f)


# ---------- summary mapping ------------------------------------------------

def _combined_fail_count(schools, subject_idx):
    """subject 별, 전체 school 합산 fail count (lsl/usl 초과)."""
    total_fail = 0
    total_rows = 0
    for table in schools.values():
        mask = _fail_mask_for_table(table)
        if subject_idx >= mask.shape[1]:
            continue
        col = mask.iloc[:, subject_idx]
        total_fail += int(col.sum())
        total_rows += int(len(col))
    return total_fail, total_rows


def build_summary_rows(schools):
    """(item, bin) summary row list 생성. 분석 결과 자체는 변경 없음."""
    cpk_rows = _build_cpk(schools)
    yield_rows = _build_yield(schools)
    fail_items = _build_fail_items(schools)["rows"]

    rows = []

    # 1) per-subject overall (bin_number=NULL)
    for idx, cpk in enumerate(cpk_rows):
        fail_count, total_rows = _combined_fail_count(schools, idx)
        yield_pct = ((total_rows - fail_count) / total_rows * 100.0) if total_rows else None
        rows.append({
            "item_name": str(cpk["subject"]),
            "bin_number": None,
            "yield_percent": yield_pct,
            "fail_count": fail_count,
            "cpk_val": _to_float(cpk.get("cpk")),
            "mean_val": _to_float(cpk.get("average")),
            "stdev_val": _to_float(cpk.get("stdev")),
            "lsl": _to_float(cpk.get("lo_limit")),
            "usl": _to_float(cpk.get("hi_limit")),
            "unit": cpk.get("unit") or "",
        })

    # 2) per-bin × item (fail_subjects 펼침)
    seen = set()  # (item_name, bin_number)
    for fail_row in fail_items:
        bin_n = _try_int(fail_row.get("student_type"))
        if bin_n is None:
            continue
        for fs in fail_row.get("fail_subjects") or []:
            item_name = str(fs.get("subject"))
            key = (item_name, bin_n)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "item_name": item_name,
                "bin_number": bin_n,
                "yield_percent": _to_float(fs.get("portion (%)")),
                "fail_count": int(fs.get("count") or 0),
                "cpk_val": None,
                "mean_val": None,
                "stdev_val": None,
                "lsl": None,
                "usl": None,
                "unit": None,
            })

    # 3) bin 전체 (item_name = "__bin_total__") — yield row 자체 정보 보존
    for yrow in yield_rows:
        bin_n = _try_int(yrow.get("student_type"))
        if bin_n is None:
            continue
        rows.append({
            "item_name": "__bin_total__",
            "bin_number": bin_n,
            "yield_percent": _to_float(yrow.get("portion (%)")),
            "fail_count": int(yrow.get("count") or 0),
            "cpk_val": None,
            "mean_val": None,
            "stdev_val": None,
            "lsl": None,
            "usl": None,
            "unit": None,
        })

    return rows


# ---------- issue_table (fail_values) builder --------------------------------

def _build_issue_table(schools):
    """비합격 학생별 측정값 초과 레코드 (fail_values). 전 학교 통합."""
    from table_builder import PASS_STUDENT_TYPE, _fmt_type, _fmt_num, _subject_columns
    import pandas as pd

    rows = []
    for source_name, table in schools.items():
        subjects_list = _subject_columns(table)
        n_sub = len(subjects_list)
        meta = table.meta.reset_index(drop=True).copy()
        meta["student_type"] = meta["student_type"].map(_fmt_type)
        non_pass = meta["student_type"] != PASS_STUDENT_TYPE
        if not non_pass.any():
            continue
        meta_np = meta[non_pass].reset_index(drop=True)
        scores_np = table.scores[non_pass].reset_index(drop=True)
        numeric = scores_np.apply(pd.to_numeric, errors="coerce")
        lo_arr = [table.lo_limits[i] if i < len(table.lo_limits) else None for i in range(n_sub)]
        hi_arr = [table.hi_limits[i] if i < len(table.hi_limits) else None for i in range(n_sub)]
        fail_lo = pd.DataFrame(False, index=numeric.index, columns=numeric.columns)
        fail_hi = pd.DataFrame(False, index=numeric.index, columns=numeric.columns)
        for idx in range(n_sub):
            col_s = numeric.iloc[:, idx]
            if lo_arr[idx] is not None and pd.notna(lo_arr[idx]):
                fail_lo.iloc[:, idx] = (col_s < float(lo_arr[idx])).fillna(False)
            if hi_arr[idx] is not None and pd.notna(hi_arr[idx]):
                fail_hi.iloc[:, idx] = (col_s > float(hi_arr[idx])).fillna(False)
        fail_any = (fail_lo | fail_hi)
        failing = fail_any.stack()
        failing = failing[failing]
        for row_i, col_i in failing.index:
            is_lo = bool(fail_lo.at[row_i, col_i])
            meta_row = meta_np.iloc[row_i]
            rows.append({
                "source": source_name,
                "call": _fmt_type(meta_row["call"]),
                "grade": _fmt_type(meta_row["grade"]),
                "class": _fmt_type(meta_row["class"]),
                "student_type": _fmt_type(meta_row["student_type"]),
                "subject": subjects_list[col_i],
                "value": _fmt_num(numeric.at[row_i, col_i]),
                "lo_limit": _fmt_num(lo_arr[col_i]) if (lo_arr[col_i] is not None and pd.notna(lo_arr[col_i])) else "N/A",
                "hi_limit": _fmt_num(hi_arr[col_i]) if (hi_arr[col_i] is not None and pd.notna(hi_arr[col_i])) else "N/A",
                "fail": "< lo" if is_lo else "> hi",
            })
    return rows


def upload_derived_if_absent(analysis_key, content_hash, options_json, file_paths):
    """fail_items + issue_table → S3 업로드 (이미 있으면 스킵).

    file_paths: list of Path — 분석에 사용된 CSV 파일들 (로컬에 있어야 함).
    """
    need_fail = not report_db.get_object_info(analysis_key, "fail_items")
    need_issue = not report_db.get_object_info(analysis_key, "issue_table")
    if not need_fail and not need_issue:
        return

    file_paths = [Path(p) for p in file_paths]
    schools = {p.stem: load_table(p) for p in sorted(file_paths, key=lambda x: x.name)}

    if need_fail:
        fail_data = _build_fail_items(schools)
        s3_key = report_s3.make_fail_items_s3_key(analysis_key)
        uri = report_s3.upload_json_to_s3(s3_key, fail_data)
        report_db.upsert_object_info(
            analysis_key, content_hash, options_json,
            "fail_items", REPORT_S3_BUCKET, s3_key, uri,
        )

    if need_issue:
        issue_data = _build_issue_table(schools)
        s3_key = report_s3.make_issue_table_s3_key(analysis_key)
        uri = report_s3.upload_json_to_s3(s3_key, issue_data)
        report_db.upsert_object_info(
            analysis_key, content_hash, options_json,
            "issue_table", REPORT_S3_BUCKET, s3_key, uri,
        )


# ---------- top-level flow -------------------------------------------------

def _wait_for_summary(analysis_key, lock_owner):
    deadline = time.time() + REPORT_LOCK_MAX_WAIT_SEC
    while time.time() < deadline:
        if report_db.has_summary(analysis_key):
            return True
        if report_db.try_acquire_analysis_lock(analysis_key, lock_owner):
            return False
        time.sleep(REPORT_LOCK_POLL_SEC)
    raise AnalysisLockTimeout(f"analysis_key {analysis_key} busy > {REPORT_LOCK_MAX_WAIT_SEC}s")


def get_or_compute_analysis(session_id, file_paths, options):
    """analyze 흐름의 핵심.

    Returns: {"reused": bool, "analysis_key": str, "content_hash": str,
              "options_json": str, "summary": list[dict]}
    """
    file_paths = [Path(p) for p in file_paths]
    for p in file_paths:
        if not p.exists():
            raise AnalysisError(f"missing file: {p}")

    content_hash = hash_files_streaming(file_paths)
    options_json = normalize_options(options)
    analysis_key = compute_analysis_key(content_hash, options_json)

    report_db.update_session(
        session_id,
        analysis_key=analysis_key,
        content_hash=content_hash,
        status="running",
    )

    # cache hit?
    if report_db.has_summary(analysis_key):
        report_db.update_session(session_id, status="reused")
        return {
            "reused": True,
            "analysis_key": analysis_key,
            "content_hash": content_hash,
            "options_json": options_json,
            "summary": report_db.get_summary_by_analysis_key(analysis_key),
        }

    # lock 획득. 다른 워커가 계산중이면 대기 후 캐시 재조회.
    lock_owner = f"analyze:{session_id}"
    if not report_db.try_acquire_analysis_lock(analysis_key, lock_owner):
        already_done = _wait_for_summary(analysis_key, lock_owner)
        if already_done:
            report_db.update_session(session_id, status="reused")
            return {
                "reused": True,
                "analysis_key": analysis_key,
                "content_hash": content_hash,
                "options_json": options_json,
                "summary": report_db.get_summary_by_analysis_key(analysis_key),
            }

    # lock 보유 상태로 다시 한번 캐시 체크 (race 회피)
    try:
        if report_db.has_summary(analysis_key):
            report_db.update_session(session_id, status="reused")
            return {
                "reused": True,
                "analysis_key": analysis_key,
                "content_hash": content_hash,
                "options_json": options_json,
                "summary": report_db.get_summary_by_analysis_key(analysis_key),
            }

        # 분석 실행 (기존 함수 wrap 만)
        schools = {p.stem: load_table(p) for p in sorted(file_paths, key=lambda x: x.name)}
        rows = build_summary_rows(schools)
        report_db.save_summary_batch(analysis_key, session_id, rows)
        report_db.update_session(session_id, status="done")
        return {
            "reused": False,
            "analysis_key": analysis_key,
            "content_hash": content_hash,
            "options_json": options_json,
            "summary": report_db.get_summary_by_analysis_key(analysis_key),
        }
    except Exception as exc:
        report_db.update_session(
            session_id,
            status="failed",
            error_message=str(exc)[:1000],
        )
        raise
    finally:
        report_db.release_analysis_lock(analysis_key, lock_owner)
