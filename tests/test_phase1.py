import pandas as pd

from src.phase1_sector import calculate_return, get_outperforming_sectors


def test_get_outperforming_sectors_recognizes_sector_momentum():
    spy = pd.Series([100.0 + i * 0.05 for i in range(260)], dtype=float)
    tech = pd.Series([100.0 + i * 0.12 for i in range(260)], dtype=float)
    other = pd.Series([100.0 + i * 0.02 for i in range(260)], dtype=float)

    price_data = {"SPY": spy}
    for ticker in [
        "XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE", "XLK", "XLU"
    ]:
        price_data[ticker] = tech if ticker == "XLK" else other

    sectors = get_outperforming_sectors(pd.DataFrame(price_data))

    assert "Technology" in sectors
    assert "Communication Services" not in sectors


def test_missing_sector_history_is_excluded_without_sentinel_returns(caplog):
    spy = pd.Series([100.0 + i * 0.05 for i in range(260)], dtype=float)
    tech = pd.Series([100.0 + i * 0.12 for i in range(260)], dtype=float)
    price_data = {"SPY": spy}
    for ticker in [
        "XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE", "XLK", "XLU"
    ]:
        price_data[ticker] = tech
    price_data["XLB"] = pd.Series(dtype=float)

    sectors = get_outperforming_sectors(pd.DataFrame(price_data))

    assert "Basic Materials" not in sectors
    assert "-999" not in caplog.text
    assert "missing, invalid, or insufficient price history" in caplog.text


def test_calculate_return_rejects_nonpositive_or_insufficient_prices():
    assert calculate_return(pd.Series([0.0] * 130), 126) is None
    assert calculate_return(pd.Series([1.0] * 126), 126) is None


def test_yfinance_sector_download_disables_parallel_threads(monkeypatch):
    captured = {}
    data = pd.DataFrame({
        "SPY": [100.0] * 130,
        **{ticker: [100.0] * 130 for ticker in [
            "XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE", "XLK", "XLU"
        ]},
    })

    def fake_download(tickers, **kwargs):
        captured["tickers"] = tickers
        captured.update(kwargs)
        return data

    monkeypatch.setattr("src.phase1_sector.yf.download", fake_download)

    get_outperforming_sectors()

    assert captured["threads"] is False
