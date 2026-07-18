"""Minimal client for Exa's public MCP web search tool."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class ExaMcpClient:
    """Call Exa's ``web_search_exa`` tool over the MCP HTTP transport."""

    def search(self, query: str, limit: int = 10) -> list[dict[str, str]]:
        try:
            with httpx.Client(timeout=httpx.Timeout(30.0, connect=8.0)) as client:
                url = settings.exa_mcp_url.rstrip("/")
                headers = {
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                    "MCP-Protocol-Version": "2025-03-26",
                }
                init = client.post(url, headers=headers, json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "tickflow-stock-panel", "version": "1.0"},
                    },
                })
                self._parse_mcp(init)
                init.raise_for_status()
                session_id = init.headers.get("Mcp-Session-Id")
                if not session_id:
                    return []

                call_headers = {**headers, "Mcp-Session-Id": session_id}
                client.post(
                    url,
                    headers=call_headers,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                    timeout=20,
                ).raise_for_status()
                response = client.post(
                    url,
                    headers=call_headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {
                            "name": "web_search_exa",
                            "arguments": {
                                "query": query,
                                "numResults": max(1, min(int(limit), 20)),
                            },
                        },
                    },
                )
                return self._extract_results(self._parse_mcp(response))
        except Exception as exc:
            logger.warning("Exa MCP search failed: %s", exc)
            return []

    @staticmethod
    def _parse_mcp(response: httpx.Response) -> dict[str, Any]:
        response.raise_for_status()
        body = response.content.decode("utf-8").strip()
        if body.startswith("{"):
            payload = json.loads(body)
        else:
            data = [line[5:].lstrip() for line in body.splitlines() if line.startswith("data:")]
            payload = json.loads("\n".join(data)) if data else {}
        if payload.get("error"):
            raise RuntimeError(payload["error"].get("message", "Exa MCP error"))
        return payload

    @classmethod
    def _extract_results(cls, payload: dict[str, Any]) -> list[dict[str, str]]:
        result = payload.get("result", {})
        candidates = result.get("structuredContent", {})
        if isinstance(candidates, dict):
            candidates = candidates.get("results", candidates.get("data", []))
        if not isinstance(candidates, list):
            candidates = []

        if not candidates:
            for block in result.get("content", []):
                if block.get("type") != "text":
                    continue
                try:
                    decoded = json.loads(block.get("text", ""))
                    candidates = decoded.get("results", decoded.get("data", [])) if isinstance(decoded, dict) else decoded
                except (TypeError, ValueError):
                    continue
                if isinstance(candidates, list):
                    break

        normalized = []
        for item in candidates if isinstance(candidates, list) else []:
            if isinstance(item, dict):
                normalized.append({
                    "title": str(item.get("title") or item.get("name") or ""),
                    "url": str(item.get("url") or item.get("link") or ""),
                    "content": str(item.get("text") or item.get("snippet") or item.get("content") or ""),
                    "published_date": str(item.get("publishedDate") or item.get("published_date") or ""),
                })
        if normalized:
            return normalized

        # Older Exa MCP responses return a human-readable text block.
        for block in result.get("content", []):
            if block.get("type") != "text":
                continue
            for entry in re.split(r"(?m)^Title:\s*", block.get("text", "")):
                if not entry.strip():
                    continue
                title, _, remainder = entry.partition("\n")
                url_match = re.search(r"(?m)^URL:\s*(\S+)", remainder)
                if not url_match:
                    continue
                published = re.search(r"(?m)^Published:\s*(.+)$", remainder)
                highlights = re.search(r"(?ms)^Highlights:\s*\n?(.*)$", remainder)
                normalized.append({
                    "title": title.strip(),
                    "url": url_match.group(1),
                    "content": highlights.group(1).strip() if highlights else "",
                    "published_date": published.group(1).strip() if published else "",
                })
        return normalized


exa_mcp = ExaMcpClient()
