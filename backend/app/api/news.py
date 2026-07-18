"""新闻资讯 API。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query

from app.services.news import NEWS_CATEGORIES, news_service

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("/feed")
async def get_news_feed(
    category: str = Query("all", description="all/realtime/morning/stock/announcement/research/hot"),
    symbol: str = Query("", description="个股代码,例如 600519.SH"),
    query: str = Query("", description="研报或新闻搜索词"),
    limit: int = Query(30, ge=1, le=100),
):
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(news_service.get_feed, category, symbol=symbol, query=query, limit=limit),
            timeout=20,
        )
    except TimeoutError:
        return {
            "news": [],
            "category": category,
            "total": 0,
            "updated_at": "",
            "error": "新闻源响应超时",
        }


@router.get("/sources")
async def get_news_sources():
    return {
        "categories": list(NEWS_CATEGORIES),
        "sources": [
            {"id": "tushare", "name": "TuShare"},
            {"id": "eastmoney", "name": "东方财富"},
            {"id": "cls", "name": "财联社"},
            {"id": "cninfo", "name": "巨潮资讯"},
            {"id": "exa", "name": "联网搜索"},
        ],
    }
