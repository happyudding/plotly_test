import numpy as np
import pandas as pd

MAX_CDF_POINTS = 120


def to_numeric_clean(series: pd.Series) -> np.ndarray:
    return pd.to_numeric(series, errors="coerce").dropna().to_numpy()


def cumulative_distribution_full(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Full unique-value CDF with no downsampling."""
    if values.size == 0:
        return np.empty(0), np.empty(0)
    sorted_vals = np.sort(values)
    n = sorted_vals.size
    unique_vals, counts = np.unique(sorted_vals, return_counts=True)
    cum_pct = np.cumsum(counts) / n * 100.0
    return unique_vals, cum_pct


def downsample_cdf(
    xs: np.ndarray, ys: np.ndarray, max_points: int = MAX_CDF_POINTS
) -> tuple[np.ndarray, np.ndarray]:
    """Uniformly subsample an already-computed CDF to at most max_points."""
    if xs.size <= max_points:
        return xs, ys
    idx = np.unique(np.linspace(0, xs.size - 1, max_points).astype(int))
    return xs[idx], ys[idx]


def cumulative_distribution(
    values: np.ndarray, max_points: int = MAX_CDF_POINTS
) -> tuple[np.ndarray, np.ndarray]:
    """Compute downsampled CDF (default 120 points)."""
    xs, ys = cumulative_distribution_full(values)
    return downsample_cdf(xs, ys, max_points)
