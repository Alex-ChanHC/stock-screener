import pytest


@pytest.fixture(autouse=True)
def screening_settings(monkeypatch):
    settings = {
        "SCREENING_BENCHMARK_TICKER": "SPY",
        "SCREENING_SECTOR_ETFS": (
            "XLC|Communication Services|communicationservices;"
            "XLY|Consumer Cyclical|consumercyclical;"
            "XLP|Consumer Defensive|consumerdefensive;"
            "XLE|Energy|energy;"
            "XLF|Financial|financial;"
            "XLV|Healthcare|healthcare;"
            "XLI|Industrials|industrials;"
            "XLB|Basic Materials|basicmaterials;"
            "XLRE|Real Estate|realestate;"
            "XLK|Technology|technology;"
            "XLU|Utilities|utilities"
        ),
        "SCREENING_RETURN_WINDOWS": "P1:2,P2:3,P3:4",
        "SCREENING_FINVIZ_FILTERS": "filter_a,filter_b",
        "SCREENING_PRICE_HISTORY_DAYS": "10",
        "SCREENING_SMA_SHORT_DAYS": "50",
        "SCREENING_SMA_LONG_DAYS": "200",
        "SCREENING_MIN_ABOVE_52W_LOW_PCT": "0.5",
        "SCREENING_MAX_BELOW_52W_HIGH_PCT": "20",
        "SCREENING_SCTR_ETF_REPORT": "etf-SCTRI",
        "SCREENING_SCTR_BENCHMARK_TICKER": "VOO",
        "SCREENING_SCTR_STOCK_REPORTS": (
            "sp500-SCTRI|US Large-Cap;"
            "sp400-SCTRI|US Mid-Cap;"
            "sp600-SCTRI|US Small-Cap"
        ),
        "SCREENING_SCTR_LONG_RETURN_DAYS": "25",
        "SCREENING_SCTR_SHORT_RETURN_DAYS": "10",
        "SCREENING_SCTR_RSI_PERIOD": "5",
    }
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
