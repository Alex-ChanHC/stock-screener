import main


def test_test_mode_sends_sample_alert_via_cli_provider(monkeypatch):
    sent_alerts = []

    def fake_send_alert(provider, results, voo_sctr, sectors):
        sent_alerts.append((provider, results, voo_sctr, sectors))
        return True

    monkeypatch.setattr(main, "send_alert", fake_send_alert)

    result = main.main(test_notification=True, notifier="ntfy")

    assert result == {"alert_sent": True, "notifier": "ntfy"}
    assert sent_alerts == [
        (
            "ntfy",
            [{"ticker": "TEST", "sctr": 100.0}],
            {"status": "SCTR", "sctr": 50.0, "momentum_proxy": None},
            ["ntfy connection test"],
        )
    ]


def test_test_mode_uses_provider_from_environment(monkeypatch):
    monkeypatch.setenv("NOTIFICATION_PROVIDER", "discord")
    sent_providers = []
    monkeypatch.setattr(
        main,
        "send_alert",
        lambda provider, *_args: sent_providers.append(provider) or True,
    )

    result = main.main(test_notification=True)

    assert result["notifier"] == "discord"
    assert sent_providers == ["discord"]


def test_pipeline_error_is_reported_in_alert_and_stops_later_stages(monkeypatch):
    alerts = []
    monkeypatch.setattr(
        main,
        "get_outperforming_sectors",
        lambda: ["Technology"],
    )

    def fail_screen(_sectors):
        raise RuntimeError("provider failure")

    monkeypatch.setattr(main, "screen_stocks", fail_screen)
    monkeypatch.setattr(
        main,
        "filter_by_sctr",
        lambda _candidates: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    monkeypatch.setattr(
        main,
        "send_alert",
        lambda provider, results, benchmark, sectors, flow_errors=None: (
            alerts.append((provider, results, benchmark, sectors, flow_errors)) or True
        ),
    )

    result = main.main(notifier="ntfy")

    assert result["flow_errors"] == [
        "Phase 2 failed (RuntimeError); check run logs."
    ]
    assert alerts[0][0] == "ntfy"
    assert alerts[0][4] == result["flow_errors"]
    assert result["alert_sent"] is True
