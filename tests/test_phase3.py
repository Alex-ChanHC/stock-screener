import pytest

from src.phase3_sctr import (
    _fetch_sctr_report,
    _rank_fallback_momentum,
    filter_by_sctr,
)
from src.screening_config import get_screening_config


def _config():
    return get_screening_config()


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200
        self.headers = {"Content-Type": "text/html"}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _fake_report(report):
    if report == _config().sctr_etf_report:
        return {"sctrs": [{"symbol": "VOO", "sctr": 55.0}], "time": "9 Oct 2026"}
    return {
        "sctrs": [
            {"symbol": "AAPL", "sctr": 70.0},
            {"symbol": "MSFT", "sctr": 70.0},
            {"symbol": "NVDA", "sctr": 70.0},
        ],
        "time": "9 Oct 2026",
    }


def test_stockcharts_sctr_reader_parses_public_report_rows(monkeypatch):
    requested = []

    def fake_get(url, **kwargs):
        requested.append((url, kwargs))
        return _FakeResponse({
            "sctrs": [
                {"symbol": "VOO", "sctr": 85.9},
                {"symbol": "INVALID", "sctr": 100.0},
            ],
            "time": "9 Oct 2026",
        })

    monkeypatch.setattr("src.phase3_sctr.requests.get", fake_get)

    scores, report_time = _fetch_sctr_report(_config().sctr_etf_report)

    assert scores == {"VOO": 85.9}
    assert report_time == "9 Oct 2026"
    assert requested[0][0].endswith(f"/data/{_config().sctr_etf_report}.json")
    assert requested[0][1]["headers"]["Referer"].endswith("/freecharts/sctr.html")


def test_filter_by_sctr_keeps_only_above_voo(monkeypatch):
    monkeypatch.setattr(
        "src.phase3_sctr._fetch_sctr_report",
        lambda report: (_fake_report(report)["sctrs"] and {
            row["symbol"]: row["sctr"] for row in _fake_report(report)["sctrs"]
        }, "9 Oct 2026"),
    )

    results, benchmark = filter_by_sctr([
        {"ticker": "AAPL", "sector": "Technology"},
        {"ticker": "MSFT", "sector": "Technology"},
        {"ticker": "NVDA", "sector": "Healthcare"},
    ])

    assert benchmark == {
        "status": "SCTR",
        "sctr": 55.0,
        "momentum_proxy": None,
        "proxy_candidate_count": 0,
        "proxy_unranked_count": 0,
        "sctr_unavailable_count": 0,
        "report_time": "9 Oct 2026",
        "etf_report_time": "9 Oct 2026",
        "stock_report_time": "9 Oct 2026",
        "stock_report_times": {
            "US Large-Cap": "9 Oct 2026",
            "US Mid-Cap": "9 Oct 2026",
            "US Small-Cap": "9 Oct 2026",
        },
        "stock_universes": ["US Large-Cap"],
    }
    assert {stock["ticker"] for stock in results} == {"AAPL", "MSFT", "NVDA"}
    assert all(stock["sctr"] > benchmark["sctr"] for stock in results)
    assert all("sector" in stock for stock in results)


def test_unavailable_candidate_sctr_uses_labeled_momentum_proxy(monkeypatch):
    def fake_fetch_report(report):
        if report == _config().sctr_etf_report:
            return {"VOO": 55.0}, "9 Oct 2026"
        return {"MSFT": 70.0}, "9 Oct 2026"

    monkeypatch.setattr("src.phase3_sctr._fetch_sctr_report", fake_fetch_report)
    monkeypatch.setattr(
        "src.phase3_sctr._rank_fallback_momentum",
        lambda tickers: {"VOO": 40.0, "AAPL": 80.0},
    )

    results, benchmark = filter_by_sctr(["AAPL", "MSFT"])

    assert benchmark == {
        "status": "SCTR",
        "sctr": 55.0,
        "momentum_proxy": 40.0,
        "proxy_candidate_count": 1,
        "proxy_unranked_count": 0,
        "sctr_unavailable_count": 1,
        "report_time": "9 Oct 2026",
        "etf_report_time": "9 Oct 2026",
        "stock_report_time": "9 Oct 2026",
        "stock_report_times": {
            "US Large-Cap": "9 Oct 2026",
            "US Mid-Cap": "9 Oct 2026",
            "US Small-Cap": "9 Oct 2026",
        },
        "stock_universes": ["US Large-Cap"],
    }
    assert results == [
        {
            "ticker": "MSFT",
            "sector": None,
            "sctr": 70.0,
            "score_type": "SCTR",
            "sctr_universe": "US Large-Cap",
        },
        {
            "ticker": "AAPL",
            "sector": None,
            "momentum_score": 80.0,
            "score_type": "momentum proxy",
        },
    ]


def test_fallback_momentum_is_equal_weighted_cross_sectional_percentile(monkeypatch):
    features = {
        "VOO": (0.0, 0.0, 50.0),
        "AAPL": (1.0, 1.0, 100.0),
        "MSFT": (-1.0, -1.0, 20.0),
    }
    monkeypatch.setattr(
        "src.phase3_sctr._fallback_momentum_features",
        lambda ticker: features[ticker],
    )

    scores = _rank_fallback_momentum(["VOO", "AAPL", "MSFT"])

    assert scores == {"VOO": 66.67, "AAPL": 100.0, "MSFT": 33.33}


def test_unavailable_voo_sctr_uses_proxy_for_entire_comparison(monkeypatch):
    fetched_tickers = []

    def fetch_report(report):
        fetched_tickers.append(report)
        return None, None

    monkeypatch.setattr("src.phase3_sctr._fetch_sctr_report", fetch_report)
    ranked_tickers = []

    def rank_momentum(tickers):
        ranked_tickers.extend(tickers)
        return {"VOO": 25.0, "AAPL": 75.0, "MSFT": 10.0}

    monkeypatch.setattr(
        "src.phase3_sctr._rank_fallback_momentum",
        rank_momentum,
    )

    results, benchmark = filter_by_sctr(["AAPL", "MSFT"])

    assert benchmark == {
        "status": "momentum proxy",
        "sctr": None,
        "momentum_proxy": 25.0,
        "proxy_candidate_count": 2,
        "proxy_unranked_count": 0,
        "sctr_unavailable_count": 2,
        "report_time": None,
        "etf_report_time": None,
        "stock_report_time": None,
    }
    assert fetched_tickers == [_config().sctr_etf_report]
    assert ranked_tickers == ["VOO", "AAPL", "MSFT"]
    assert results == [
        {
            "ticker": "AAPL",
            "sector": None,
            "momentum_score": 75.0,
            "score_type": "momentum proxy",
        }
    ]


def test_candidate_proxy_is_unranked_when_voo_proxy_is_missing(monkeypatch):
    def fake_fetch_report(report):
        if report == _config().sctr_etf_report:
            return {"VOO": 55.0}, "9 Oct 2026"
        return {}, "9 Oct 2026"

    monkeypatch.setattr("src.phase3_sctr._fetch_sctr_report", fake_fetch_report)
    monkeypatch.setattr(
        "src.phase3_sctr._rank_fallback_momentum",
        lambda tickers: {"AAPL": 80.0},
    )

    results, benchmark = filter_by_sctr(["AAPL"])

    assert results == []
    assert benchmark["proxy_candidate_count"] == 1
    assert benchmark["proxy_unranked_count"] == 1
    assert benchmark["etf_report_time"] == "9 Oct 2026"
    assert benchmark["stock_report_time"] == "9 Oct 2026"


def test_candidate_scores_are_found_in_any_stockcharts_equity_universe(monkeypatch):
    requested_reports = []

    def fake_fetch_report(report):
        requested_reports.append(report)
        if report == _config().sctr_etf_report:
            return {"VOO": 85.9}, "9 Oct 2026"
        if report == "sp400-SCTRI":
            return {"OSCR": 97.6, "ESTC": 98.2}, "9 Oct 2026"
        return {}, "9 Oct 2026"

    monkeypatch.setattr("src.phase3_sctr._fetch_sctr_report", fake_fetch_report)

    results, benchmark = filter_by_sctr(["OSCR", "ESTC"])

    assert requested_reports == [
        _config().sctr_etf_report,
        *[report for report, _ in _config().sctr_stock_reports],
    ]
    assert {item["ticker"] for item in results} == {"OSCR", "ESTC"}
    assert {item["sctr_universe"] for item in results} == {"US Mid-Cap"}
    assert benchmark["sctr_unavailable_count"] == 0


def test_unavailable_sctr_and_voo_proxy_fail_explicitly(monkeypatch):
    monkeypatch.setattr(
        "src.phase3_sctr._fetch_sctr_report",
        lambda _report: (None, None),
    )
    monkeypatch.setattr("src.phase3_sctr._rank_fallback_momentum", lambda _tickers: {})

    with pytest.raises(RuntimeError, match="cannot rank candidates"):
        filter_by_sctr(["AAPL"])


def test_voo_failure_skips_stock_report(monkeypatch):
    requested_reports = []
    monkeypatch.setattr(
        "src.phase3_sctr._fetch_sctr_report",
        lambda report: requested_reports.append(report) or (None, None),
    )
    monkeypatch.setattr(
        "src.phase3_sctr._rank_fallback_momentum",
        lambda tickers: {"VOO": 50.0, "AAPL": 80.0},
    )

    filter_by_sctr(["AAPL"])

    assert requested_reports == [_config().sctr_etf_report]
