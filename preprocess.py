import numpy as np
import pandas as pd


def to_numeric_clean(series: pd.Series) -> np.ndarray:
    return pd.to_numeric(series, errors="coerce").dropna().to_numpy()


def cumulative_distribution(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if values.size == 0:
        return np.empty(0), np.empty(0)
    sorted_vals = np.sort(values)
    n = sorted_vals.size
    unique_vals, counts = np.unique(sorted_vals, return_counts=True)
    cum_pct = np.cumsum(counts) / n * 100.0
    return unique_vals, cum_pct
