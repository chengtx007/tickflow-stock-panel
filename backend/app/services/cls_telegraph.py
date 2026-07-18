"""华尔街见闻全球快讯抓取及板块新闻影响分析。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from app.services.ai_provider import ai_configured, generate_ai_text

logger = logging.getLogger(__name__)

WALLSTREETCN_LIVES_URL = "https://api-one-wscn.awtmt.com/apiv1/content/lives"
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://wallstreetcn.com/live/global",
}
MAX_PAGES = 40
PAGE_SIZE = 100
ANALYSIS_BATCH_SIZE = 50
ANALYSIS_CONCURRENCY = 5
MAX_BATCH_ATTEMPTS = 5

ProgressCallback = Callable[[dict[str, int | str]], Awaitable[None]]


class TelegraphError(RuntimeError):
    """华尔街见闻快讯获取或解析失败。"""


def _normalize_rows(rows: list[Any], cutoff: datetime) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        published_at, ident = row.get("display_time"), row.get("id")
        if not isinstance(published_at, int) or not isinstance(ident, int) or ident in seen:
            continue
        if datetime.fromtimestamp(published_at, UTC) < cutoff:
            continue
        seen.add(ident)
        items.append({
            "id": ident,
            "title": str(row.get("title") or ""),
            "content": str(row.get("content_text") or row.get("content") or ""),
            "published_at": datetime.fromtimestamp(published_at, UTC).isoformat(),
            "timestamp": published_at,
            "url": str(row.get("uri") or f"https://wallstreetcn.com/livenews/{ident}"),
        })
    return items


def fetch_recent_telegraphs(hours: int = 24) -> list[dict[str, Any]]:
    """从 WallstreetCN 全球快讯的公开分页接口获取指定时间窗口的资讯。"""
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    cursor: int | None = None
    rows_all: list[Any] = []

    with httpx.Client(headers=REQUEST_HEADERS, timeout=20) as client:
        for page in range(MAX_PAGES):
            params: dict[str, Any] = {
                "channel": "global-channel",
                "client": "pc",
                "limit": PAGE_SIZE,
                "first_page": str(page == 0).lower(),
                "accept": "live,vip-live",
            }
            if cursor is not None:
                params["cursor"] = cursor
            response = client.get(WALLSTREETCN_LIVES_URL, params=params)
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("data", {}).get("items", []) if isinstance(payload, dict) else []
            if not isinstance(rows, list) or not rows:
                break

            rows_all.extend(rows)
            times = [row.get("display_time") for row in rows if isinstance(row, dict) and isinstance(row.get("display_time"), int)]
            if not times:
                break
            oldest = min(times)
            if oldest <= int(cutoff.timestamp()) or cursor is not None and oldest >= cursor:
                break
            cursor = oldest

    items = _normalize_rows(rows_all, cutoff)
    if not items:
        raise TelegraphError(f"华尔街见闻未返回最近 {hours} 小时全球快讯")
    return sorted(items, key=lambda item: item["timestamp"], reverse=True)


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    result = json.loads(text)
    if not isinstance(result, dict) or not isinstance(result.get("plates"), list):
        raise ValueError("AI 返回格式不完整")
    return result


def _cache_path() -> Path:
    from app.config import settings
    return settings.data_dir / "wallstreetcn_news_analysis_cache.json"


def _load_cached_analysis(cache_key: str) -> dict[str, Any] | None:
    try:
        cached = json.loads(_cache_path().read_text(encoding="utf-8"))
        result = cached.get(cache_key) if isinstance(cached, dict) else None
        return result if isinstance(result, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _save_cached_analysis(cache_key: str, result: dict[str, Any]) -> None:
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({cache_key: result}, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        logger.warning("WallstreetCN analysis cache write failed: %s", exc)


async def analyze_telegraphs(
    plate_names: list[str], hours: int = 24, progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    if not ai_configured():
        raise TelegraphError("AI API Key 未配置，请先在设置中配置 DeepSeek API Key")
    news = fetch_recent_telegraphs(hours)
    cache_key = hashlib.sha256(json.dumps({
        "hours": hours, "plate_names": plate_names, "news_ids": [item["id"] for item in news],
    }, ensure_ascii=False).encode()).hexdigest()
    cached = _load_cached_analysis(cache_key)
    if cached:
        cached["cache_hit"] = True
        return cached
    allowed = set(plate_names)
    by_id = {item["id"]: item for item in news}
    news_batches = [news[start:start + ANALYSIS_BATCH_SIZE] for start in range(0, len(news), ANALYSIS_BATCH_SIZE)]
    semaphore = asyncio.Semaphore(ANALYSIS_CONCURRENCY)
    progress_lock = asyncio.Lock()
    completed_batches = 0
    retry_count = 0
    failed_batch_count = 0

    async def report(status: str) -> None:
        if progress:
            await progress({
                "status": status,
                "completed_batches": completed_batches,
                "total_batches": len(news_batches),
                "retry_count": retry_count,
                "failed_batches": failed_batch_count,
            })

    async def analyze_batch(batch: list[dict[str, Any]]) -> dict[str, Any] | None:
        nonlocal completed_batches, retry_count, failed_batch_count
        for attempt in range(1, MAX_BATCH_ATTEMPTS + 1):
            try:
                async with semaphore:
                    result = await _analyze_news_batch(plate_names, batch, hours)
                async with progress_lock:
                    completed_batches += 1
                    await report("running")
                return result
            except TelegraphError as exc:
                logger.warning("WallstreetCN analysis batch attempt %d failed: %s", attempt, exc)
                if attempt < MAX_BATCH_ATTEMPTS:
                    async with progress_lock:
                        retry_count += 1
                        await report("running")
                    await asyncio.sleep(attempt)
        async with progress_lock:
            completed_batches += 1
            failed_batch_count += 1
            await report("running")
        return None

    await report("running")
    batch_results = await asyncio.gather(*(
        analyze_batch(news_batch)
        for news_batch in news_batches
    ))
    merged: dict[str, dict[str, Any]] = {}
    failed_batches = sum(result is None for result in batch_results)
    for parsed in batch_results:
        if parsed is None:
            continue
        for item in parsed["plates"]:
            if not isinstance(item, dict) or item.get("plate_name") not in allowed:
                continue
            score = item.get("score")
            if not isinstance(score, int) or score == 0 or score < -2 or score > 2:
                continue
            ids = [news_id for news_id in item.get("news_ids", []) if isinstance(news_id, int) and news_id in by_id]
            if not ids:
                continue
            result = merged.setdefault(item["plate_name"], {"score": 0, "summaries": [], "ids": set()})
            result["score"] += score
            summary = str(item.get("summary") or "")
            if summary and summary not in result["summaries"]:
                result["summaries"].append(summary)
            result["ids"].update(ids)

    plates = []
    for plate_name, result in merged.items():
        score = max(-2, min(2, result["score"]))
        if score == 0:
            continue
        ids = [item["id"] for item in news if item["id"] in result["ids"]]
        plates.append({
            "plate_name": plate_name,
            "sentiment": "bullish" if score > 0 else "bearish",
            "score": score,
            "summary": "；".join(result["summaries"][:3]),
            "news": [by_id[news_id] for news_id in ids],
        })
    result = {
        "source": "华尔街见闻全球快讯",
        "hours": hours,
        "news_count": len(news),
        "batch_count": len(news_batches),
        "failed_batch_count": failed_batches,
        "coverage_start": news[-1]["published_at"],
        "coverage_end": news[0]["published_at"],
        "summary": f"已完成 {len(news_batches)} 个新闻批次的全行业分析。" + (f"其中 {failed_batches} 批未完成。" if failed_batches else ""),
        "plates": plates,
        "analyzed_at": datetime.now(UTC).isoformat(),
        "cache_hit": False,
    }
    if not failed_batches:
        _save_cached_analysis(cache_key, result)
    return result


async def _analyze_news_batch(plate_names: list[str], news: list[dict[str, Any]], hours: int) -> dict[str, Any]:
    news_for_prompt = [
        {"id": item["id"], "time": item["published_at"], "title": item["title"], "content": item["content"][:300]}
        for item in news
    ]
    prompt = f"""你是 A 股新闻分析师。只根据给出的华尔街见闻全球快讯，判断它们对指定板块未来短线情绪的影响。
板块列表：{json.dumps(plate_names, ensure_ascii=False)}
输出严格 JSON，不要 Markdown：
{{"summary":"全市场 2-3 句总结","plates":[{{"plate_name":"必须是列表中的原名","sentiment":"bullish|bearish|neutral","score":-2到2整数,"summary":"一句影响逻辑","news_ids":[快讯id]}}]}}
只输出有明确关联且 score 非 0 的板块；没有关联不要猜测；同一消息不要重复计入多个无关板块。
以下为最近 {hours} 小时快讯中的一个批次：{json.dumps(news_for_prompt, ensure_ascii=False)}"""
    try:
        return _parse_json(await generate_ai_text(
            [{"role": "user", "content": prompt}], temperature=0.1, max_tokens=2500, timeout=180,
        ))
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise TelegraphError(f"新闻分析批次失败: {exc}") from exc


async def analyze_plate_news_detail(plate_name: str, news_ids: list[int], hours: int = 24) -> dict[str, Any]:
    if not ai_configured():
        raise TelegraphError("AI API Key 未配置，请先在设置中配置 DeepSeek API Key")
    news_by_id = {item["id"]: item for item in fetch_recent_telegraphs(hours)}
    news = [news_by_id[news_id] for news_id in news_ids if news_id in news_by_id]
    if not news:
        raise TelegraphError("未找到该板块对应的近期快讯，请重新执行新闻分析")
    prompt = f"""你是 A 股板块研究员。只根据下面与“{plate_name}”关联的新闻，生成简明但具体的交易新闻分析。
输出使用中文 Markdown，包含：核心催化、利好与风险、影响路径、短线观察点。不要引用新闻之外的事实，不构成投资建议。
新闻：{json.dumps([{"time": item["published_at"], "title": item["title"], "content": item["content"][:600]} for item in news[:40]], ensure_ascii=False)}"""
    try:
        analysis = await generate_ai_text(
            [{"role": "user", "content": prompt}], temperature=0.2, max_tokens=1600, timeout=120,
        )
    except RuntimeError as exc:
        raise TelegraphError(f"板块详细新闻分析失败: {exc}") from exc
    return {
        "plate_name": plate_name,
        "news_count": len(news),
        "analysis": analysis.strip(),
    }
