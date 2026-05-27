from __future__ import annotations

import pandas as pd


def preprocess_file_to_df(file_path) -> pd.DataFrame:
    """전처리 진입점.

    preprocessor_fromhoney.csvfile_to_df 의 반환 구조를 받아서
    downstream code (iloc positional 접근) 가 기대하는 canonical 포맷으로 변환.
    """
    from analysis.preprocessor_fromhoney import csvfile_to_df
    df = csvfile_to_df(file_path)
    return _to_canonical(df)


def _to_canonical(df: pd.DataFrame) -> pd.DataFrame:
    """downstream 이 iloc[0, N_META:] 로 subject 를 읽으므로,
    row 0 위치에 컬럼명(또는 subject 이름) 이 들어가도록 통일하고
    df.columns 는 정수 인덱스로 reset.
    """
    if df.empty:
        return df

    cols = list(df.columns)

    # 케이스 1: 정수 컬럼 (header=None 스타일) → 이미 canonical
    if all(isinstance(c, int) for c in cols):
        return df

    # 케이스 2 / 3 판별: row 0 가 컬럼명과 동일한가?
    row0 = [str(v) for v in df.iloc[0].tolist()]
    col_strs = [str(c) for c in cols]

    if row0 == col_strs:
        # 케이스 2 (Structure A): row 0 가 이미 컬럼명 중복.
        # 컬럼 라벨만 정수로 reset 하면 downstream positional 접근과 정렬됨.
        out = df.copy()
        out.columns = range(len(cols))
        return out

    # 케이스 3 (Structure B): row 0 가 Units 등. 컬럼명을 row 0 로 prepend.
    header_row = pd.DataFrame([cols], columns=cols)
    out = pd.concat([header_row, df], ignore_index=True)
    out.columns = range(len(cols))
    return out
