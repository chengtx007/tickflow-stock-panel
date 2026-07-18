from __future__ import annotations

import json

from app.services import market_flow


def test_fetch_xuangutong_industry_flow_uses_ranked_ids_and_details():
    calls = []

    def request_json(url, params):
        calls.append((url, params))
        if url.endswith("/rank"):
            assert params == {"field": "fund_flow", "type": 2}
            return {"code": 20000, "data": ["101", "202"]}
        assert params["plates"] == "101,202"
        return {
            "code": 20000,
            "data": {
                "101": {"plate_name": "软件", "fund_flow": 12.5, "rise_count": 4},
                "202": {"plate_name": "券商", "fund_flow": -3.0, "fall_count": 8},
            },
        }

    snapshot = market_flow.fetch_xuangutong_industry_flow(request_json)

    assert len(calls) == 2
    assert snapshot["source"] == "xuangutong"
    assert [(row["rank"], row["plate_id"], row["plate_name"]) for row in snapshot["rows"]] == [
        (1, "101", "软件"),
        (2, "202", "券商"),
    ]


def test_refresh_uses_tushare_when_primary_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(
        market_flow,
        "fetch_xuangutong_industry_flow",
        lambda: (_ for _ in ()).throw(market_flow.MarketFlowError("primary unavailable")),
    )
    monkeypatch.setattr(
        market_flow,
        "fetch_tushare_industry_flow",
        lambda: {
            "source": "tushare",
            "as_of": "2026-07-17",
            "updated_at": "now",
            "rows": [{"plate_id": "tushare:银行", "plate_name": "银行", "fund_flow": 1.0, "core_avg_pcp": 0.01}],
        },
    )

    snapshot = market_flow.refresh_industry_flow(tmp_path)

    assert snapshot["source"] == "tushare"
    saved = json.loads((tmp_path / "market_flow" / "industry.json").read_text(encoding="utf-8"))
    assert saved == snapshot
    assert market_flow.read_industry_flow(tmp_path) == snapshot
    history = market_flow.read_industry_flow_history(tmp_path)
    assert len(history) == 1
    assert history[0]["rows"] == [{"plate_id": "tushare:银行", "plate_name": "银行", "fund_flow": 1.0, "core_avg_pcp": 0.01}]
