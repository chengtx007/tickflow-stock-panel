import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as echarts from 'echarts'
import type { ECharts, EChartsOption } from 'echarts'
import { Activity, RefreshCw, X } from 'lucide-react'
import { api, type IndustryFlowSnapshot } from '@/lib/api'
import { fmtBigNum, fmtPct } from '@/lib/format'
import { QK } from '@/lib/queryKeys'

type IndustryFlowRow = IndustryFlowSnapshot['rows'][number]

function fmtFlowAmount(value: number | null | undefined) {
  return fmtBigNum(value == null ? value : Math.abs(value))
}

function FlowTreemap({ rows, history, positive, onSelect }: { rows: IndustryFlowRow[]; history: Map<string, number[]>; positive: boolean; onSelect: (row: IndustryFlowRow) => void }) {
  const chartRef = useRef<HTMLDivElement>(null)
  const chartRefInstance = useRef<ECharts | null>(null)
  const onSelectRef = useRef(onSelect)
  useEffect(() => { onSelectRef.current = onSelect }, [onSelect])
  const maxAbsFlow = Math.max(...rows.map(row => Math.abs(row.fund_flow ?? 0)), 1)
  const option = useMemo<EChartsOption>(() => ({
    animationDurationUpdate: 300,
    tooltip: {
      trigger: 'item', backgroundColor: '#18181d', borderColor: '#34343d', textStyle: { color: '#f4f4f5', fontSize: 12 }, padding: [9, 11],
      formatter: (params: any) => {
        const item = params.data as { flow: number; pct: number; names: string; history: number[] }
        const trend = item.history.length > 1 ? item.history.map(fmtBigNum).join(' → ') : '新数据'
        return [`<strong>${params.name}</strong>`, `资金${item.flow >= 0 ? '流入' : '流出'}：<b style="color:${item.flow >= 0 ? '#ef5a54' : '#22c58b'}">${fmtFlowAmount(item.flow)}</b>`, `板块涨跌：${fmtPct(item.pct)}`, item.names ? `代表股：${item.names}` : '', `资金趋势：${trend}`].filter(Boolean).join('<br/>')
      },
    },
    series: [{
      type: 'treemap', left: 0, right: 0, top: 0, bottom: 0, roam: true, scaleLimit: { min: 1, max: 20 }, nodeClick: false, breadcrumb: { show: false }, sort: 'desc', visibleMin: 1,
      label: {
        show: true, color: '#f8fafc', fontSize: 14, lineHeight: 21, overflow: 'truncate',
        formatter: (params: any) => { const item = params.data as { flow: number; pct: number }; return `{name|${params.name}}\n{flow|${fmtFlowAmount(item.flow)}}\n{${item.pct >= 0 ? 'pctUp' : 'pctDown'}|${fmtPct(item.pct)}}` },
        rich: {
          name: { fontSize: 14, fontWeight: 700, lineHeight: 21, color: '#ffffff' },
          flow: { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 14, fontWeight: 700, lineHeight: 20, color: '#ffffff' },
          pctUp: { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12, fontWeight: 700, color: '#ffffff', backgroundColor: '#c53f43', padding: [2, 4], lineHeight: 20 },
          pctDown: { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12, fontWeight: 700, color: '#ffffff', backgroundColor: '#177a56', padding: [2, 4], lineHeight: 20 },
        },
      },
      itemStyle: { borderColor: '#1b1b20', borderWidth: 1, gapWidth: 1 },
      emphasis: { itemStyle: { borderColor: '#f8fafc', borderWidth: 1 }, label: { color: '#ffffff' } },
      data: rows.map(row => {
        const flow = row.fund_flow ?? 0
        const strength = Math.sqrt(Math.abs(flow) / maxAbsFlow)
        const names = row.top_n_stocks?.items?.slice(0, 2).map(stock => stock.stock_chi_name || stock.symbol).filter(Boolean).join(' · ') ?? ''
        return { name: row.plate_name, plate: row, value: Math.max(Math.abs(flow), maxAbsFlow * 0.002), flow, pct: row.core_avg_pcp ?? 0, names, history: history.get(row.plate_id) ?? [], itemStyle: { color: positive ? `rgba(196, 67, 66, ${0.28 + strength * 0.64})` : `rgba(24, 132, 91, ${0.28 + strength * 0.64})` } }
      }),
    }],
  }), [history, maxAbsFlow, positive, rows])

  useEffect(() => {
    if (!chartRef.current) return
    const chart = echarts.init(chartRef.current, undefined, { renderer: 'canvas' })
    chartRefInstance.current = chart
    chart.on('click', (params: any) => { if (params.data?.plate) onSelectRef.current(params.data.plate) })
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => { window.removeEventListener('resize', resize); chart.dispose(); chartRefInstance.current = null }
  }, [])
  useEffect(() => { chartRefInstance.current?.setOption(option, { notMerge: true }) }, [option])
  return <div ref={chartRef} className="h-[42rem] cursor-grab border border-border bg-[#17171b] active:cursor-grabbing" aria-label={positive ? '资金流入矩形热力图' : '资金流出矩形热力图'} />
}

export function MarketFlow() {
  const qc = useQueryClient()
  const [kind, setKind] = useState<'industry' | 'concept'>('industry')
  const [direction, setDirection] = useState<'inflow' | 'outflow'>('inflow')
  const [selectedPlate, setSelectedPlate] = useState<IndustryFlowRow | null>(null)
  const flow = useQuery({ queryKey: QK.industryFlow, queryFn: api.industryFlow, staleTime: 60_000, retry: false })
  const history = useQuery({ queryKey: QK.industryFlowHistory(20), queryFn: () => api.industryFlowHistory(20), staleTime: 60_000, retry: false })
  const conceptFlow = useQuery({ queryKey: QK.conceptFlow, queryFn: api.conceptFlow, staleTime: 60_000, retry: false })
  const conceptHistory = useQuery({ queryKey: QK.conceptFlowHistory(20), queryFn: () => api.conceptFlowHistory(20), staleTime: 60_000, retry: false })
  const refresh = useMutation({ mutationFn: api.refreshIndustryFlow, onSuccess: () => { qc.invalidateQueries({ queryKey: QK.industryFlow }); qc.invalidateQueries({ queryKey: QK.industryFlowHistory(20) }) } })
  const refreshConcept = useMutation({ mutationFn: api.refreshConceptFlow, onSuccess: () => { qc.invalidateQueries({ queryKey: QK.conceptFlow }); qc.invalidateQueries({ queryKey: QK.conceptFlowHistory(20) }) } })
  const plateStocks = useQuery({ queryKey: ['market-flow-plate-stocks', selectedPlate?.plate_id], queryFn: () => api.marketFlowPlateStocks(selectedPlate!.plate_id), enabled: !!selectedPlate, retry: false })
  useEffect(() => { if (kind === 'concept' && !conceptFlow.data && !refreshConcept.isPending) refreshConcept.mutate() }, [conceptFlow.data, kind, refreshConcept])

  const activeFlow = kind === 'industry' ? flow.data : conceptFlow.data
  const activeHistory = kind === 'industry' ? history.data : conceptHistory.data
  const activeRefresh = kind === 'industry' ? refresh : refreshConcept
  if (!activeFlow?.rows.length) return <div className="grid min-h-full place-items-center bg-base text-sm text-muted">加载{kind === 'industry' ? '行业' : '概念'}资金流…</div>

  const rows = [...activeFlow.rows].sort((a, b) => a.rank - b.rank)
  const inflows = rows.filter(row => (row.fund_flow ?? 0) > 0)
  const outflows = rows.filter(row => (row.fund_flow ?? 0) < 0)
  const inflowTotal = inflows.reduce((sum, row) => sum + (row.fund_flow ?? 0), 0)
  const outflowTotal = Math.abs(outflows.reduce((sum, row) => sum + (row.fund_flow ?? 0), 0))
  const historyById = new Map<string, number[]>()
  for (const daily of activeHistory?.snapshots ?? []) for (const row of daily.rows) if (typeof row.fund_flow === 'number') historyById.set(row.plate_id, [...(historyById.get(row.plate_id) ?? []), row.fund_flow])
  const activeRows = direction === 'inflow' ? inflows : outflows

  return (
    <div className="min-h-full bg-base p-3">
      <section className="border border-border bg-surface/80 p-3 shadow-[0_1px_2px_hsl(var(--border)/0.4)]">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2"><Activity className="h-4 w-4 text-accent" /><div><h1 className="text-sm font-semibold text-foreground">资金流热力图</h1><p className="mt-0.5 font-mono text-[11px] text-muted">{activeFlow.as_of} · {rows.length} 个{kind === 'industry' ? '行业' : '概念'}</p></div></div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-bull">流入 {fmtBigNum(inflowTotal)}</span><span className="font-mono text-xs text-bear">流出 {fmtBigNum(outflowTotal)}</span>
            <button onClick={() => activeRefresh.mutate()} disabled={activeRefresh.isPending} title="刷新板块资金流" className="grid h-7 w-7 place-items-center border border-border text-muted hover:bg-elevated hover:text-accent disabled:opacity-50"><RefreshCw className={`h-3.5 w-3.5 ${activeRefresh.isPending ? 'animate-spin' : ''}`} /></button>
          </div>
        </div>
        <div className="mb-3 flex flex-wrap gap-3 border-b border-border pb-2">
          <div className="flex border border-border"><button onClick={() => setKind('industry')} className={`h-7 px-3 text-xs ${kind === 'industry' ? 'bg-accent text-base' : 'text-muted hover:bg-elevated'}`}>行业</button><button onClick={() => setKind('concept')} className={`h-7 border-l border-border px-3 text-xs ${kind === 'concept' ? 'bg-accent text-base' : 'text-muted hover:bg-elevated'}`}>概念</button></div>
          <div className="flex border border-border"><button onClick={() => setDirection('inflow')} className={`h-7 px-3 text-xs ${direction === 'inflow' ? 'bg-bull text-base' : 'text-muted hover:bg-elevated'}`}>流入 {fmtBigNum(inflowTotal)}</button><button onClick={() => setDirection('outflow')} className={`h-7 border-l border-border px-3 text-xs ${direction === 'outflow' ? 'bg-bear text-base' : 'text-muted hover:bg-elevated'}`}>流出 {fmtBigNum(outflowTotal)}</button></div>
        </div>
        <div><div className="mb-1.5 flex items-baseline justify-between"><h2 className={`text-xs font-semibold ${direction === 'inflow' ? 'text-bull' : 'text-bear'}`}>{kind === 'industry' ? '行业' : '概念'}资金{direction === 'inflow' ? '流入' : '流出'}</h2><span className="font-mono text-[11px] text-muted">{activeRows.length} 个 · {fmtBigNum(direction === 'inflow' ? inflowTotal : outflowTotal)} · 点击板块查看成分股 · 滚轮缩放 · 拖动平移</span></div><FlowTreemap rows={activeRows} history={historyById} positive={direction === 'inflow'} onSelect={setSelectedPlate} /></div>
      </section>
      {selectedPlate && <div className="fixed inset-0 z-50 flex items-center justify-center p-5"><button className="absolute inset-0 bg-black/65" aria-label="关闭成分股窗口" onClick={() => setSelectedPlate(null)} /><section className="relative flex max-h-[85vh] w-full max-w-5xl flex-col border border-border bg-surface shadow-2xl"><header className="flex items-center justify-between border-b border-border px-4 py-3"><div><h2 className="text-sm font-semibold text-foreground">{selectedPlate.plate_name} 成分股</h2><p className="mt-0.5 font-mono text-[11px] text-muted">选股通成分股 · 项目行情报价 · {plateStocks.data?.stocks.length ?? 0} 只</p></div><button onClick={() => setSelectedPlate(null)} title="关闭" className="grid h-8 w-8 place-items-center text-muted hover:bg-elevated hover:text-foreground"><X className="h-4 w-4" /></button></header><div className="min-h-0 overflow-y-auto"><table className="w-full text-left text-xs"><thead className="sticky top-0 bg-elevated text-muted"><tr><th className="px-4 py-2 font-medium">代码</th><th className="px-4 py-2 font-medium">名称</th><th className="px-4 py-2 text-right font-medium">最新价</th><th className="px-4 py-2 text-right font-medium">涨跌额</th><th className="px-4 py-2 text-right font-medium">涨跌幅</th></tr></thead><tbody>{plateStocks.isLoading ? <tr><td colSpan={5} className="px-4 py-10 text-center text-muted">加载成分股与行情…</td></tr> : plateStocks.data?.stocks.map(stock => { const pct = stock.change_percent ?? null; return <tr key={stock.symbol} className="border-t border-border/70 hover:bg-elevated/60"><td className="px-4 py-2 font-mono text-muted">{stock.symbol}</td><td className="px-4 py-2 font-medium text-foreground">{stock.name}</td><td className="px-4 py-2 text-right font-mono text-foreground">{stock.price?.toFixed(2) ?? '—'}</td><td className={`px-4 py-2 text-right font-mono ${pct != null && pct >= 0 ? 'text-bull' : 'text-bear'}`}>{stock.change_amount?.toFixed(2) ?? '—'}</td><td className={`px-4 py-2 text-right font-mono font-semibold ${pct != null && pct >= 0 ? 'text-bull' : 'text-bear'}`}>{pct == null ? '—' : fmtPct(pct)}</td></tr> })}</tbody></table></div></section></div>}
    </div>
  )
}
