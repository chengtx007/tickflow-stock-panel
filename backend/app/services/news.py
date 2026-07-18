"""联网财经新闻聚合服务。

优先使用 TuShare/AkShare 的结构化接口，失败时使用 Exa 公共 MCP 搜索。
所有上游都是可选降级项；新闻不可用不应阻断行情或 AI 分析。
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from app.config import settings
from app.services.exa_mcp import exa_mcp

logger = logging.getLogger(__name__)

NEWS_CATEGORIES = ("all", "realtime", "morning", "stock", "announcement", "research", "hot")
QUALITY_DOMAINS = (
    "eastmoney.com", "cninfo.com.cn", "sse.com.cn", "szse.cn", "stcn.com",
    "nbd.com.cn", "caixin.com", "yicai.com", "finance.sina.com.cn",
)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _published_value(item: dict) -> datetime:
    raw = _text(item.get("published_at") or item.get("published_date"))
    if not raw:
        return datetime.min
    raw = raw.replace("T", " ").replace("/", "-").replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d %H:%M", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(raw[:len(datetime.now().strftime(fmt))], fmt)
        except (TypeError, ValueError):
            continue
    return datetime.min


class NewsService:
    """统一新闻服务，负责上游适配、标准化、去重和短缓存。"""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, list[dict]]] = {}
        self._cache_lock = threading.Lock()
        self._ak_lock = threading.Lock()
        self._tushare = None
        self._akshare = None

    def get_feed(
        self,
        category: str = "all",
        *,
        symbol: str = "",
        query: str = "",
        limit: int = 30,
    ) -> dict[str, Any]:
        category = category if category in NEWS_CATEGORIES else "all"
        limit = max(1, min(int(limit), 100))
        key = f"feed:{category}:{symbol.strip()}:{query.strip()}:{limit}"
        cached = self._get_cache(key)
        if cached is not None:
            return self._response(category, cached, cached=True)

        if category == "all":
            items = self._merge(
                self.get_feed("hot", limit=max(10, limit // 2))["news"],
                self.get_feed("stock", symbol=symbol, limit=max(10, limit // 2))["news"] if symbol else [],
            )
        elif category == "hot":
            items = self._hot_news(limit)
        elif category == "realtime":
            items = self._realtime_news(limit)
        elif category == "morning":
            items = self._morning_news(limit)
        elif category == "stock":
            items = self._stock_news(symbol, limit) if symbol else self._hot_news(limit)
        elif category == "announcement":
            items = self._announcement_news(symbol, limit)
        else:
            items = self._research_news(query or symbol or "A股 投资策略", limit)

        items = self._merge(items)[:limit]
        self._set_cache(key, items, 180 if category == "realtime" else 600)
        return self._response(category, items)

    def get_market_context(self, limit: int = 8) -> list[dict]:
        """返回给大盘复盘使用的近期市场新闻。"""
        result = self.get_feed("realtime", limit=limit)["news"]
        return result or self.get_feed("hot", limit=limit)["news"]

    def _response(self, category: str, news: list[dict], *, cached: bool = False) -> dict[str, Any]:
        return {
            "news": news,
            "category": category,
            "total": len(news),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "cached": cached,
        }

    def _get_cache(self, key: str) -> list[dict] | None:
        with self._cache_lock:
            value = self._cache.get(key)
            if not value:
                return None
            expires_at, data = value
            if time.time() >= expires_at:
                self._cache.pop(key, None)
                return None
            return data

    def _set_cache(self, key: str, data: list[dict], ttl: int) -> None:
        with self._cache_lock:
            self._cache[key] = (time.time() + ttl, data)
            if len(self._cache) > 120:
                expired = [k for k, (expires, _) in self._cache.items() if expires <= time.time()]
                for expired_key in expired:
                    self._cache.pop(expired_key, None)

    def _merge(self, *lists: list[dict]) -> list[dict]:
        seen: set[str] = set()
        result: list[dict] = []
        for items in lists:
            for item in items:
                key = item.get("id") or f"{item.get('title')}:{item.get('published_at')}"
                if not item.get("title") or key in seen:
                    continue
                seen.add(key)
                result.append(item)
        result.sort(key=_published_value, reverse=True)
        return result

    def _item(
        self,
        title: Any,
        content: Any,
        source: str,
        source_name: str,
        category: str,
        published_at: Any = "",
        url: Any = "",
    ) -> dict:
        title_s = _text(title)
        published_s = _text(published_at)
        return {
            "id": hashlib.sha1(f"{title_s}:{source}:{published_s}".encode()).hexdigest()[:16],
            "title": title_s,
            "content": _text(content)[:1200],
            "snippet": _text(content)[:360],
            "source": source,
            "source_name": source_name or source,
            "category": category,
            "published_at": published_s,
            "published_date": published_s,
            "url": _text(url),
        }

    def _hot_news(self, limit: int) -> list[dict]:
        df = self._tushare_call("major_news", src="", start_date=self._date(-1), end_date=self._date(0))
        if df is not None and not df.empty:
            result = []
            for row in df.head(limit).to_dict("records"):
                result.append(self._item(row.get("title"), row.get("content"), "tushare", row.get("src", "主流媒体"), "hot", row.get("pub_time"), row.get("url")))
            if result:
                return result

        df = self._ak_call("stock_info_global_cls")
        if df is not None and not df.empty:
            return [
                self._item(
                    row.get("标题", row.get("title")), row.get("摘要", row.get("content")),
                    "akshare", "财联社", "hot", row.get("发布时间", row.get("pub_time")),
                    row.get("链接", row.get("url")),
                )
                for row in df.head(limit).to_dict("records")
            ]
        return self._exa_news("A股 财经市场 最新热点新闻", "hot", limit)

    def _realtime_news(self, limit: int) -> list[dict]:
        df = self._ak_call("stock_info_global_em")
        if df is not None and not df.empty:
            return [
                self._item(row.get("标题"), row.get("摘要"), "akshare", "东方财富", "realtime", row.get("发布时间"), row.get("链接"))
                for row in df.head(limit).to_dict("records")
            ]
        return self._exa_news("A股 全球财经 实时快讯", "realtime", limit)

    def _morning_news(self, limit: int) -> list[dict]:
        df = self._ak_call("stock_info_cjzc_em")
        today = datetime.now().strftime("%Y-%m-%d")
        if df is not None and not df.empty:
            result = []
            for row in df.to_dict("records"):
                published = _text(row.get("发布时间"))
                if published and not published.startswith(today):
                    continue
                result.append(self._item(row.get("标题"), row.get("摘要"), "akshare", "东方财富财经早餐", "morning", published, row.get("链接")))
                if len(result) >= limit:
                    break
            if result:
                return result
        return self._exa_news("A股 今日财经早餐 早间市场", "morning", limit)

    def _stock_news(self, symbol: str, limit: int) -> list[dict]:
        symbol = symbol.strip()
        plain = symbol.split(".", 1)[0]
        df = self._tushare_call("news", src="sina", start_date=self._date_time(-3), end_date=self._date_time(0))
        if df is not None and not df.empty:
            result = []
            for row in df.to_dict("records"):
                title, content = _text(row.get("title")), _text(row.get("content"))
                if plain not in title and plain not in content and symbol not in title and symbol not in content:
                    continue
                result.append(self._item(title, content, "tushare", row.get("src", "新浪财经"), "stock", row.get("datetime"), row.get("url")))
                if len(result) >= limit:
                    return result

        df = self._ak_call("stock_news_em", symbol=plain)
        if df is not None and not df.empty:
            result = [
                self._item(
                    row.get("新闻标题", row.get("标题")),
                    row.get("新闻内容", row.get("内容")),
                    "akshare", "东方财富", "stock",
                    row.get("发布时间", row.get("时间")),
                    row.get("新闻链接", row.get("网址")),
                )
                for row in df.head(limit).to_dict("records")
            ]
            if result:
                return result
        return self._exa_news(f"{symbol} 个股 最新消息 新闻", "stock", limit)

    def _announcement_news(self, symbol: str, limit: int) -> list[dict]:
        if symbol:
            plain = symbol.split(".", 1)[0]
            df = self._ak_call("stock_zh_a_disclosure_report_cninfo", symbol=plain)
            if df is not None and not df.empty:
                return [
                    self._item(row.get("公告标题"), row.get("公告类型"), "cninfo", "巨潮资讯", "announcement", row.get("公告时间"), row.get("网址"))
                    for row in df.head(limit).to_dict("records")
                ]
        query = f"{symbol} 上市公司 公告 披露" if symbol else "A股 上市公司 最新公告"
        return self._exa_news(query, "announcement", limit)

    def _research_news(self, query: str, limit: int) -> list[dict]:
        return self._exa_news(f"{query} 研报 研究报告 券商", "research", limit)

    def _date(self, offset: int) -> str:
        return (datetime.now() + timedelta(days=offset)).strftime("%Y%m%d")

    def _date_time(self, offset: int) -> str:
        return (datetime.now() + timedelta(days=offset)).strftime("%Y%m%d %H:%M:%S")

    def _tushare_call(self, method: str, **kwargs):
        if not settings.tushare_api_token:
            return None
        try:
            if self._tushare is None:
                import tushare as ts
                self._tushare = ts.pro_api(settings.tushare_api_token)
            return getattr(self._tushare, method)(**kwargs)
        except Exception as exc:
            logger.warning("TuShare news call %s failed: %s", method, exc)
            return None

    def _ak_call(self, method: str, **kwargs):
        try:
            # AkShare 1.18.x still uses Python-style ``r"\\u3000"`` regexes.
            # Pandas 3 routes inferred strings through PyArrow, whose regex
            # engine rejects that escape. Keep this compatibility option scoped
            # to the AkShare call and serialize calls because the option is global.
            import pandas as pd
            with self._ak_lock, pd.option_context("future.infer_string", False):
                if self._akshare is None:
                    import akshare as ak
                    self._akshare = ak
                return getattr(self._akshare, method)(**kwargs)
        except Exception as exc:
            logger.warning("AkShare news call %s failed: %s", method, exc)
            return None

    def _exa_news(self, query: str, category: str, limit: int) -> list[dict]:
        domains = " OR ".join(f"site:{domain}" for domain in QUALITY_DOMAINS)
        results = self._exa_search(f"{query} ({domains})", limit)
        return [
            self._item(
                item.get("title"), item.get("content"), "exa", urlparse(_text(item.get("url"))).netloc or "网络搜索", category,
                item.get("published_date"), item.get("url"),
            )
            for item in results
        ]

    def _exa_search(self, query: str, limit: int) -> list[dict]:
        """调用 Exa MCP 的 web_search_exa 工具并兼容 JSON/SSE 返回。"""
        return exa_mcp.search(query, limit)


news_service = NewsService()
