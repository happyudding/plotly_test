from pathlib import Path

import pandas as pd

GFORM = "GFORM"

STDF_SUFFIXES = {".std", ".stdf", ".xz"}


def parse_stdf_to_csv(file_path):
    # TODO: STDF 파싱 구현 예정
    return pd.DataFrame()


def drm_file_open_to_dataframe(file_path):
    # TODO: DRM 보호 파일 열기 구현 예정
    return pd.DataFrame()


def get_df_fileindex_from_df_original_csv(df, drm_flag):
    # TODO: df에서 file_index 추출 구현 예정
    return df, GFORM


def reprobing_data_process(data_csv):
    # TODO: reprobing 데이터 처리 구현 예정
    return data_csv


def df_read_csv_files(file_path):
    path = Path(file_path)
    try:
        if path.suffix.lower() == ".xlsx":
            df = pd.read_excel(path, header=None)
        else:
            df = pd.read_csv(path, header=None)
        return df, True
    except Exception:
        return None, False


def csvfile_to_df(file_path):
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix in STDF_SUFFIXES:
        df = parse_stdf_to_csv(file_path)
        drm_flag = True
    else:
        df, drm_flag = df_read_csv_files(file_path)
        if not drm_flag:
            df = drm_file_open_to_dataframe(file_path)

    data_csv, file_index = get_df_fileindex_from_df_original_csv(df, drm_flag)

    if file_index == GFORM:
        data = data_csv
    else:
        data = reprobing_data_process(data_csv)

    return data
