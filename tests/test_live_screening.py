import os
from pprint import pformat
from pathlib import Path

import pytest

from src.notifier import _format_message
from src.phase1_sector import get_outperforming_sectors
from src.phase2_finviz import screen_stocks
from src.phase3_sctr import filter_by_sctr


def test_live_screening_preview(monkeypatch, capsys):
    if os.getenv("RUN_LIVE_SCREENING") != "1":
        pytest.skip("Set RUN_LIVE_SCREENING=1 to opt in to live provider requests.")

    settings_path = Path(".screening.env")
    if not settings_path.is_file():
        pytest.fail("Live screening preview requires a local .screening.env file.")

    for name in tuple(os.environ):
        if name.startswith("SCREENING_"):
            monkeypatch.delenv(name)

    sectors = get_outperforming_sectors()
    candidates = screen_stocks(sectors)
    results, benchmark = filter_by_sctr(candidates)
    preview = _format_message(results, benchmark, sectors)

    with capsys.disabled():
        print("LIVE SCREENING PREVIEW — NOT SENT")
        print(f"Outperforming sectors: {sectors}")
        print(f"Finviz candidates ({len(candidates)}): {pformat(candidates)}")
        print(f"Passing results ({len(results)}): {pformat(results)}")
        print("\nNotification preview:\n" + preview)
        print("\nNo notification was sent.")
