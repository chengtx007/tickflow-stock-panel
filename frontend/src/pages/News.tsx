import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Clock3, ExternalLink, Loader2, Newspaper, RefreshCw, Search } from 'lucide-react'
import { api, type NewsItem } from '@/lib/api'
import { PageHeader } from '@/components/PageHeader'
import { cn } from '@/lib/cn'

type NewsCategory = 'all' | 'realtime' | 'morning' | 'stock' | 'announcement' | 'research' | 'hot'

const categories: Array<{ id: NewsCategory; label: string }> = [
  { id: 'all', label: '全部资讯' },
  { id: 'realtime', label: '实时快讯' },
  { id: 'morning', label: '财经早餐' },
  { id: 'stock', label: '个股新闻' },
  { id: 'announcement', label: '公告公示' },
  { id: 'research', label: '研报速递' },
  { id: 'hot', label: '热门资讯' },
]

function formatPublished(value: string) {
  if (!value) return '时间未知'
  const date = new Date(value.replace(/^([0-9]{4})([0-9]{2})([0-9]{2}) /, '$1-$2-$3T'))
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function sourceTone(source: string) {
  const value = source.toLowerCase()
  if (value.includes('东方') || value.includes('east')) return 'text-warning border-warning/30 bg-warning/10'
  if (value.includes('财联') || value.includes('cls')) return 'text-accent border-accent/30 bg-accent/10'
  if (value.includes('新浪') || value.includes('sina')) return 'text-bull border-bull/30 bg-bull/10'
  if (value.includes('巨潮') || value.includes('cninfo')) return 'text-secondary border-border bg-elevated'
  return 'text-muted border-border bg-elevated'
}

function NewsRow({ item, active, onSelect }: { item: NewsItem; active: boolean; onSelect: () => void }) {
  const source = item.source_name || item.source || '未知来源'
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        'w-full border-b border-border/70 px-4 py-3.5 text-left transition-colors',
        active ? 'bg-accent/10' : 'hover:bg-elevated/60',
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <h2 className={cn('min-w-0 text-sm leading-5', active ? 'font-semibold text-foreground' : 'font-medium text-secondary')}>
          {item.title}
        </h2>
        <span className="shrink-0 text-[10px] font-mono text-muted">{formatPublished(item.published_at)}</span>
      </div>
      {(item.snippet || item.content) && (
        <p className="mt-1.5 line-clamp-2 text-xs leading-5 text-muted">{item.snippet || item.content}</p>
      )}
      <div className="mt-2 flex items-center gap-2 text-[10px]">
        <span className={cn('rounded border px-1.5 py-0.5', sourceTone(source))}>{source}</span>
        {item.category && <span className="text-muted">{categories.find(c => c.id === item.category)?.label ?? item.category}</span>}
      </div>
    </button>
  )
}

export function News() {
  const [category, setCategory] = useState<NewsCategory>('all')
  const [symbolInput, setSymbolInput] = useState('')
  const [queryInput, setQueryInput] = useState('')
  const [symbol, setSymbol] = useState('')
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<NewsItem | null>(null)

  const feed = useQuery({
    queryKey: ['news-feed', category, symbol, query],
    queryFn: () => api.newsFeed(category, symbol.trim(), query.trim()),
    staleTime: 120_000,
    placeholderData: previous => previous,
  })

  const items = feed.data?.news ?? []
  const selectedItem = useMemo(
    () => items.find(item => item.id === selected?.id) ?? items[0] ?? null,
    [items, selected?.id],
  )

  useEffect(() => {
    setSelected(items[0] ?? null)
  }, [category, symbol, query, items])

  return (
    <div className="flex h-full min-h-0 flex-col bg-base">
      <PageHeader
        title="新闻资讯"
        subtitle={feed.data ? `${feed.data.total} 条 · 更新于 ${formatPublished(feed.data.updated_at)}` : '联网财经新闻'}
        right={
          <button
            type="button"
            onClick={() => feed.refetch()}
            disabled={feed.isFetching}
            className="inline-flex items-center gap-1.5 rounded-btn border border-border bg-elevated px-3 py-1.5 text-xs text-secondary hover:text-foreground disabled:opacity-50"
            title="刷新新闻"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', feed.isFetching && 'animate-spin')} />刷新
          </button>
        }
      />

      <div className="min-h-0 flex-1 overflow-auto px-4 py-4 sm:px-6">
        <div className="mx-auto flex max-w-[1440px] flex-col gap-3">
          <div className="flex flex-wrap items-center gap-1.5 border-b border-border pb-3">
            {categories.map(item => (
              <button
                key={item.id}
                type="button"
                onClick={() => setCategory(item.id)}
                className={cn(
                  'rounded-btn px-3 py-1.5 text-xs transition-colors',
                  category === item.id ? 'bg-accent text-white' : 'bg-elevated text-secondary hover:text-foreground',
                )}
              >
                {item.label}
              </button>
            ))}
          </div>

          <form
            className="flex flex-wrap gap-2"
            onSubmit={event => {
              event.preventDefault()
              setSymbol(symbolInput.trim())
              setQuery(queryInput.trim())
            }}
          >
            <label className="relative min-w-[12rem] flex-1 sm:max-w-xs">
              <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-muted" />
              <input
                value={queryInput}
                onChange={event => setQueryInput(event.target.value)}
                placeholder="搜索研报或市场新闻"
                className="h-8 w-full rounded-input border border-border bg-surface pl-8 pr-2 text-xs text-foreground outline-none placeholder:text-muted focus:border-accent"
              />
            </label>
            <input
              value={symbolInput}
              onChange={event => setSymbolInput(event.target.value)}
              placeholder="个股代码，如 600519.SH"
              className="h-8 min-w-[12rem] rounded-input border border-border bg-surface px-2.5 text-xs text-foreground outline-none placeholder:text-muted focus:border-accent sm:w-52"
            />
            <button type="submit" className="inline-flex h-8 items-center gap-1.5 rounded-btn bg-accent px-3 text-xs font-medium text-white hover:bg-accent/90">
              <Search className="h-3.5 w-3.5" />查询
            </button>
          </form>

          {(feed.isError || feed.data?.error) && (
            <div className="rounded-card border border-danger/30 bg-danger/10 px-4 py-3 text-xs text-danger">
              新闻源暂时不可用，请稍后刷新。
            </div>
          )}

          <div className="grid min-h-[34rem] grid-cols-1 overflow-hidden rounded-card border border-border bg-surface lg:grid-cols-[minmax(0,1.25fr)_minmax(22rem,0.75fr)]">
            <section className="min-h-0 border-border lg:border-r">
              <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
                <div className="flex items-center gap-2 text-xs font-medium text-foreground">
                  <Newspaper className="h-3.5 w-3.5 text-accent" />资讯列表
                </div>
                {feed.isFetching && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted" />}
              </div>
              <div className="max-h-[calc(100vh-18rem)] overflow-auto">
                {items.length === 0 && !feed.isFetching ? (
                  <div className="grid min-h-64 place-items-center px-6 text-center text-xs text-muted">暂无匹配资讯</div>
                ) : items.map(item => (
                  <NewsRow key={item.id} item={item} active={item.id === selectedItem?.id} onSelect={() => setSelected(item)} />
                ))}
              </div>
            </section>

            <aside className="min-h-[22rem] bg-elevated/20 p-5">
              {selectedItem ? (
                <article>
                  <div className="flex flex-wrap items-center gap-2 text-[10px] text-muted">
                    <span className={cn('rounded border px-1.5 py-0.5', sourceTone(selectedItem.source_name || selectedItem.source))}>
                      {selectedItem.source_name || selectedItem.source}
                    </span>
                    <span className="inline-flex items-center gap-1"><Clock3 className="h-3 w-3" />{formatPublished(selectedItem.published_at)}</span>
                  </div>
                  <h2 className="mt-3 text-base font-semibold leading-6 text-foreground">{selectedItem.title}</h2>
                  <p className="mt-4 whitespace-pre-wrap text-sm leading-7 text-secondary">{selectedItem.content || selectedItem.snippet || '暂无正文摘要。'}</p>
                  {selectedItem.url && (
                    <a
                      href={selectedItem.url}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-6 inline-flex items-center gap-1.5 rounded-btn border border-border bg-surface px-3 py-2 text-xs text-secondary hover:border-accent hover:text-accent"
                    >
                      查看原文 <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                  )}
                </article>
              ) : (
                <div className="grid h-full min-h-64 place-items-center text-xs text-muted">选择一条资讯查看详情</div>
              )}
            </aside>
          </div>
        </div>
      </div>
    </div>
  )
}
