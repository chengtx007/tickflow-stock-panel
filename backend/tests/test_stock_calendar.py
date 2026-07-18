from __future__ import annotations

from datetime import date, timedelta

import httpx

from app.services import stock_calendar


def test_normalize_stock_code_accepts_project_symbol():
    assert stock_calendar.normalize_stock_code("300168.SZ") == "300168"
    assert stock_calendar.normalize_stock_code("600000.SH") == "600000"
    assert stock_calendar.normalize_stock_code("not-a-stock") is None


def test_fetch_events_maps_eastmoney_payload(monkeypatch):
    recent = date.today().isoformat()
    recent_previous = (date.today() - timedelta(days=1)).isoformat()
    old = (date.today() - timedelta(days=366)).isoformat()
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://example.com"),
        json={
            "success": True,
            "result": {
                "count": 3,
                "data": [
                    {
                        "NOTICE_DATE": f"{recent} 00:00:00",
                        "EVENT_TYPE": "公告",
                        "EVENT_TYPE_CODE": "019",
                        "LEVEL1_CONTENT": "发布公告",
                        "INFO_CODE": "AN123",
                        "CHANGE_RATE": -5.2953,
                        "CLOSE_PRICE": 4.65,
                    },
                    {"NOTICE_DATE": f"{recent_previous} 00:00:00", "EVENT_TYPE": "股东大会", "LEVEL1_CONTENT": "召开股东大会"},
                    {"NOTICE_DATE": f"{old} 00:00:00", "EVENT_TYPE": "公告", "LEVEL1_CONTENT": "一年前公告"},
                ],
            },
        },
    )
    captured: dict = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return response

    monkeypatch.setattr(stock_calendar.httpx, "get", fake_get)

    result = stock_calendar.fetch_events("300168.SZ", limit=20)

    assert result["code"] == "300168"
    assert result["count"] == 2
    assert len(result["events"]) == 2
    assert result["events"][0] == {
        "id": "AN123",
        "date": "2026-07-17",
        "event_type": "公告",
        "event_type_code": "019",
        "content": "发布公告",
        "info_code": "AN123",
        "change_rate": -5.2953,
        "close_price": 4.65,
    }
    assert captured["kwargs"]["params"]["filter"] == '(SECURITY_CODE="300168")'
    assert captured["kwargs"]["params"]["pageSize"] == 20


def test_fetch_events_raises_for_upstream_failure(monkeypatch):
    monkeypatch.setattr(
        stock_calendar.httpx,
        "get",
        lambda *args, **kwargs: httpx.Response(
            200,
            request=httpx.Request("GET", "https://example.com"),
            json={"success": False, "message": "失败"},
        ),
    )

    try:
        stock_calendar.fetch_events("300168.SZ")
    except stock_calendar.StockCalendarError as exc:
        assert str(exc) == "失败"
    else:
        raise AssertionError("expected StockCalendarError")
