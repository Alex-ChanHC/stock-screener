import pytest

from src import notifier


class _FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"id": "test-message-id", "event": "message", "ok": True}


@pytest.mark.parametrize(
    ("provider", "environment", "expected_url"),
    [
        ("telegram", {"TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "123"}, "sendMessage"),
        ("ntfy", {"NTFY_TOPIC": "private-topic"}, "https://ntfy.sh/private-topic"),
        ("discord", {"DISCORD_WEBHOOK_URL": "https://discord.test/webhook"}, "https://discord.test/webhook"),
    ],
)
def test_send_alert_routes_to_selected_provider(monkeypatch, provider, environment, expected_url):
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "NTFY_TOPIC", "DISCORD_WEBHOOK_URL"):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    requests_made = []

    def fake_post(url, **kwargs):
        requests_made.append((url, kwargs))
        return _FakeResponse()

    monkeypatch.setattr(notifier.requests, "post", fake_post)

    sent = notifier.send_alert(provider, [{"ticker": "AAPL", "sctr": 75.0}], 50.0, ["Technology"])

    assert sent is True
    assert len(requests_made) == 1
    assert expected_url in requests_made[0][0]


def test_send_alert_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unsupported notification provider"):
        notifier.send_alert("email", [], 0.0, [])


def test_discord_selected_without_webhook_fails(monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)

    assert notifier.send_alert("discord", [], 0.0, []) is False


def test_ntfy_logs_server_acceptance_not_delivery(monkeypatch, caplog):
    monkeypatch.setenv("NTFY_TOPIC", "private-topic")
    monkeypatch.setattr(notifier.requests, "post", lambda *_args, **_kwargs: _FakeResponse())
    caplog.set_level("INFO", logger="src.notifier")

    sent = notifier.send_alert("ntfy", [], 0.0, [])

    assert sent is True
    assert "ntfy accepted the publish" in caplog.text
    assert "not app delivery" in caplog.text
    assert "private-topic" not in caplog.text


def test_fallback_scores_are_explicitly_not_labeled_as_sctr():
    message = notifier._format_message(
        [
            {
                "ticker": "AAPL",
                "sector": "Technology",
                "momentum_score": 75.0,
                "score_type": "momentum proxy",
            }
        ],
        {
            "status": "momentum proxy",
            "sctr": None,
            "momentum_proxy": 25.0,
            "proxy_candidate_count": 1,
        },
        ["Technology"],
    )

    assert "Sales Growth TTM" not in message
    assert (
        "VOO SCTR: unavailable; momentum proxy:25.0; "
        "1 candidate comparison(s) proxied"
    ) in message
    assert "Proxy: momentum (12M/6M return and RSI percentiles)." in message
    assert "[Technology] - AAPL momentum proxy:75.0" in message
    assert "SCTR not compared" not in message


def test_verified_scores_are_labeled_as_sctr():
    message = notifier._format_message(
        [{"ticker": "MSFT", "sector": "Technology", "sctr": 70.0, "score_type": "SCTR"}],
        55.0,
        ["Technology"],
    )

    assert "VOO SCTR:55.0 (US ETFs); stocks: Large-Cap" in message
    assert "[Technology] - MSFT 70.0" in message


def test_mixed_results_are_grouped_by_sector_with_both_voo_benchmarks():
    message = notifier._format_message(
        [
            {"ticker": "AMZN", "sector": "Technology", "momentum_score": 88.9, "score_type": "momentum proxy"},
            {"ticker": "MSFT", "sector": "Technology", "sctr": 71.2, "score_type": "SCTR"},
            {"ticker": "LLY", "sector": "Healthcare", "sctr": 64.4, "score_type": "SCTR"},
        ],
        {
            "status": "SCTR",
            "sctr": 55.0,
            "momentum_proxy": 86.0,
            "proxy_candidate_count": 1,
            "proxy_unranked_count": 0,
            "sctr_unavailable_count": 1,
            "report_time": "9 Oct 2026",
            "stock_universes": ["US Large-Cap", "US Mid-Cap"],
        },
        ["Healthcare", "Technology"],
    )

    assert (
        "VOO SCTR:55.0 (US ETFs); stocks: Large-Cap/Mid-Cap; "
        "report 9 Oct 2026"
    ) in message
    assert (
        "SCTR missing for 1 stock(s); proxy used for 1; "
        "VOO momentum proxy:86.0"
    ) in message
    assert "Proxy: momentum (12M/6M return and RSI percentiles)." in message
    assert "[Healthcare] - LLY 64.4" in message
    assert "[Technology] - AMZN momentum proxy:88.9, MSFT 71.2" in message


def test_message_identifies_different_etf_and_stock_report_dates():
    message = notifier._format_message(
        [],
        {
            "status": "SCTR",
            "sctr": 55.0,
            "momentum_proxy": None,
            "etf_report_time": "9 Oct 2026",
            "stock_report_time": "8 Oct 2026",
        },
        [],
    )

    assert "ETF report 9 Oct 2026, stock report 8 Oct 2026" in message


def test_long_notification_is_truncated_to_provider_safe_size():
    results = [
        {
            "ticker": f"TICKER{index:04d}",
            "sector": "Technology",
            "sctr": 70.0,
            "score_type": "SCTR",
        }
        for index in range(1000)
    ]

    message = notifier._format_message(
        results,
        {"status": "SCTR", "sctr": 55.0, "momentum_proxy": None},
        ["Technology"],
    )

    assert len(message) <= notifier.MAX_NOTIFICATION_LENGTH
    assert "omitted" in message
