from datetime import UTC, datetime

from app.services.cls_telegraph import _normalize_rows


def test_normalize_rows_keeps_recent_wallstreetcn_lives_and_uses_text_content():
    cutoff = datetime(2026, 7, 15, tzinfo=UTC)
    rows = [
        {
            "id": 1001,
            "display_time": int(datetime(2026, 7, 16, tzinfo=UTC).timestamp()),
            "title": "测试快讯",
            "content_text": "用于板块分析的纯文本",
            "uri": "https://wallstreetcn.com/livenews/1001",
        },
        {
            "id": 1002,
            "display_time": int(datetime(2026, 7, 14, tzinfo=UTC).timestamp()),
            "title": "过期快讯",
        },
    ]

    assert _normalize_rows(rows, cutoff) == [{
        "id": 1001,
        "title": "测试快讯",
        "content": "用于板块分析的纯文本",
        "published_at": "2026-07-16T00:00:00+00:00",
        "timestamp": int(datetime(2026, 7, 16, tzinfo=UTC).timestamp()),
        "url": "https://wallstreetcn.com/livenews/1001",
    }]
