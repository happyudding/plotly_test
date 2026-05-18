import json
import math
from pathlib import Path

import pandas as pd

from config import DATASETS_DIR, META_COLUMNS

JSON_KWARGS = {"ensure_ascii": False, "separators": (",", ":")}
PASS_STUDENT_TYPE = "1"


def _json_safe(value):
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if pd.isna(value):
        return None
    return value


def _fmt_type(value):
    if pd.isna(value):
        return ""
    try:
        f = float(value)
        if f.is_integer():
            return str(int(f))
    except (TypeError, ValueError):
        pass
    return str(value)


def _fmt_num(value, digits=6):
    value = _json_safe(value)
    if value is None:
        return "N/A"
    return round(float(value), digits)


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, **JSON_KWARGS), encoding="utf-8")


def _subject_columns(table):
    return [str(s) for s in table.subjects]


def _combined_frames(schools):
    frames = []
    for source_name, table in schools.items():
        meta = table.meta.reset_index(drop=True).copy()
        scores = table.scores.reset_index(drop=True).copy()
        scores.columns = _subject_columns(table)
        frame = pd.concat([meta, scores], axis=1)
        frame.insert(0, "source_file", source_name)
        frame["student_type"] = frame["student_type"].map(_fmt_type)
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["source_file", *META_COLUMNS])
    return pd.concat(frames, ignore_index=True)


def _fail_mask_for_table(table):
    numeric = table.scores.apply(pd.to_numeric, errors="coerce")
    mask = pd.DataFrame(False, index=numeric.index, columns=numeric.columns)
    for idx, col in enumerate(numeric.columns):
        lo = table.lo_limits[idx] if idx < len(table.lo_limits) else None
        hi = table.hi_limits[idx] if idx < len(table.hi_limits) else None
        series = numeric[col]
        col_mask = pd.Series(False, index=series.index)
        if lo is not None and not pd.isna(lo):
            col_mask = col_mask | (series < float(lo))
        if hi is not None and not pd.isna(hi):
            col_mask = col_mask | (series > float(hi))
        mask[col] = col_mask.fillna(False)
    return mask


def _main_fail_subjects_by_type(schools):
    by_type = {}
    for _source_name, table in schools.items():
        mask = _fail_mask_for_table(table)
        student_types = table.meta["student_type"].map(_fmt_type)
        for student_type in sorted(student_types.unique()):
            if student_type == PASS_STUDENT_TYPE:
                continue
            rows = student_types == student_type
            counts = mask.loc[rows].sum(axis=0)
            if counts.empty or int(counts.max()) <= 0:
                continue
            sid = int(counts.idxmax())
            item = {
                "subject_id": sid,
                "subject": table.subjects[sid],
                "fail_count": int(counts.max()),
            }
            current = by_type.get(student_type)
            if current is None or item["fail_count"] > current["fail_count"]:
                by_type[student_type] = item
    return by_type


def _build_yield(schools):
    combined = _combined_frames(schools)
    total = len(combined)
    main_fail = _main_fail_subjects_by_type(schools)
    rows = []
    if total == 0:
        return rows
    counts = combined["student_type"].map(_fmt_type).value_counts(dropna=False)
    for student_type, count in counts.sort_index(key=lambda s: s.map(lambda x: float(x) if str(x).replace(".", "", 1).isdigit() else float("inf"))).items():
        rows.append({
            "student_type": student_type,
            "count": int(count),
            "portion (%)": round(int(count) / total * 100.0, 3),
            "Main Fail subject": "Pass" if student_type == PASS_STUDENT_TYPE else main_fail.get(student_type, {}).get("subject", "N/A"),
        })
    return rows


def _build_cpk(schools):
    rows = []
    first = next(iter(schools.values()))
    for idx, subject in enumerate(first.subjects):
        values = []
        for table in schools.values():
            values.append(pd.to_numeric(table.scores.iloc[:, idx], errors="coerce"))
        series = pd.concat(values, ignore_index=True).dropna()
        lo = first.lo_limits[idx] if idx < len(first.lo_limits) else None
        hi = first.hi_limits[idx] if idx < len(first.hi_limits) else None
        stdev = series.std(ddof=1) if len(series) > 1 else float("nan")
        avg = series.mean() if len(series) else float("nan")
        can_calc = (
            len(series) > 1 and stdev and not pd.isna(stdev) and stdev != 0
            and lo is not None and hi is not None and not pd.isna(lo) and not pd.isna(hi)
        )
        if can_calc:
            cp = (float(hi) - float(lo)) / (6.0 * stdev)
            cpl = (avg - float(lo)) / (3.0 * stdev)
            cpu = (float(hi) - avg) / (3.0 * stdev)
            cpk = min(cpl, cpu)
        else:
            cp = cpl = cpu = cpk = None
        rows.append({
            "subject_id": idx,
            "subject": subject,
            "unit": first.units[idx] if idx < len(first.units) else "",
            "lo_limit": _fmt_num(lo),
            "hi_limit": _fmt_num(hi),
            "min": _fmt_num(series.min() if len(series) else None),
            "max": _fmt_num(series.max() if len(series) else None),
            "average": _fmt_num(avg),
            "stdev": _fmt_num(stdev),
            "cp": _fmt_num(cp),
            "cpl": _fmt_num(cpl),
            "cpu": _fmt_num(cpu),
            "cpk": _fmt_num(cpk),
        })
    return rows


def _build_fail_items(schools):
    total_rows = sum(len(t.meta) for t in schools.values())
    summary = {}
    records = []
    for source_name, table in schools.items():
        mask = _fail_mask_for_table(table)
        student_types = table.meta["student_type"].map(_fmt_type)
        for sid, subject in enumerate(table.subjects):
            fail_rows = mask.iloc[:, sid]
            fail_count = int(fail_rows.sum())
            if fail_count > 0:
                current = summary.setdefault(sid, {
                    "subject_id": sid,
                    "subject": subject,
                    "fail_count": 0,
                    "fail_portion (%)": 0.0,
                    "student_types": {},
                })
                current["fail_count"] += fail_count
                type_counts = student_types[fail_rows].value_counts()
                for student_type, count in type_counts.items():
                    current["student_types"][student_type] = current["student_types"].get(student_type, 0) + int(count)
        fail_any = mask.any(axis=1)
        for ridx in list(mask.index[fail_any]):
            failed_subject_ids = [int(sid) for sid, failed in mask.loc[ridx].items() if bool(failed)]
            failed_subjects = [table.subjects[sid] for sid in failed_subject_ids]
            row = {
                "source_file": source_name,
                **{col: _json_safe(table.meta.iloc[ridx][col]) for col in META_COLUMNS},
                "student_type": student_types.iloc[ridx],
                "fail_count": len(failed_subjects),
                "fail_subjects": ", ".join(failed_subjects),
            }
            records.append(row)
    summaries = []
    for item in summary.values():
        item["fail_portion (%)"] = round(item["fail_count"] / total_rows * 100.0, 3) if total_rows else 0.0
        item["student_types"] = ", ".join(f"{k}:{v}" for k, v in sorted(item["student_types"].items()))
        summaries.append(item)
    summaries.sort(key=lambda x: (-x["fail_portion (%)"], -x["fail_count"], x["subject"]))
    return {"summary": summaries, "records": records}


def build_table_artifacts(dataset_id, schools):
    out_dir = DATASETS_DIR / dataset_id
    tables_dir = out_dir / "tables"
    combined = _combined_frames(schools)
    first = next(iter(schools.values()))
    meta = {
        "dataset_id": dataset_id,
        "sources": list(schools.keys()),
        "row_count": int(len(combined)),
        "subjects": [
            {
                "subject_id": idx,
                "subject": subject,
                "unit": first.units[idx] if idx < len(first.units) else "",
                "lo_limit": _json_safe(first.lo_limits[idx] if idx < len(first.lo_limits) else None),
                "hi_limit": _json_safe(first.hi_limits[idx] if idx < len(first.hi_limits) else None),
            }
            for idx, subject in enumerate(first.subjects)
        ],
        "raw_columns": combined.columns.tolist(),
    }
    _write_json(tables_dir / "meta.json", meta)
    _write_json(tables_dir / "yield.json", _build_yield(schools))
    _write_json(tables_dir / "cpk.json", _build_cpk(schools))
    _write_json(tables_dir / "fail_items.json", _build_fail_items(schools))
    return {"tables_dir": str(tables_dir), "row_count": meta["row_count"]}


def load_raw_page(dataset_id, page_current=0, page_size=25, sort_by=None, filter_query=""):
    input_dir = DATASETS_DIR / dataset_id / "input"
    from data_loader import load_table

    schools = {p.stem: load_table(p) for p in sorted(input_dir.glob("*.csv"))}
    df = _combined_frames(schools)
    df = _apply_filter(df, filter_query or "")
    if sort_by:
        for sort in reversed(sort_by):
            col = sort.get("column_id")
            if col in df.columns:
                df = df.sort_values(col, ascending=sort.get("direction") != "desc", kind="mergesort")
    total = len(df)
    start = int(page_current or 0) * int(page_size or 25)
    end = start + int(page_size or 25)
    page = df.iloc[start:end].where(pd.notna(df), None)
    return page.to_dict("records"), total, df.columns.tolist()


def _apply_filter(df, filter_query):
    if not filter_query:
        return df
    filtered = df
    for expr in filter_query.split(" && "):
        if " contains " in expr:
            left, right = expr.split(" contains ", 1)
            col = left.strip().strip("{}")
            val = right.strip().strip("'\"")
            if col in filtered.columns:
                filtered = filtered[filtered[col].astype(str).str.contains(val, case=False, na=False)]
        elif " eq " in expr:
            left, right = expr.split(" eq ", 1)
            col = left.strip().strip("{}")
            val = right.strip().strip("'\"")
            if col in filtered.columns:
                filtered = filtered[filtered[col].astype(str) == val]
    return filtered


def read_table_json(dataset_id, name):
    path = DATASETS_DIR / dataset_id / "tables" / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))

