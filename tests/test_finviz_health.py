import logging

import requests

from scripts import check_finviz_health


class FakeResponse:
    status_code = 200

    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


def test_health_check_succeeds_when_current_finviz_links_are_present(
    monkeypatch, caplog
):
    caplog.set_level(logging.INFO)
    requested = {}

    def fake_get(url, **kwargs):
        requested["url"] = url
        requested.update(kwargs)
        return FakeResponse(
            '<a href="/quote?t=AAA&amp;b=1">AAA</a>'
            '<a href="/quote?t=BBB&amp;b=1">BBB</a>'
        )

    monkeypatch.setattr(check_finviz_health.requests, "get", fake_get)

    assert check_finviz_health.main() == 0
    assert requested["params"]["f"] == "cap_largeover"
    assert "extracted 2 ticker links" in caplog.text


def test_health_check_fails_when_no_ticker_links_are_parseable(monkeypatch, caplog):
    monkeypatch.setattr(
        check_finviz_health.requests,
        "get",
        lambda *_args, **_kwargs: FakeResponse(
            "<html><title>Changed page</title></html>"
        ),
    )

    assert check_finviz_health.main() == 1
    assert "no parseable tickers" in caplog.text


def test_health_check_fails_when_finviz_request_fails(monkeypatch, caplog):
    def fail_request(*_args, **_kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(check_finviz_health.requests, "get", fail_request)

    assert check_finviz_health.main() == 1
    assert "could not fetch the screener (Timeout)" in caplog.text
