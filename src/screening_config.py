import os
from dataclasses import dataclass
from typing import Dict, Tuple

from dotenv import load_dotenv


def _load_private_settings() -> None:
    load_dotenv(".screening.env", override=False)


@dataclass(frozen=True)
class ScreeningConfig:
    benchmark_ticker: str
    sector_map: Dict[str, Tuple[str, str]]
    lookback_windows: Dict[str, int]
    finviz_filters: Tuple[str, ...]
    price_history_days: int
    sma_short_days: int
    sma_long_days: int
    min_above_52w_low_pct: float
    max_below_52w_high_pct: float
    sctr_etf_report: str
    sctr_benchmark_ticker: str
    sctr_stock_reports: Tuple[Tuple[str, str], ...]
    sctr_return_periods: Tuple[int, int]
    sctr_rsi_period: int


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required screening setting {name}; configure the private screening env file."
        )
    return value


def _parse_integer(name: str) -> int:
    try:
        value = int(_required(name))
    except ValueError as exc:
        raise RuntimeError(f"Screening setting {name} must be an integer.") from exc
    if value <= 0:
        raise RuntimeError(f"Screening setting {name} must be greater than zero.")
    return value


def _parse_sector_map(raw: str) -> Dict[str, Tuple[str, str]]:
    result = {}
    for entry in raw.split(";"):
        parts = [part.strip() for part in entry.split("|")]
        if len(parts) != 3 or not all(parts):
            raise RuntimeError(
                "SCREENING_SECTOR_ETFS entries must use ETF|sector name|Finviz token."
            )
        ticker, sector_name, finviz_token = parts
        if ticker in result:
            raise RuntimeError(f"Duplicate sector ETF in screening config: {ticker}.")
        result[ticker] = (sector_name, finviz_token)
    if not result:
        raise RuntimeError("SCREENING_SECTOR_ETFS must contain at least one entry.")
    return result


def _parse_lookback_windows(raw: str) -> Dict[str, int]:
    result = {}
    for entry in raw.split(","):
        try:
            label, days_text = (part.strip() for part in entry.split(":", 1))
            days = int(days_text)
        except ValueError as exc:
            raise RuntimeError(
                "SCREENING_RETURN_WINDOWS entries must use label:days."
            ) from exc
        if not label or days <= 0 or label in result:
            raise RuntimeError("SCREENING_RETURN_WINDOWS contains an invalid entry.")
        result[label] = days
    if not result:
        raise RuntimeError("SCREENING_RETURN_WINDOWS must contain at least one entry.")
    return result


def _parse_stock_reports(raw: str) -> Tuple[Tuple[str, str], ...]:
    reports = []
    for entry in raw.split(";"):
        parts = [part.strip() for part in entry.split("|")]
        if len(parts) != 2 or not all(parts):
            raise RuntimeError(
                "SCREENING_SCTR_STOCK_REPORTS entries must use report|universe name."
            )
        reports.append((parts[0], parts[1]))
    if not reports:
        raise RuntimeError("SCREENING_SCTR_STOCK_REPORTS must contain at least one entry.")
    return tuple(reports)


def get_screening_config() -> ScreeningConfig:
    _load_private_settings()
    filters = tuple(
        value.strip()
        for value in _required("SCREENING_FINVIZ_FILTERS").split(",")
        if value.strip()
    )
    if not filters:
        raise RuntimeError("SCREENING_FINVIZ_FILTERS must contain at least one selector.")

    try:
        low_pct = float(_required("SCREENING_MIN_ABOVE_52W_LOW_PCT"))
        high_pct = float(_required("SCREENING_MAX_BELOW_52W_HIGH_PCT"))
    except ValueError as exc:
        raise RuntimeError("52-week distance screening settings must be numeric percentages.") from exc
    if not 0 <= low_pct < 100 or not 0 <= high_pct < 100:
        raise RuntimeError("52-week distance settings must be percentages in [0, 100).")

    return ScreeningConfig(
        benchmark_ticker=_required("SCREENING_BENCHMARK_TICKER").upper(),
        sector_map=_parse_sector_map(_required("SCREENING_SECTOR_ETFS")),
        lookback_windows=_parse_lookback_windows(_required("SCREENING_RETURN_WINDOWS")),
        finviz_filters=filters,
        price_history_days=_parse_integer("SCREENING_PRICE_HISTORY_DAYS"),
        sma_short_days=_parse_integer("SCREENING_SMA_SHORT_DAYS"),
        sma_long_days=_parse_integer("SCREENING_SMA_LONG_DAYS"),
        min_above_52w_low_pct=low_pct / 100,
        max_below_52w_high_pct=high_pct / 100,
        sctr_etf_report=_required("SCREENING_SCTR_ETF_REPORT"),
        sctr_benchmark_ticker=_required("SCREENING_SCTR_BENCHMARK_TICKER").upper(),
        sctr_stock_reports=_parse_stock_reports(
            _required("SCREENING_SCTR_STOCK_REPORTS")
        ),
        sctr_return_periods=(
            _parse_integer("SCREENING_SCTR_LONG_RETURN_DAYS"),
            _parse_integer("SCREENING_SCTR_SHORT_RETURN_DAYS"),
        ),
        sctr_rsi_period=_parse_integer("SCREENING_SCTR_RSI_PERIOD"),
    )
