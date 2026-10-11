import logging
import math
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple, Union

import pandas as pd
import requests
import yfinance as yf

from src.screening_config import get_screening_config

LOGGER = logging.getLogger(__name__)
STOCKCHARTS_REPORT_URL = "https://stockcharts.com/data/{report}.json"


def _calculate_rsi(series: pd.Series, period: int = 14) -> float:
    """Compute the 14-period RSI for the provided series."""
    if len(series) < period + 1:
        return 50.0
    deltas = series.pct_change().dropna()
    gains = deltas.where(deltas > 0, 0.0)
    losses = (-deltas).where(deltas < 0, 0.0)
    avg_gain = gains.rolling(window=period, min_periods=period).mean().iloc[-1]
    avg_loss = losses.rolling(window=period, min_periods=period).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _fallback_momentum_features(ticker: str) -> Optional[Tuple[float, float, float]]:
    """Return 12-month return, 6-month return, and 14-day RSI for fallback ranking."""
    config = get_screening_config()
    try:
        history = yf.download(
            ticker,
            period="2y",
            interval="1d",
            auto_adjust=True,
            progress=False,
            actions=False,
        )
    except Exception as exc:  # pragma: no cover - network issues fallback
        LOGGER.warning("Unable to fetch fallback momentum data for %s (%s).", ticker, type(exc).__name__)
        return None

    if history is None or history.empty:
        LOGGER.warning("No fallback momentum data available for %s.", ticker)
        return None

    close_data = history["Close"]
    if isinstance(close_data, pd.DataFrame):
        if ticker in close_data.columns:
            close_data = close_data[ticker]
        elif len(close_data.columns) == 1:
            close_data = close_data.iloc[:, 0]
        else:
            LOGGER.warning("Ambiguous fallback close-price data for %s.", ticker)
            return None

    close = pd.Series(close_data).dropna()
    long_period, short_period = config.sctr_return_periods
    if len(close) <= long_period:
        LOGGER.warning("Insufficient history for fallback momentum ranking of %s.", ticker)
        return None

    latest = float(close.iloc[-1])
    prior_short = float(close.iloc[-(short_period + 1)])
    prior_long = float(close.iloc[-(long_period + 1)])
    if latest <= 0 or prior_short <= 0 or prior_long <= 0:
        LOGGER.warning("Invalid prices for fallback momentum ranking of %s.", ticker)
        return None

    return (
        latest / prior_long - 1,
        latest / prior_short - 1,
        _calculate_rsi(close, period=config.sctr_rsi_period),
    )


def _rank_fallback_momentum(tickers: List[str]) -> dict[str, float]:
    """Rank fallback momentum features as equal-weighted cross-sectional percentiles."""
    features = {}
    for ticker in tickers:
        result = _fallback_momentum_features(ticker)
        if result is not None:
            features[ticker] = result

    if not features:
        return {}

    feature_frame = pd.DataFrame.from_dict(
        features,
        orient="index",
        columns=["12-month return", "6-month return", "14-day RSI"],
    )
    percentiles = feature_frame.rank(method="average", pct=True) * 100
    scores = percentiles.mean(axis=1)
    LOGGER.info(
        "Calculated momentum-proxy features for %d/%d requested symbols.",
        len(scores),
        len(tickers),
    )
    return {ticker: round(float(score), 2) for ticker, score in scores.items()}


def _fetch_sctr_report(report: str) -> Tuple[Optional[Dict[str, float]], Optional[str]]:
    """Fetch the same JSON data feed used by StockCharts' public SCTR report page."""
    url = STOCKCHARTS_REPORT_URL.format(report=report)
    try:
        response = requests.get(
            url,
            params={"r": int(datetime.now(timezone.utc).timestamp() * 1000)},
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://stockcharts.com/freecharts/sctr.html",
                "Accept": "application/json",
            },
            timeout=25,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        LOGGER.warning(
            "StockCharts SCTR report %s request failed (%s): %s",
            report,
            type(exc).__name__,
            exc,
        )
        return None, None

    if not isinstance(payload, dict) or not isinstance(payload.get("sctrs"), list):
        LOGGER.warning(
            "StockCharts SCTR report %s returned an unexpected JSON structure.",
            report,
        )
        return None, None

    scores: Dict[str, float] = {}
    for row in payload["sctrs"]:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("symbol", "")).strip().upper()
        try:
            score = float(row["sctr"])
        except (KeyError, TypeError, ValueError):
            continue
        if ticker and math.isfinite(score) and 0 <= score <= 99.9:
            scores[ticker] = score

    report_time = str(payload.get("time") or "").strip() or None
    LOGGER.info(
        "Loaded StockCharts SCTR report %s: %d symbols, report time=%s.",
        report,
        len(scores),
        report_time or "unknown",
    )
    if not scores:
        LOGGER.warning("StockCharts SCTR report %s contained no valid scores.", report)
        return None, report_time
    return scores, report_time


def filter_by_sctr(
    candidates: Iterable[Union[str, dict]],
) -> Tuple[List[dict], dict]:
    """Filter against VOO SCTR, using labeled momentum percentiles when needed."""
    seen = set()
    unique_candidates: List[str] = []
    candidate_sectors: Dict[str, Optional[str]] = {}
    for candidate in candidates or []:
        if isinstance(candidate, dict):
            ticker = str(candidate.get("ticker", "")).strip().upper()
            sector = candidate.get("sector")
            sector = str(sector).strip() if sector else None
        else:
            ticker = str(candidate).strip().upper()
            sector = None
        if ticker and ticker not in seen:
            seen.add(ticker)
            unique_candidates.append(ticker)
            candidate_sectors[ticker] = sector

    if not unique_candidates:
        return [], {"status": "not checked", "sctr": None, "momentum_proxy": None}

    config = get_screening_config()
    benchmark_ticker = config.sctr_benchmark_ticker
    etf_scores, etf_report_time = _fetch_sctr_report(config.sctr_etf_report)
    voo_sctr = (
        etf_scores.get(benchmark_ticker) if etf_scores is not None else None
    )
    passing: List[dict] = []
    if voo_sctr is None:
        LOGGER.warning(
            "VOO SCTR unavailable from the StockCharts US ETF report; skipping the "
            "stock report and using momentum percentiles for all %d candidates.",
            len(unique_candidates),
        )
        fallback_scores = _rank_fallback_momentum(
            [benchmark_ticker] + unique_candidates
        )
        fallback_voo_score = fallback_scores.get(benchmark_ticker)
        if fallback_voo_score is None:
            raise RuntimeError(
                "Unable to retrieve VOO SCTR or calculate its momentum proxy; cannot rank candidates."
            )
        LOGGER.info(
            "VOO SCTR unavailable; momentum-proxy benchmark is %.2f.",
            fallback_voo_score,
        )
        for ticker in unique_candidates:
            score = fallback_scores.get(ticker)
            if score is not None and score > fallback_voo_score:
                passing.append({
                    "ticker": ticker,
                    "sector": candidate_sectors[ticker],
                    "momentum_score": score,
                    "score_type": "momentum proxy",
                })
        benchmark = {
            "status": "momentum proxy",
            "sctr": None,
            "momentum_proxy": fallback_voo_score,
            "proxy_candidate_count": len(unique_candidates),
            "proxy_unranked_count": sum(
                ticker not in fallback_scores for ticker in unique_candidates
            ),
            "sctr_unavailable_count": len(unique_candidates),
            "report_time": etf_report_time,
            "etf_report_time": etf_report_time,
            "stock_report_time": None,
        }
    else:
        LOGGER.info(
            "%s SCTR is %.2f from the configured ETF report (time=%s).",
            benchmark_ticker,
            voo_sctr,
            etf_report_time or "unknown",
        )
        stock_scores: Dict[str, float] = {}
        stock_report_times: Dict[str, Optional[str]] = {}
        ticker_universes: Dict[str, str] = {}
        for report, universe in config.sctr_stock_reports:
            report_scores, report_time = _fetch_sctr_report(report)
            stock_report_times[universe] = report_time
            for ticker, score in (report_scores or {}).items():
                if ticker not in stock_scores:
                    stock_scores[ticker] = score
                    ticker_universes[ticker] = universe

        successful_report_times = [
            report_time
            for report_time in stock_report_times.values()
            if report_time is not None
        ]
        stock_report_time = (
            successful_report_times[0]
            if successful_report_times
            and all(
                report_time == successful_report_times[0]
                for report_time in successful_report_times
            )
            else None
        )
        candidate_sctrs = {
            ticker: stock_scores.get(ticker)
            for ticker in unique_candidates
        }
        available_candidate_sctrs = sum(
            score is not None for score in candidate_sctrs.values()
        )
        LOGGER.info(
            "Candidate SCTR coverage: %d/%d found in US Large-, Mid-, or Small-Cap "
            "reports; %d require fallback.",
            available_candidate_sctrs,
            len(unique_candidates),
            len(unique_candidates) - available_candidate_sctrs,
        )
        if available_candidate_sctrs:
            universe_counts: Dict[str, int] = {}
            for ticker in unique_candidates:
                universe = ticker_universes.get(ticker)
                if universe:
                    universe_counts[universe] = universe_counts.get(universe, 0) + 1
            LOGGER.info("Candidate SCTR report coverage by universe: %s", universe_counts)

        for ticker, score in candidate_sctrs.items():
            if score is not None and score > voo_sctr:
                passing.append({
                    "ticker": ticker,
                    "sector": candidate_sectors[ticker],
                    "sctr": round(float(score), 2),
                    "score_type": "SCTR",
                    "sctr_universe": ticker_universes[ticker],
                })

        unavailable_candidates = [
            ticker for ticker, score in candidate_sctrs.items() if score is None
        ]
        if unavailable_candidates:
            LOGGER.warning(
                "No StockCharts US equity-universe SCTR row for candidates: %s",
                ", ".join(unavailable_candidates),
            )
        fallback_voo_score = None
        fallback_scores: Dict[str, float] = {}
        if unavailable_candidates:
            fallback_tickers = [benchmark_ticker] + unavailable_candidates
            fallback_scores = _rank_fallback_momentum(fallback_tickers)
            fallback_voo_score = fallback_scores.get(benchmark_ticker)
            if fallback_voo_score is None:
                LOGGER.warning(
                    "Unable to calculate VOO momentum proxy; skipping %d candidates "
                    "whose SCTR was unavailable.",
                    len(unavailable_candidates),
                )
            else:
                for ticker in unavailable_candidates:
                    score = fallback_scores.get(ticker)
                    if score is not None and score > fallback_voo_score:
                        passing.append({
                            "ticker": ticker,
                            "sector": candidate_sectors[ticker],
                            "momentum_score": score,
                            "score_type": "momentum proxy",
                        })
        benchmark = {
            "status": "SCTR",
            "sctr": float(voo_sctr),
            "momentum_proxy": fallback_voo_score,
            "proxy_candidate_count": sum(
                ticker in fallback_scores for ticker in unavailable_candidates
            ),
            "proxy_unranked_count": (
                len(unavailable_candidates)
                if fallback_voo_score is None
                else sum(ticker not in fallback_scores for ticker in unavailable_candidates)
            ),
            "sctr_unavailable_count": len(unavailable_candidates),
            "report_time": stock_report_time or etf_report_time,
            "etf_report_time": etf_report_time,
            "stock_report_time": stock_report_time,
            "stock_report_times": stock_report_times,
            "stock_universes": list(dict.fromkeys(ticker_universes.values())),
        }

    passing.sort(
        key=lambda item: (
            item.get("score_type") == "momentum proxy",
            -float(item.get("sctr", item.get("momentum_score", 0.0))),
        )
    )
    LOGGER.info(
        "SCTR stage retained %d/%d candidates: %d actual SCTR and %d momentum proxy.",
        len(passing),
        len(unique_candidates),
        sum(item.get("score_type") == "SCTR" for item in passing),
        sum(item.get("score_type") == "momentum proxy" for item in passing),
    )
    return passing, benchmark
