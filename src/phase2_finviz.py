import logging
import re
from typing import List
from urllib.parse import parse_qs, urljoin, urlsplit

import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup

from src.screening_config import get_screening_config

LOGGER = logging.getLogger(__name__)

def _sector_token(sector: str) -> str:
    configured_sector = next(
        (
            finviz_token
            for sector_name, finviz_token in get_screening_config().sector_map.values()
            if sector_name == sector
        ),
        None,
    )
    return configured_sector or sector.lower().replace(" ", "")


def _finviz_filters(sector: str) -> str:
    """Build Finviz filters for the sector and available fundamental criteria."""
    selectors = get_screening_config().finviz_filters
    return ",".join((f"sec_{_sector_token(sector)}", *selectors))


def _fetch_tickers_via_url(sector: str) -> List[str]:
    """Query Finviz and extract tickers matching its supported fundamental filters."""
    filters = _finviz_filters(sector)
    tickers = []
    seen_tickers = set()
    seen_page_urls = set()
    next_page_url = None
    page_count = 0

    while True:
        try:
            if next_page_url:
                if next_page_url in seen_page_urls:
                    LOGGER.error(
                        "Finviz pagination loop detected for sector %s after %d pages.",
                        sector,
                        page_count,
                    )
                    return []
                seen_page_urls.add(next_page_url)
                response = requests.get(
                    next_page_url,
                    timeout=20,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
            else:
                response = requests.get(
                    "https://finviz.com/screener.ashx",
                    params={"v": "111", "f": filters, "o": "-marketcap"},
                    timeout=20,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
            response.raise_for_status()
        except requests.RequestException as exc:  # pragma: no cover - network failure path
            LOGGER.warning(
                "Finviz request failed for sector %s on page %d with filters %s "
                "(%s: %s); discarding partial results.",
                sector,
                page_count + 1,
                filters,
                type(exc).__name__,
                exc,
            )
            return []

        page_count += 1
        response_text = response.text or ""
        for ticker in _parse_finviz_tickers(response_text):
            if ticker not in seen_tickers:
                seen_tickers.add(ticker)
                tickers.append(ticker)

        soup = BeautifulSoup(response_text, "html.parser")
        next_link = soup.select_one("a.screener-pages.is-next[href]")
        next_page_url = (
            urljoin("https://finviz.com/", next_link["href"])
            if next_link is not None
            else None
        )
        if next_page_url is None:
            break

    if not tickers:
        response_text = response.text or ""
        soup = BeautifulSoup(response_text, "html.parser")
        page_title = soup.title.get_text(" ", strip=True) if soup.title else "(no title)"
        title = page_title[:160]
        visible_text = soup.get_text(" ", strip=True).casefold()
        page_text = f"{title.casefold()} {visible_text}"
        if any(
            marker in page_text
            for marker in ("captcha", "verify you are human", "access denied", "unusual traffic")
        ):
            page_type = "possible bot challenge or access denial"
        elif "no stocks match" in page_text or "no results" in page_text:
            page_type = "screener reports no matches"
        elif not response_text.strip():
            page_type = "empty response"
        else:
            page_type = "unrecognized page format"
        LOGGER.warning(
            "Finviz returned zero tickers for sector %s. Page type: %s; title: %r; "
            "HTTP %s; response length: %d; filters: %s.",
            sector,
            page_type,
            title,
            response.status_code,
            len(response_text),
            filters,
        )
    else:
        LOGGER.info(
            "Finviz returned %d unique tickers across %d page(s) for sector %s: %s",
            len(tickers),
            page_count,
            sector,
            ", ".join(tickers),
        )
    return tickers


def _parse_finviz_tickers(response_text: str) -> List[str]:
    """Extract ticker query parameters from legacy and current Finviz stock links."""
    soup = BeautifulSoup(response_text, "html.parser")
    tickers = []
    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "")
        parsed_url = urlsplit(href)
        route = parsed_url.path.rstrip("/").rsplit("/", 1)[-1].casefold()
        if route not in {"stock", "quote", "quote.ashx"}:
            continue
        ticker_values = parse_qs(parsed_url.query).get("t", [])
        if ticker_values and re.fullmatch(r"[A-Z0-9.\-]{1,10}", ticker_values[0]):
            tickers.append(ticker_values[0])
    if not tickers:
        tickers = re.findall(
            r"""data-boxover-ticker=["']([A-Z0-9.\-]{1,10})["']""",
            response_text,
        )
    return list(dict.fromkeys(tickers))


def _passes_price_and_moving_average_filters(ticker: str) -> bool:
    """Check exact price-to-52-week-range and simple-moving-average conditions."""
    config = get_screening_config()
    try:
        history = yf.Ticker(ticker).history(
            period="2y",
            interval="1d",
            auto_adjust=True,
        )
    except Exception as exc:  # pragma: no cover - data provider failure path
        LOGGER.warning(
            "Could not retrieve price history for %s (%s); excluding ticker.",
            ticker,
            type(exc).__name__,
        )
        return False

    if (
        history is None
        or history.empty
        or len(history) < config.price_history_days
        or not {"Close", "High", "Low"}.issubset(history.columns)
    ):
        LOGGER.warning("Insufficient OHLC history for %s; excluding ticker.", ticker)
        return False

    year = history.tail(config.price_history_days)
    closes = pd.to_numeric(year["Close"], errors="coerce").dropna()
    highs = pd.to_numeric(year["High"], errors="coerce").dropna()
    lows = pd.to_numeric(year["Low"], errors="coerce").dropna()
    if (
        len(closes) != config.price_history_days
        or len(highs) != config.price_history_days
        or len(lows) != config.price_history_days
        or len(history["Close"].dropna()) < config.sma_long_days
    ):
        LOGGER.warning("Incomplete OHLC history for %s; excluding ticker.", ticker)
        return False

    current_price = float(closes.iloc[-1])
    high_52w = float(highs.max())
    low_52w = float(lows.min())
    close_history = pd.to_numeric(history["Close"], errors="coerce").dropna()
    sma_short = float(close_history.tail(config.sma_short_days).mean())
    sma_long = float(close_history.tail(config.sma_long_days).mean())

    if low_52w <= 0 or high_52w <= 0:
        LOGGER.warning("Invalid 52-week high/low data for %s; excluding ticker.", ticker)
        return False

    checks = {
        "price above short moving average": current_price > sma_short,
        "price above configured 52-week-low distance": current_price
        >= low_52w * (1 + config.min_above_52w_low_pct),
        "price within configured 52-week-high distance": current_price
        >= high_52w * (1 - config.max_below_52w_high_pct),
        "short moving average above long moving average": sma_short > sma_long,
    }
    failed = [condition for condition, passes in checks.items() if not passes]
    if failed:
        LOGGER.info("%s excluded; failed price/average checks: %s.", ticker, ", ".join(failed))
        return False
    return True


def screen_stocks(sectors: List[str]) -> List[dict]:
    """Return unique passing ticker/sector pairs after local validations."""
    finviz_candidates: dict[str, str] = {}
    for sector in sectors or []:
        if not sector:
            continue
        for ticker in _fetch_tickers_via_url(sector):
            if ticker:
                finviz_candidates.setdefault(ticker, sector)

    LOGGER.info("Finviz returned %d unique fundamental candidates.", len(finviz_candidates))
    if not finviz_candidates:
        LOGGER.warning(
            "Phase 2 has no tickers to validate. Review the per-sector Finviz diagnostics "
            "to distinguish zero screener matches from blocked or changed responses."
        )
    passing_tickers = []
    for ticker, sector in finviz_candidates.items():
        if not _passes_price_and_moving_average_filters(ticker):
            LOGGER.info("%s rejected by technical price/moving-average checks.", ticker)
            continue
        passing_tickers.append({"ticker": ticker, "sector": sector})

    LOGGER.info(
        "%d/%d Finviz candidates passed the additional technical checks: %s",
        len(passing_tickers),
        len(finviz_candidates),
        ", ".join(item["ticker"] for item in passing_tickers) if passing_tickers else "(none)",
    )
    return passing_tickers
