import logging
from typing import List, Optional

import pandas as pd
import yfinance as yf

from src.screening_config import get_screening_config

LOGGER = logging.getLogger(__name__)

def calculate_return(series: pd.Series, days: int) -> Optional[float]:
    """Calculate percentage return, or None when the requested history is invalid."""
    series = series.dropna()
    if len(series) <= days:
        return None
    latest_price = float(series.iloc[-1])
    past_price = float(series.iloc[-(days + 1)])
    if (
        not pd.notna(latest_price)
        or not pd.notna(past_price)
        or latest_price <= 0
        or past_price <= 0
    ):
        return None
    return float((latest_price - past_price) / past_price)


def get_outperforming_sectors(data: pd.DataFrame = None) -> List[str]:
    """Identify configured sector ETFs that beat the configured benchmark in each window."""
    config = get_screening_config()
    tickers = [config.benchmark_ticker] + list(config.sector_map)

    if data is None:
        try:
            LOGGER.info(
                "Fetching price data for %s and configured sector ETFs...",
                config.benchmark_ticker,
            )
            df = yf.download(
                tickers,
                period="1y",
                auto_adjust=True,
                progress=False,
                threads=False,
            )
            if isinstance(df.columns, pd.MultiIndex):
                if "Close" in df.columns.levels[0]:
                    df = df["Close"]
                else:
                    df = df.xs("Close", axis=1, level=0)
            data = df
        except Exception as exc:
            LOGGER.error("Failed to fetch ETF data from yfinance: %s", exc)
            return []

    if (
        data is None
        or data.empty
        or config.benchmark_ticker not in data.columns
    ):
        LOGGER.warning("Price data is missing or invalid.")
        return []

    spy_series = data[config.benchmark_ticker].dropna()
    spy_returns = {
        tf: calculate_return(spy_series, days)
        for tf, days in config.lookback_windows.items()
    }
    if any(value is None for value in spy_returns.values()):
        LOGGER.error("SPY history is insufficient or invalid; cannot compare sector returns.")
        return []

    benchmark_return_summary = ", ".join(
        f"{timeframe}: {value * 100:.2f}%"
        for timeframe, value in spy_returns.items()
    )
    LOGGER.info(
        "%s returns - %s",
        config.benchmark_ticker,
        benchmark_return_summary,
    )

    outperforming_sectors = []

    for etf, (sector_name, _) in config.sector_map.items():
        if etf not in data.columns:
            continue
        etf_series = data[etf].dropna()
        etf_returns = {
            tf: calculate_return(etf_series, days)
            for tf, days in config.lookback_windows.items()
        }
        if any(value is None for value in etf_returns.values()):
            LOGGER.warning(
                "%s (%s) has missing, invalid, or insufficient price history; excluding sector.",
                etf,
                sector_name,
            )
            continue

        # Check outperformance in ALL three timeframes simultaneously
        is_outperforming = all(
            etf_returns[tf] > spy_returns[tf]
            for tf in config.lookback_windows
        )

        return_summary = ", ".join(
            f"{timeframe}: {value * 100:.2f}%"
            for timeframe, value in etf_returns.items()
        )
        LOGGER.info(
            "%s (%s) returns - %s | Outperforming %s: %s",
            etf,
            sector_name,
            return_summary,
            config.benchmark_ticker,
            is_outperforming,
        )

        if is_outperforming:
            outperforming_sectors.append(sector_name)

    return outperforming_sectors
