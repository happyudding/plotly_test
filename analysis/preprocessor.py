from __future__ import annotations

from pathlib import Path

import pandas as pd


def preprocess_file_to_df(file_path: str) -> pd.DataFrame:
    """파일을 표준 포맷의 DataFrame 으로 변환.

    표준 포맷 (header=None 으로 읽었을 때):
        Row 0:  [DUT, XCoord, YCoord, Bin, Serial, item1, item2, ...]
        Row 1:  [Units,       None, None, None, None, "V",  "mA", ...]
        Row 2:  [Lower Limit, None, None, None, None, 0.1,  5.0,  ...]
        Row 3:  [Upper Limit, None, None, None, None, 1.5,  20.0, ...]
        Row 6+: 측정 데이터

    병합 방법:
        본문을 아래처럼 교체하면 analyze / preview_items 양쪽에 자동 적용.
            from your_module import csvfiles_to_df
            return csvfiles_to_df(file_path)
    """
    path = Path(file_path)
    try:
        if path.suffix.lower() == ".xlsx":
            df = pd.read_excel(path, header=None)
        else:
            df = pd.read_csv(path, header=None)
    except Exception:
        return pd.DataFrame()

    return _ensure_serial_column(df)


def _ensure_serial_column(df: pd.DataFrame) -> pd.DataFrame:
    """Serial 컬럼이 4번 인덱스에 없으면 None 컬럼으로 삽입.

    옛 school.csv 같은 4-메타 포맷을 5-메타 표준 포맷으로 끌어올림.
    이미 새 포맷(Row 0 Col 4 == "Serial")이면 그대로 반환.
    """
    if df.empty or df.shape[1] < 5:
        return df
    if str(df.iat[0, 4]).strip().lower() == "serial":
        return df

    left = df.iloc[:, :4].reset_index(drop=True)
    right = df.iloc[:, 4:].reset_index(drop=True)
    serial = pd.DataFrame({"_s": [None] * len(df)})
    out = pd.concat([left, serial, right], axis=1, ignore_index=True)
    out.iat[0, 4] = "Serial"
    return out
