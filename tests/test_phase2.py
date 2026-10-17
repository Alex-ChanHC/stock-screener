import pandas as pd
import pytest

from src import phase2_finviz
from src.screening_config import get_screening_config


def test_finviz_filter_codes_match_supported_fundamental_rules():
    filters = phase2_finviz._finviz_filters("Communication Services").split(",")

    assert "sec_communicationservices" in filters
    assert tuple(filters[1:]) == get_screening_config().finviz_filters


def test_finviz_ticker_parser_handles_html_encoded_links_and_deduplicates():
    html = """
    <table>
      <tr><td><a href="/quote.ashx?t=NVDA&amp;ty= c&amp;p=d&amp;b=1">NVDA</a></td></tr>
      <tr><td><a href="/quote.ashx?t=NVDA">NVDA</a></td></tr>
      <tr><td><a href="stock?t=LLY&amp;ty=c&amp;p=d&amp;b=1">LLY</a></td></tr>
      <tr><td><a href="/quote?t=CVX&amp;b=1">CVX</a></td></tr>
      <tr><td><a href="/quote.ashx?t=BRK.B">BRK.B</a></td></tr>
    </table>
    """

    assert phase2_finviz._parse_finviz_tickers(html) == ["NVDA", "LLY", "CVX", "BRK.B"]


def test_finviz_empty_response_logs_diagnostic_page_details(monkeypatch, caplog):
    class FakeResponse:
        text = "<html><title>Access Denied</title><body>Verify you are human</body></html>"
        status_code = 200

        def raise_for_status(self):
            return None

    monkeypatch.setattr(phase2_finviz.requests, "get", lambda *_args, **_kwargs: FakeResponse())

    assert phase2_finviz._fetch_tickers_via_url("Technology") == []
    assert "possible bot challenge or access denial" in caplog.text
    assert "Access Denied" in caplog.text
    assert "response length:" in caplog.text
    assert "sec_technology" in caplog.text


def test_finviz_valid_page_is_not_mistaken_for_bot_challenge(monkeypatch, caplog):
    class FakeResponse:
        text = (
            "<html><title>Stock Screener</title>"
            "<script>const robotChallengeEnabled = false;</script>"
            '<a href="stock?t=LLY&amp;ty=c&amp;p=d&amp;b=1">LLY</a></html>'
        )
        status_code = 200

        def raise_for_status(self):
            return None

    monkeypatch.setattr(phase2_finviz.requests, "get", lambda *_args, **_kwargs: FakeResponse())
    caplog.set_level("INFO", logger="src.phase2_finviz")

    assert phase2_finviz._fetch_tickers_via_url("Healthcare") == ["LLY"]
    assert "possible bot challenge" not in caplog.text
    assert "Finviz returned 1 unique tickers" in caplog.text


def test_finviz_ticker_fetcher_collects_all_pages_and_deduplicates(monkeypatch, caplog):
    class FakeResponse:
        status_code = 200

        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            return None

    pages = [
        FakeResponse(
            '<a href="stock?t=AAA">AAA</a>'
            '<a class="screener-pages is-next" href="screener?v=111&amp;r=21">next</a>'
        ),
        FakeResponse('<a href="stock?t=AAA">AAA</a><a href="stock?t=BBB">BBB</a>'),
    ]
    requested_urls = []

    def fake_get(url, **_kwargs):
        requested_urls.append(url)
        return pages.pop(0)

    monkeypatch.setattr(phase2_finviz.requests, "get", fake_get)
    caplog.set_level("INFO", logger="src.phase2_finviz")

    assert phase2_finviz._fetch_tickers_via_url("Technology") == ["AAA", "BBB"]
    assert len(requested_urls) == 2
    assert "across 2 page(s)" in caplog.text


def test_technical_filters_use_exact_price_and_moving_average_conditions(monkeypatch):
    index = pd.date_range("2024-01-01", periods=520, freq="D")
    closes = pd.Series([100.0 + value * 0.2 for value in range(520)], index=index)
    history = pd.DataFrame(
        {"Close": closes, "High": closes + 1.0, "Low": closes - 1.0},
        index=index,
    )
    monkeypatch.setattr(
        phase2_finviz.yf,
        "Ticker",
        lambda _ticker: type("FakeTicker", (), {"history": lambda *_args, **_kwargs: history})(),
    )

    assert phase2_finviz._passes_price_and_moving_average_filters("TEST") is True


@pytest.mark.parametrize("latest_close", [200.0, 198.0], ids=["flat", "falling"])
def test_technical_filters_reject_non_rising_50_day_average(
    monkeypatch, caplog, latest_close
):
    caplog.set_level("INFO", logger="src.phase2_finviz")
    index = pd.date_range("2024-01-01", periods=520, freq="D")
    closes = pd.Series(
        [100.0] * 370 + [200.0] * 100 + [190.0] * 49 + [latest_close],
        index=index,
    )
    history = pd.DataFrame(
        {"Close": closes, "High": closes + 1.0, "Low": closes - 1.0},
    )
    monkeypatch.setattr(
        phase2_finviz.yf,
        "Ticker",
        lambda _ticker: type("FakeTicker", (), {"history": lambda *_args, **_kwargs: history})(),
    )

    assert phase2_finviz._passes_price_and_moving_average_filters("TEST") is False
    assert "short moving average rising" in caplog.text


def test_technical_filters_reject_price_more_than_25_percent_below_high(monkeypatch):
    index = pd.date_range("2024-01-01", periods=520, freq="D")
    closes = pd.Series([100.0 + value * 0.2 for value in range(520)], index=index)
    closes.iloc[-1] = 100.0
    history = pd.DataFrame(
        {"Close": closes, "High": closes + 1.0, "Low": closes - 1.0},
        index=index,
    )
    monkeypatch.setattr(
        phase2_finviz.yf,
        "Ticker",
        lambda _ticker: type("FakeTicker", (), {"history": lambda *_args, **_kwargs: history})(),
    )

    assert phase2_finviz._passes_price_and_moving_average_filters("TEST") is False


def test_screen_stocks_deduplicates_sectors_and_applies_technical_checks(monkeypatch):
    monkeypatch.setattr(
        phase2_finviz,
        "_fetch_tickers_via_url",
        lambda _sector: ["AAA", "BBB"],
    )
    validated = []

    def pass_validation(ticker):
        validated.append(ticker)
        return ticker == "AAA"

    monkeypatch.setattr(
        phase2_finviz,
        "_passes_price_and_moving_average_filters",
        pass_validation,
    )

    assert phase2_finviz.screen_stocks(["Technology", "Healthcare"]) == [
        {"ticker": "AAA", "sector": "Technology"}
    ]
    assert validated == ["AAA", "BBB"]
