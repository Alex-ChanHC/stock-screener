import argparse
import logging
import os

from dotenv import load_dotenv

from src.phase1_sector import get_outperforming_sectors
from src.phase2_finviz import screen_stocks
from src.phase3_sctr import filter_by_sctr
from src.notifier import send_alert

LOGGER = logging.getLogger(__name__)


def main(test_notification: bool = False, notifier: str = None) -> dict:
    load_dotenv()
    load_dotenv(".screening.env")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    selected_notifier = (notifier or os.getenv("NOTIFICATION_PROVIDER", "ntfy")).strip().lower()

    if test_notification:
        sent = send_alert(
            selected_notifier,
            [{"ticker": "TEST", "sctr": 100.0}],
            {"status": "SCTR", "sctr": 50.0, "momentum_proxy": None},
            [f"{selected_notifier} connection test"],
        )
        if not sent:
            raise RuntimeError(
                f"{selected_notifier} test alert failed; check its configuration and access."
            )
        LOGGER.info("%s test alert sent successfully.", selected_notifier)
        return {"alert_sent": True, "notifier": selected_notifier}

    sectors = []
    candidates = []
    results = []
    voo_benchmark = {"status": "not checked", "sctr": None, "momentum_proxy": None}
    flow_errors = []

    try:
        sectors = get_outperforming_sectors()
        LOGGER.info("Outperforming sectors: %s", sectors)
    except Exception as exc:
        LOGGER.exception("Phase 1 sector screening failed.")
        flow_errors.append(f"Phase 1 failed ({type(exc).__name__}); check run logs.")

    if not flow_errors:
        try:
            candidates = screen_stocks(sectors)
            LOGGER.info("Candidate tickers discovered: %d", len(candidates))
        except Exception as exc:
            LOGGER.exception("Phase 2 stock screening failed.")
            flow_errors.append(f"Phase 2 failed ({type(exc).__name__}); check run logs.")

    if not flow_errors:
        try:
            results, voo_benchmark = filter_by_sctr(candidates)
            LOGGER.info("Passing stocks after SCTR/proxy ranking: %d", len(results))
        except Exception as exc:
            LOGGER.exception("Phase 3 ranking failed.")
            flow_errors.append(f"Phase 3 failed ({type(exc).__name__}); check run logs.")

    alert_sent = send_alert(
        selected_notifier,
        results,
        voo_benchmark,
        sectors,
        flow_errors=flow_errors,
    )
    if not alert_sent:
        LOGGER.error("%s alert delivery failed.", selected_notifier)
    LOGGER.info("%s alert sent: %s", selected_notifier, alert_sent)

    return {
        "sectors": sectors,
        "candidates": candidates,
        "results": results,
        "voo_sctr": voo_benchmark["sctr"],
        "voo_benchmark": voo_benchmark,
        "alert_sent": alert_sent,
        "notifier": selected_notifier,
        "flow_errors": flow_errors,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the stock screener.")
    parser.add_argument(
        "--notifier",
        choices=("telegram", "ntfy", "discord"),
        help="notification provider (defaults to NOTIFICATION_PROVIDER, then ntfy)",
    )
    parser.add_argument(
        "--test-notification",
        "--test-telegram",
        dest="test_notification",
        action="store_true",
        help="send a sample message to verify the selected notification provider",
    )
    args = parser.parse_args()
    main(test_notification=args.test_notification, notifier=args.notifier)
