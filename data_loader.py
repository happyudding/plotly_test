from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from config import (
    HI_LIMIT_ROW,
    LO_LIMIT_ROW,
    META_COLUMNS,
    N_META_COLUMNS,
    STUDENT_DATA_START_ROW,
    SUBJECT_NAME_ROW,
    UNIT_ROW,
)


@dataclass
class ExcelData:
    subjects: list[str]
    units: list[str]
    lo_limits: list[float]
    hi_limits: list[float]
    scores: pd.DataFrame
    meta: pd.DataFrame


def _parse_raw(raw: pd.DataFrame) -> ExcelData:
    subject_row = raw.iloc[SUBJECT_NAME_ROW, N_META_COLUMNS:]
    unit_row = raw.iloc[UNIT_ROW, N_META_COLUMNS:]
    lo_row = raw.iloc[LO_LIMIT_ROW, N_META_COLUMNS:]
    hi_row = raw.iloc[HI_LIMIT_ROW, N_META_COLUMNS:]

    subjects = [str(s) for s in subject_row.tolist()]
    units = [str(u) if pd.notna(u) else "" for u in unit_row.tolist()]
    lo_limits = pd.to_numeric(lo_row, errors="coerce").tolist()
    hi_limits = pd.to_numeric(hi_row, errors="coerce").tolist()

    student_block = raw.iloc[STUDENT_DATA_START_ROW:].reset_index(drop=True)

    meta = student_block.iloc[:, :N_META_COLUMNS].copy()
    meta.columns = META_COLUMNS

    scores = student_block.iloc[:, N_META_COLUMNS:].copy()
    scores.columns = range(len(subjects))

    return ExcelData(
        subjects=subjects,
        units=units,
        lo_limits=lo_limits,
        hi_limits=hi_limits,
        scores=scores,
        meta=meta,
    )


def load_table(path: Path) -> ExcelData:
    if path.suffix.lower() == ".csv":
        raw = pd.read_csv(path, header=None)
    else:
        raw = pd.read_excel(path, header=None)
    return _parse_raw(raw)
