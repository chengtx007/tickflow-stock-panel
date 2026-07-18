"""东方财富个股事件日历数据。"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

EASTMONEY_CALENDAR_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EASTMONEY_CALENDAR_PAGE = "https://data.eastmoney.com/stockcalendar/{code}.html"
_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_PAGE_SIZE = 200
_RECENT_DAYS = 365


class StockCalendarError(RuntimeError):
    """东方财富事件日历请求失败。"""


def normalize_stock_code(symbol: str) -> str | None:
    """从项目股票标识(如 300168.SZ)中提取六位证券代码。"""
    match = _CODE_RE.search(symbol.strip())
    return match.group(1) if match else None


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_event(row: dict[str, Any], index: int) -> dict[str, Any] | None:
    raw_date = str(row.get("NOTICE_DATE") or "")
    event_date = raw_date[:10]
    content = str(row.get("LEVEL1_CONTENT") or "").strip()
    if not event_date or not content:
        return None

    event_type = str(row.get("EVENT_TYPE") or "其他")
    type_code = str(row.get("EVENT_TYPE_CODE") or "")
    info_code = str(row.get("INFO_CODE") or "") or None
    return {
        "id": info_code or f"{event_date}-{type_code}-{index}",
        "date": event_date,
        "event_type": event_type,
        "event_type_code": type_code,
        "content": content,
        "info_code": info_code,
        "change_rate": _number(row.get("CHANGE_RATE")),
        "close_price": _number(row.get("CLOSE_PRICE")),
    }


def fetch_events(symbol: str, limit: int = 500) -> dict[str, Any]:
    """获取单只股票近一年的事件日历, 同时保留已公布的未来事件。"""
    code = normalize_stock_code(symbol)
    if not code:
        raise ValueError("无效的股票代码")

    params = {
        "reportName": "RPT_STOCKCALENDAR",
        "columns": "ALL",
        "quoteColumns": "",
        "filter": f'(SECURITY_CODE="{code}")',
        "sortTypes": -1,
        "sortColumns": "NOTICE_DATE",
        "source": "WEB",
        "client": "WEB",
    }
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": EASTMONEY_CALENDAR_PAGE.format(code=code),
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
        ),
    }

    cutoff = date.today() - timedelta(days=_RECENT_DAYS)
    rows: list[dict[str, Any]] = []
    page = 1
    while len(rows) < limit:
        page_size = min(_PAGE_SIZE, limit - len(rows))
        page_params = {**params, "pageNumber": page, "pageSize": page_size}
        try:
            response = httpx.get(
                EASTMONEY_CALENDAR_API,
                params=page_params,
                headers=headers,
                timeout=httpx.Timeout(15.0, connect=5.0),
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("eastmoney stock calendar request failed for %s: %s", symbol, exc)
            raise StockCalendarError("东方财富事件日历暂时无法获取") from exc

        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(payload, dict) or payload.get("success") is not True or not isinstance(result, dict):
            message = payload.get("message") if isinstance(payload, dict) else None
            logger.warning("eastmoney stock calendar response failed for %s: %s", symbol, message)
            raise StockCalendarError(message or "东方财富事件日历返回异常")

        page_rows = result.get("data")
        if not isinstance(page_rows, list):
            page_rows = []
        rows.extend(row for row in page_rows if isinstance(row, dict))
        if len(page_rows) < page_size:
            break

        last_date = next(
            (str(row.get("NOTICE_DATE") or "")[:10] for row in reversed(page_rows) if row.get("NOTICE_DATE")),
            "",
        )
        if last_date and last_date < cutoff.isoformat():
            break
        page += 1

    events = []
    for index, row in enumerate(rows):
        event = _parse_event(row, index)
        if event is None:
            continue
        try:
            event_date = date.fromisoformat(event["date"])
        except ValueError:
            continue
        if event_date >= cutoff:
            events.append(event)

    return {
        "symbol": symbol,
        "code": code,
        "count": len(events),
        "events": events,
        "source_url": EASTMONEY_CALENDAR_PAGE.format(code=code),
    }
