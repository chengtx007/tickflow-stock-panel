"""行业板块资金流快照。

选股通的公开 ``flash-api`` 是主数据源; TuShare 的同花顺行业资金流仅在
主源不可用时作为回退. 数据按行业板块保存, 与按个股关联的 ext_data 分开.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

FLASH_API = "https://flash-api.xuangubao.com.cn"
INDUSTRY_TYPE = 2
CONCEPT_TYPE = 1
DETAIL_FIELDS = (
    "plate_id,plate_name,fund_flow,rise_count,fall_count,stay_count,"
    "limit_up_count,core_avg_pcp,core_avg_pcp_rank,"
    "core_avg_pcp_rank_change,top_n_stocks,bottom_n_stocks"
)
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://xuangutong.com.cn/zhutiku",
    "Origin": "https://xuangutong.com.cn",
}


class MarketFlowError(RuntimeError):
    """行业资金流的所有数据源均不可用。"""


RequestJson = Callable[[str, dict[str, str | int]], dict[str, Any]]


def _request_json(url: str, params: dict[str, str | int]) -> dict[str, Any]:
    response = httpx.get(url, params=params, headers=REQUEST_HEADERS, timeout=30)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or data.get("code") != 20000:
        message = data.get("message") if isinstance(data, dict) else str(data)
        raise MarketFlowError(f"选股通接口失败: {message}")
    return data


def _fetch_xuangutong_flow(plate_type: int, label: str, request_json: RequestJson = _request_json) -> dict[str, Any]:
    """获取选股通一个板块分类的资金流, 保持上游资金流排名顺序。"""
    rank = request_json(
        f"{FLASH_API}/api/plate/rank",
        {"field": "fund_flow", "type": plate_type},
    )
    plate_ids = rank.get("data")
    if not isinstance(plate_ids, list) or not plate_ids:
        raise MarketFlowError(f"选股通{label}板块排序为空")

    normalized_ids = [str(plate_id) for plate_id in plate_ids]
    detail = request_json(
        f"{FLASH_API}/api/plate/data",
        {"fields": DETAIL_FIELDS, "plates": ",".join(normalized_ids)},
    )
    detail_rows = detail.get("data")
    if not isinstance(detail_rows, dict):
        raise MarketFlowError(f"选股通{label}板块详情格式异常")

    rows: list[dict[str, Any]] = []
    for rank_no, plate_id in enumerate(normalized_ids, start=1):
        row = detail_rows.get(plate_id)
        if not isinstance(row, dict) or not row.get("plate_name"):
            continue
        rows.append({
            "rank": rank_no,
            "plate_id": plate_id,
            "plate_name": row["plate_name"],
            "fund_flow": row.get("fund_flow"),
            "core_avg_pcp": row.get("core_avg_pcp"),
            "rise_count": row.get("rise_count"),
            "fall_count": row.get("fall_count"),
            "stay_count": row.get("stay_count"),
            "limit_up_count": row.get("limit_up_count"),
            "core_avg_pcp_rank": row.get("core_avg_pcp_rank"),
            "core_avg_pcp_rank_change": row.get("core_avg_pcp_rank_change"),
            "top_n_stocks": row.get("top_n_stocks"),
            "bottom_n_stocks": row.get("bottom_n_stocks"),
        })

    if not rows:
        raise MarketFlowError(f"选股通{label}板块详情为空")
    if len(rows) != len(normalized_ids):
        logger.warning("选股通%s板块详情缺少 %d/%d 条", label, len(normalized_ids) - len(rows), len(normalized_ids))

    return {
        "source": "xuangutong",
        "as_of": date.today().isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
        "rows": rows,
    }


def fetch_xuangutong_industry_flow(request_json: RequestJson = _request_json) -> dict[str, Any]:
    return _fetch_xuangutong_flow(INDUSTRY_TYPE, "行业", request_json)


def fetch_xuangutong_concept_flow(request_json: RequestJson = _request_json) -> dict[str, Any]:
    return _fetch_xuangutong_flow(CONCEPT_TYPE, "概念", request_json)


def fetch_xuangutong_plate_stocks(plate_id: str, request_json: RequestJson = _request_json) -> list[str]:
    detail = request_json(
        f"{FLASH_API}/api/plate/data",
        {"fields": "plate_id,plate_name,stocks", "plates": plate_id},
    )
    row = detail.get("data", {}).get(str(plate_id)) if isinstance(detail.get("data"), dict) else None
    stocks = row.get("stocks") if isinstance(row, dict) else None
    return [str(symbol) for symbol in stocks] if isinstance(stocks, list) else []


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_tushare_industry_flow() -> dict[str, Any]:
    """TuShare 同花顺行业资金流回退源。"""
    if not settings.tushare_api_token:
        raise MarketFlowError("未配置 TUSHARE_API_TOKEN")

    import tushare as ts

    df = ts.pro_api(settings.tushare_api_token).moneyflow_ind_ths()
    if df is None or df.empty:
        raise MarketFlowError("TuShare 行业资金流为空")

    records = df.to_dict("records")
    records.sort(key=lambda row: _number(row.get("net_mf_amount")) or 0, reverse=True)
    rows = [
        {
            "rank": rank,
            "plate_id": f"tushare:{row.get('name', '')}",
            "plate_name": row.get("name") or "",
            "fund_flow": _number(row.get("net_mf_amount")),
            "core_avg_pcp": (
                _number(row.get("pct_change")) / 100
                if _number(row.get("pct_change")) is not None else None
            ),
            "amount": _number(row.get("amount")),
            "trade_date": str(row.get("trade_date") or ""),
        }
        for rank, row in enumerate(records, start=1)
        if row.get("name")
    ]
    if not rows:
        raise MarketFlowError("TuShare 行业资金流无有效记录")

    return {
        "source": "tushare",
        "as_of": rows[0].get("trade_date") or date.today().isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
        "rows": rows,
    }


def _snapshot_path(data_dir: Path) -> Path:
    return data_dir / "market_flow" / "industry.json"


def _history_path(data_dir: Path, as_of: str) -> Path:
    return data_dir / "market_flow" / "industry_history" / f"{as_of}.json"


def _concept_snapshot_path(data_dir: Path) -> Path:
    return data_dir / "market_flow" / "concept.json"


def _concept_history_path(data_dir: Path, as_of: str) -> Path:
    return data_dir / "market_flow" / "concept_history" / f"{as_of}.json"


def _history_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """保存热力图趋势所需的最小字段, 避免每日重复存成分股明细。"""
    return {
        "source": snapshot["source"],
        "as_of": snapshot["as_of"],
        "updated_at": snapshot["updated_at"],
        "rows": [
            {
                "plate_id": row["plate_id"],
                "plate_name": row["plate_name"],
                "fund_flow": row.get("fund_flow"),
                "core_avg_pcp": row.get("core_avg_pcp"),
            }
            for row in snapshot["rows"]
        ],
    }


def refresh_industry_flow(data_dir: Path) -> dict[str, Any]:
    """刷新行业资金流快照, 选股通失败时自动回退 TuShare。"""
    errors: list[str] = []
    for fetcher in (fetch_xuangutong_industry_flow, fetch_tushare_industry_flow):
        try:
            snapshot = fetcher()
            path = _snapshot_path(data_dir)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            tmp_path.replace(path)
            history_path = _history_path(data_dir, snapshot["as_of"])
            history_path.parent.mkdir(parents=True, exist_ok=True)
            history_tmp = history_path.with_suffix(".tmp")
            history_tmp.write_text(json.dumps(_history_snapshot(snapshot), ensure_ascii=False), encoding="utf-8")
            history_tmp.replace(history_path)
            logger.info("行业资金流刷新成功: source=%s, rows=%d", snapshot["source"], len(snapshot["rows"]))
            return snapshot
        except Exception as exc:
            errors.append(str(exc))
            logger.warning("行业资金流来源 %s 失败: %s", fetcher.__name__, exc)

    raise MarketFlowError("行业资金流刷新失败: " + "; ".join(errors))


def refresh_concept_flow(data_dir: Path) -> dict[str, Any]:
    snapshot = fetch_xuangutong_concept_flow()
    path = _concept_snapshot_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    history_path = _concept_history_path(data_dir, snapshot["as_of"])
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(_history_snapshot(snapshot), ensure_ascii=False), encoding="utf-8")
    return snapshot


def read_industry_flow(data_dir: Path) -> dict[str, Any] | None:
    path = _snapshot_path(data_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("行业资金流快照读取失败: %s", exc)
        return None
    return data if isinstance(data, dict) else None


def read_concept_flow(data_dir: Path) -> dict[str, Any] | None:
    path = _concept_snapshot_path(data_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def read_industry_flow_history(data_dir: Path, days: int = 20) -> list[dict[str, Any]]:
    """读取最近 N 个交易日的行业资金流摘要。"""
    history_dir = data_dir / "market_flow" / "industry_history"
    if not history_dir.exists():
        return []

    snapshots: list[dict[str, Any]] = []
    for path in sorted(history_dir.glob("*.json"), reverse=True)[:days]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("行业资金流历史读取失败 %s: %s", path.name, exc)
            continue
        if isinstance(data, dict) and isinstance(data.get("rows"), list):
            snapshots.append(data)
    return list(reversed(snapshots))


def read_concept_flow_history(data_dir: Path, days: int = 20) -> list[dict[str, Any]]:
    history_dir = data_dir / "market_flow" / "concept_history"
    if not history_dir.exists():
        return []
    snapshots = []
    for path in sorted(history_dir.glob("*.json"), reverse=True)[:days]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and isinstance(data.get("rows"), list):
            snapshots.append(data)
    return list(reversed(snapshots))
