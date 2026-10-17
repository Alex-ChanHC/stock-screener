import logging
import sys

import requests

from src.phase2_finviz import _parse_finviz_tickers

LOGGER = logging.getLogger(__name__)


def main() -> int:
    try:
        response = requests.get(
            "https://finviz.com/screener.ashx",
            params={"v": "111", "f": "cap_largeover", "o": "-marketcap"},
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        LOGGER.error(
            "Finviz health check could not fetch the screener (%s).",
            type(exc).__name__,
        )
        return 1

    ticker_count = len(_parse_finviz_tickers(response.text or ""))
    if ticker_count == 0:
        LOGGER.error(
            "Finviz health check found no parseable tickers in the screener response."
        )
        return 1

    LOGGER.info("Finviz health check passed: extracted %d ticker links.", ticker_count)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(main())
