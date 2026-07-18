from __future__ import annotations

from app.services.stock_analyzer import _SYSTEM_PROMPT, _build_user_prompt


def test_stock_analysis_prompt_does_not_include_news_dimension():
    prompt = _build_user_prompt([], {}, {}, None, "300168.SZ", "")

    assert "消息面" not in _SYSTEM_PROMPT
    assert "联网新闻" not in _SYSTEM_PROMPT
    assert "新闻" not in prompt
    assert "消息面" not in prompt
