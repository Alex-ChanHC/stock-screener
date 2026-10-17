import html
import logging
import os
from typing import Dict, Iterable, List, Optional, Union

import requests

LOGGER = logging.getLogger(__name__)
SUPPORTED_PROVIDERS = ("telegram", "ntfy", "discord")
MAX_NOTIFICATION_LENGTH = 3500


def _format_message(
    results: Iterable[dict],
    voo_benchmark: Union[dict, float, None],
    outperforming_sectors: List[str],
    flow_errors: Optional[List[str]] = None,
) -> str:
    if isinstance(voo_benchmark, dict):
        benchmark_status = voo_benchmark.get("status", "not checked")
        voo_sctr = voo_benchmark.get("sctr")
        voo_proxy = voo_benchmark.get("momentum_proxy")
        proxy_candidate_count = int(voo_benchmark.get("proxy_candidate_count", 0))
        proxy_unranked_count = int(voo_benchmark.get("proxy_unranked_count", 0))
        sctr_unavailable_count = int(voo_benchmark.get("sctr_unavailable_count", 0))
        report_time = voo_benchmark.get("report_time")
        etf_report_time = voo_benchmark.get("etf_report_time", report_time)
        stock_report_time = voo_benchmark.get("stock_report_time", report_time)
    else:
        benchmark_status = "momentum proxy" if voo_benchmark is None else "SCTR"
        voo_sctr = voo_benchmark
        voo_proxy = None
        proxy_candidate_count = 0
        proxy_unranked_count = 0
        sctr_unavailable_count = 0
        report_time = None
        etf_report_time = None
        stock_report_time = None

    lines = ["Stock Screener"]
    footer = [f"⚠️ {error}" for error in flow_errors or []]
    if outperforming_sectors:
        lines.append("Sectors: " + ", ".join(outperforming_sectors))
    if benchmark_status == "not checked":
        lines.append("VOO SCTR: not checked (no candidates)")
    elif benchmark_status == "momentum proxy":
        date_label = f"; ETF report {etf_report_time}" if etf_report_time else ""
        lines.append(
            "VOO SCTR: unavailable; "
            + (
                f"momentum proxy:{float(voo_proxy):.1f}"
                if voo_proxy is not None
                else "momentum proxy unavailable"
            )
            + f"; {proxy_candidate_count} candidate comparison(s) proxied{date_label}"
        )
    else:
        if etf_report_time and stock_report_time and etf_report_time == stock_report_time:
            date_label = f"; report {etf_report_time}"
        elif etf_report_time and stock_report_time:
            date_label = (
                f"; ETF report {etf_report_time}, stock report {stock_report_time}"
            )
        elif etf_report_time or stock_report_time:
            date_label = f"; report {etf_report_time or stock_report_time}"
        else:
            date_label = f"; report {report_time}" if report_time else ""
        lines.append(f"VOO SCTR:{float(voo_sctr):.1f}{date_label}")
        if sctr_unavailable_count:
            proxy_text = (
                f"; VOO momentum proxy:{float(voo_proxy):.1f}"
                if voo_proxy is not None
                else "; VOO momentum proxy unavailable"
            )
            lines.append(
                f"SCTR missing for {sctr_unavailable_count} stock(s); "
                f"proxy used for {proxy_candidate_count}{proxy_text}"
            )
    if benchmark_status == "momentum proxy" or proxy_candidate_count:
        lines.append("Proxy: momentum (12M/6M return and RSI percentiles).")
    if proxy_unranked_count:
        lines.append(f"Proxy unavailable for {proxy_unranked_count} candidate(s); excluded.")

    results = list(results or [])
    if results:
        lines.append("Qualifying stocks:")
        grouped: Dict[str, List[str]] = {}
        for item in results:
            sector = str(item.get("sector") or "Other")
            ticker = str(item.get("ticker", "N/A"))
            if item.get("score_type") == "momentum proxy" or item.get("sctr_compared") is False:
                entry = f"{ticker} proxy:{float(item.get('momentum_score', 0.0)):.1f}"
            else:
                entry = ticker
            grouped.setdefault(sector, []).append(entry)

        sector_order = {sector: index for index, sector in enumerate(outperforming_sectors)}
        groups = sorted(
            grouped.items(),
            key=lambda group: (sector_order.get(group[0], len(sector_order)), group[0]),
        )
        omitted = 0
        while True:
            grouped_lines = [
                f"[{sector}] - {', '.join(entries)}"
                for sector, entries in groups
                if entries
            ]
            message_lines = lines + grouped_lines + footer
            if omitted:
                message_lines.append(f"... +{omitted} omitted")
            message = "\n".join(message_lines)
            if len(message) <= MAX_NOTIFICATION_LENGTH:
                return message

            for _, entries in reversed(groups):
                if entries:
                    entries.pop()
                    omitted += 1
                    break
            else:
                return "\n".join((lines + footer))[:MAX_NOTIFICATION_LENGTH]
    else:
        lines.append(
            "Screening incomplete." if flow_errors else "No qualifying stocks found."
        )

    return "\n".join(lines + footer)


def _send_telegram(message: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        LOGGER.error("Telegram selected but TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing.")
        return False

    escaped_message = html.escape(message)
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": escaped_message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        LOGGER.error("Failed to send Telegram alert (%s).", type(exc).__name__)
        return False

    if not data.get("ok"):
        LOGGER.error("Telegram rejected the alert.")
        return False
    return True


def _send_ntfy(message: str) -> bool:
    topic = (os.getenv("NTFY_TOPIC") or "").strip()
    if not topic:
        LOGGER.error("ntfy selected but NTFY_TOPIC is missing.")
        return False

    server = (os.getenv("NTFY_SERVER") or "https://ntfy.sh").strip().rstrip("/")
    try:
        response = requests.post(
            f"{server}/{topic.strip('/')}",
            data=message.encode("utf-8"),
            headers={"Title": "Stock Screener Alert", "Content-Type": "text/plain; charset=utf-8"},
            timeout=20,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        LOGGER.error("Failed to send ntfy alert (%s).", type(exc).__name__)
        return False

    try:
        response_data = response.json()
    except ValueError:
        response_data = {}
    message_id = response_data.get("id") if isinstance(response_data, dict) else None
    if message_id:
        LOGGER.info(
            "ntfy accepted the publish (message ID: %s, server: %s). "
            "This confirms server acceptance, not app delivery.",
            message_id,
            server,
        )
    else:
        LOGGER.info(
            "ntfy server %s accepted the publish (HTTP %s). "
            "This confirms server acceptance, not app delivery.",
            server,
            response.status_code,
        )
    return True


def _send_discord(message: str) -> bool:
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        LOGGER.error("Discord selected but DISCORD_WEBHOOK_URL is missing.")
        return False

    try:
        response = requests.post(
            webhook_url,
            json={"content": message},
            timeout=20,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        LOGGER.error("Failed to send Discord alert (%s).", type(exc).__name__)
        return False
    return True


def send_alert(
    provider: str,
    results: Iterable[dict],
    voo_benchmark: Union[dict, float, None],
    outperforming_sectors: List[str],
    flow_errors: Optional[List[str]] = None,
) -> bool:
    """Send a screener alert through the selected notification provider."""
    normalized_provider = provider.strip().lower()
    if normalized_provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported notification provider {provider!r}; choose from "
            f"{', '.join(SUPPORTED_PROVIDERS)}."
        )

    message = _format_message(results, voo_benchmark, outperforming_sectors, flow_errors)
    senders = {
        "telegram": _send_telegram,
        "ntfy": _send_ntfy,
        "discord": _send_discord,
    }
    return senders[normalized_provider](message)


def send_telegram_alert(
    results: Iterable[dict],
    voo_benchmark: Union[dict, float, None],
    outperforming_sectors: List[str],
) -> bool:
    """Backward-compatible Telegram-only alert entry point."""
    return send_alert("telegram", results, voo_benchmark, outperforming_sectors)
