"""行业资金流快照接口。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.services import market_flow
from app.services import watchlist
from app.tickflow.capabilities import Cap

router = APIRouter(prefix="/api/market-flow", tags=["Market Flow"])


@router.get("/industry")
def get_industry_flow(request: Request):
    snapshot = market_flow.read_industry_flow(request.app.state.repo.store.data_dir)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="行业资金流尚未获取")
    return snapshot


@router.get("/industry/history")
def get_industry_flow_history(request: Request, days: int = Query(20, ge=2, le=120)):
    return {"snapshots": market_flow.read_industry_flow_history(request.app.state.repo.store.data_dir, days)}


@router.post("/industry/refresh")
def refresh_industry_flow(request: Request):
    try:
        snapshot = market_flow.refresh_industry_flow(request.app.state.repo.store.data_dir)
    except market_flow.MarketFlowError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return snapshot


@router.get("/concept")
def get_concept_flow(request: Request):
    snapshot = market_flow.read_concept_flow(request.app.state.repo.store.data_dir)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="概念资金流尚未获取")
    return snapshot


@router.get("/concept/history")
def get_concept_flow_history(request: Request, days: int = Query(20, ge=2, le=120)):
    return {"snapshots": market_flow.read_concept_flow_history(request.app.state.repo.store.data_dir, days)}


@router.post("/concept/refresh")
def refresh_concept_flow(request: Request):
    try:
        return market_flow.refresh_concept_flow(request.app.state.repo.store.data_dir)
    except market_flow.MarketFlowError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{plate_id}/stocks")
def get_plate_stocks(plate_id: str, request: Request):
    try:
        symbols = market_flow.fetch_xuangutong_plate_stocks(plate_id)
    except market_flow.MarketFlowError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not symbols:
        return {"stocks": []}

    latest, _ = request.app.state.repo.get_enriched_latest()
    quote_by_symbol = {
        str(row.get("symbol")): {
            "price": row.get("close"),
            "change_amount": row.get("change_amount"),
            "change_pct": row.get("change_pct"),
        }
        for row in latest.to_dicts()
        if row.get("symbol") in symbols
    }
    # 单股行情能力对数百只成分股会触发逐批限流; 仅在真正的批量行情可用时补实时。
    if request.app.state.capabilities.has(Cap.QUOTE_BATCH):
        quotes = watchlist.fetch_quotes(symbols, request.app.state.capabilities)
        quote_by_symbol.update({str(row.get("symbol")): row for row in quotes if row.get("symbol")})
    names = request.app.state.repo.get_name_map(symbols)
    rows = []
    for symbol in symbols:
        quote = quote_by_symbol.get(symbol, {})
        price = quote.get("price") if quote.get("price") is not None else quote.get("last_price")
        pct = quote.get("pct") if quote.get("pct") is not None else quote.get("change_pct")
        rows.append({
            "symbol": symbol,
            "name": quote.get("name") or names.get(symbol) or symbol,
            "price": price,
            "change_amount": quote.get("change_amount"),
            "change_percent": pct,
        })
    rows.sort(key=lambda row: row["change_percent"] if isinstance(row["change_percent"], (int, float)) else -float("inf"), reverse=True)
    return {"stocks": rows}
