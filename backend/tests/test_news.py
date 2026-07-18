from __future__ import annotations

import pandas as pd

from app.services.news import NewsService


def test_akshare_call_uses_python_string_inference_temporarily():
    service = NewsService()
    observed: dict[str, object] = {}

    class FakeAkshare:
        @staticmethod
        def stock_news_em(**_kwargs):
            observed["infer_string"] = pd.get_option("future.infer_string")
            return "ok"

    service._akshare = FakeAkshare()

    with pd.option_context("future.infer_string", True):
        assert service._ak_call("stock_news_em", symbol="300168") == "ok"
        assert observed["infer_string"] is False
        assert pd.get_option("future.infer_string") is True
