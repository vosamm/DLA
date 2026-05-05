import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import type { Alert, Watch, Toast } from '../types'
import { Icons } from '../icons'
import { fetchAlerts, fetchWatches, createWatch, updateWatch, deleteWatch } from '../api'
import { getRead, addRead, addReadAll, getDismissed, addDismissed } from '../storage'

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtTime(ts: number): string {
  const diff = Date.now() / 1000 - ts
  if (diff < 60) return '방금'
  if (diff < 3600) return `${Math.floor(diff / 60)}분 전`
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`
  if (diff < 604800) return `${Math.floor(diff / 86400)}일 전`
  return new Date(ts * 1000).toLocaleDateString('ko-KR', { month: 'short', day: 'numeric' })
}

function dateGroupLabel(ts: number): string {
  const d = new Date(ts * 1000)
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const itemDay = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const diff = today.getTime() - itemDay.getTime()
  if (diff <= 0) return '오늘'
  if (diff <= 86400000) return '어제'
  if (diff < 7 * 86400000) return '이번 주'
  return d.toLocaleDateString('ko-KR', { year: 'numeric', month: 'long' })
}

function hostOf(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, '') } catch { return url }
}

function errMsg(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

function typeLabel(type: 'content' | 'market'): string {
  return type === 'content' ? '공지' : '마켓'
}

function scopeWatchUuid(scope: string): string | null {
  return scope.startsWith('watch:') ? scope.slice(6) : null
}

// ─── Hooks ───────────────────────────────────────────────────────────────────

function useEscapeKey(onClose: () => void, enabled = true) {
  useEffect(() => {
    if (!enabled) return
    const handleKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [onClose, enabled])
}

// ─── SiteChip ────────────────────────────────────────────────────────────────

function SiteChip({ type, name, time }: {
  type: 'content' | 'market'
  name: string
  time: number
}) {
  return (
    <>
      <span className="site-chip">
        <span className={`type-dot ${type}`} />
        {name}
      </span>
      <span className="dot-sep" />
      <span className="alert-time">{fmtTime(time)}</span>
    </>
  )
}

// ─── BrandMark ────────────────────────────────────────────────────────────────

function BrandMark() {
  return (
    <div className="brand-mark">
      <div className="dot" />
      <div className="ring" />
      <div className="ring r2" />
    </div>
  )
}

// ─── ToastHost ────────────────────────────────────────────────────────────────

function ToastHost({ toasts }: { toasts: Toast[] }) {
  return (
    <div className="toast-host">
      {toasts.map(t => (
        <div key={t.id} className={`toast show${t.type === 'error' ? ' error' : ''}`}>{t.msg}</div>
      ))}
    </div>
  )
}

// ─── Header ───────────────────────────────────────────────────────────────────

function Header({ unreadCount, totalAlerts, totalWatches, lastUpdated, onRefresh, onManage }: {
  unreadCount: number
  totalAlerts: number
  totalWatches: number
  lastUpdated: Date | null
  onRefresh: () => void
  onManage: () => void
}) {
  return (
    <header className="header">
      <div className="brand">
        <BrandMark />
        Notice Ping
      </div>
      <div className="header-stats">
        <span><span className="stat-num">{unreadCount}</span>읽지 않음</span>
        <div className="sep" />
        <span><span className="stat-num">{totalAlerts}</span>알림</span>
        <div className="sep" />
        <span><span className="stat-num">{totalWatches}</span>모니터</span>
      </div>
      <div className="header-actions">
        {lastUpdated && (
          <span className="last-updated">
            {lastUpdated.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}
          </span>
        )}
        <button className="icon-btn" title="새로고침" onClick={onRefresh}><Icons.Refresh /></button>
        <button className="icon-btn" title="모니터 관리" onClick={onManage}><Icons.Settings /></button>
      </div>
    </header>
  )
}

// ─── NavItem ──────────────────────────────────────────────────────────────────

function NavItem({ id, label, icon, count, typeDot, activeScope, onScope }: {
  id: string
  label: string
  icon?: React.ReactNode
  count?: number
  typeDot?: 'content' | 'market'
  activeScope: string
  onScope: (s: string) => void
}) {
  const hasUnread = (count ?? 0) > 0
  return (
    <div
      className={`nav-item${id === activeScope ? ' active' : ''}${hasUnread ? ' has-unread' : ''}`}
      onClick={() => onScope(id)}
    >
      {typeDot
        ? <span className={`nav-type-dot ${typeDot}`} />
        : icon && <span className="nav-icon">{icon}</span>
      }
      <span className="nav-label">{label}</span>
      {count !== undefined && <span className="nav-count">{count}</span>}
    </div>
  )
}

// ─── Sidebar ──────────────────────────────────────────────────────────────────

function Sidebar({ scope, watches, alerts, onScope }: {
  scope: string
  watches: Watch[]
  alerts: Alert[]
  onScope: (s: string) => void
}) {
  const unreadByWatch = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const a of alerts) {
      if (!a.read && !a.dismissed) {
        counts[a.watch_uuid] = (counts[a.watch_uuid] ?? 0) + 1
      }
    }
    return counts
  }, [alerts])

  const totalUnread = useMemo(
    () => alerts.filter(a => !a.read && !a.dismissed).length,
    [alerts]
  )

  const contentWatches = watches.filter(w => w.type === 'content')
  const marketWatches = watches.filter(w => w.type === 'market')
  const navProps = { activeScope: scope, onScope }

  return (
    <nav className="sidebar">
      <NavItem id="all" label="전체 받은 알림" icon={<Icons.Inbox />} count={totalUnread} {...navProps} />
      <NavItem id="unread" label="읽지 않음" icon={<Icons.Bell />} count={totalUnread} {...navProps} />

      {contentWatches.length > 0 && (
        <>
          <div className="sidebar-section">공지 · 뉴스</div>
          {contentWatches.map(w => (
            <NavItem
              key={w.uuid}
              id={`watch:${w.uuid}`}
              label={w.title || hostOf(w.url)}
              count={unreadByWatch[w.uuid] ?? 0}
              typeDot="content"
              {...navProps}
            />
          ))}
        </>
      )}

      {marketWatches.length > 0 && (
        <>
          <div className="sidebar-section">거래 · 상품</div>
          {marketWatches.map(w => (
            <NavItem
              key={w.uuid}
              id={`watch:${w.uuid}`}
              label={w.title || hostOf(w.url)}
              count={unreadByWatch[w.uuid] ?? 0}
              typeDot="market"
              {...navProps}
            />
          ))}
        </>
      )}

      <div className="sidebar-spacer" />
      <NavItem id="manage" label="모니터 관리" icon={<Icons.Settings />} {...navProps} />
    </nav>
  )
}

// ─── AlertRow ────────────────────────────────────────────────────────────────

function AlertRow({ alert, watchMap, onOpen, onDismiss, onMarkRead }: {
  alert: Alert
  watchMap: Map<string, Watch>
  onOpen: (a: Alert) => void
  onDismiss: (id: number) => void
  onMarkRead: (id: number) => void
}) {
  const watch = watchMap.get(alert.watch_uuid)
  const siteName = watch?.title || hostOf(alert.url)

  function handleClick() {
    onOpen(alert)
    if (!alert.read) onMarkRead(alert.id)
  }

  return (
    <div
      className={`alert-row is-${alert.type} ${alert.read ? 'is-read' : 'is-unread'}`}
      onClick={handleClick}
    >
      <div className="alert-dot" />
      <div className="alert-stripe" />
      <div className="alert-body">
        <div className="alert-meta-row">
          <SiteChip type={alert.type} name={siteName} time={alert.changed_at} />
        </div>
        <div className="alert-title">{alert.analysis.title || siteName}</div>
        {alert.analysis.summary && (
          <div className="alert-summary">{alert.analysis.summary}</div>
        )}
      </div>
      <div className="alert-actions" onClick={e => e.stopPropagation()}>
        {!alert.read && (
          <button className="icon-btn" title="읽음 표시" onClick={() => onMarkRead(alert.id)}>
            <Icons.Check />
          </button>
        )}
        <button className="icon-btn" title="닫기" onClick={() => onDismiss(alert.id)}>
          <Icons.X />
        </button>
      </div>
    </div>
  )
}

// ─── Inbox ───────────────────────────────────────────────────────────────────

function Inbox({ alerts, watchMap, scope, onOpen, onDismiss, onMarkRead, onMarkAllRead }: {
  alerts: Alert[]
  watchMap: Map<string, Watch>
  scope: string
  onOpen: (a: Alert) => void
  onDismiss: (id: number) => void
  onMarkRead: (id: number) => void
  onMarkAllRead: () => void
}) {
  const uuid = scopeWatchUuid(scope)

  const filtered = useMemo(() => {
    const base = alerts.filter(a => !a.dismissed)
    if (scope === 'unread') return base.filter(a => !a.read)
    if (uuid) return base.filter(a => a.watch_uuid === uuid)
    return base
  }, [alerts, scope, uuid])

  const groups = useMemo(() => {
    const result: { label: string; items: Alert[] }[] = []
    for (const a of filtered) {
      const label = dateGroupLabel(a.changed_at)
      const last = result[result.length - 1]
      if (last?.label === label) last.items.push(a)
      else result.push({ label, items: [a] })
    }
    return result
  }, [filtered])

  const unreadCount = useMemo(() => filtered.filter(a => !a.read).length, [filtered])

  const watch = uuid ? watchMap.get(uuid) : undefined
  const title = scope === 'unread' ? '읽지 않음'
    : uuid ? (watch?.title || (watch ? hostOf(watch.url) : '알림'))
    : '전체 받은 알림'
  const scopeBadge = uuid ? typeLabel(watch?.type ?? 'content') : null

  return (
    <>
      <div className="main-header">
        <div className="main-title">
          {title}
          {scopeBadge && <span className="scope-badge">{scopeBadge}</span>}
        </div>
        {unreadCount > 0 && (
          <div className="main-actions">
            <button className="btn ghost" onClick={onMarkAllRead}>
              <Icons.CheckAll /> 모두 읽음
            </button>
          </div>
        )}
      </div>
      <div className="inbox">
        {filtered.length === 0 ? (
          <div className="empty">
            <div className="empty-mark"><Icons.Inbox /></div>
            <h3>알림 없음</h3>
            <p>새로운 변경 사항이 감지되면 여기에 표시됩니다.</p>
          </div>
        ) : (
          groups.map(g => (
            <div key={g.label}>
              <div className="date-divider">{g.label}</div>
              {g.items.map(a => (
                <AlertRow
                  key={a.id}
                  alert={a}
                  watchMap={watchMap}
                  onOpen={onOpen}
                  onDismiss={onDismiss}
                  onMarkRead={onMarkRead}
                />
              ))}
            </div>
          ))
        )}
      </div>
    </>
  )
}

// ─── DetailDrawer ─────────────────────────────────────────────────────────────

function DetailDrawer({ alert, watchMap, onClose, onDismiss }: {
  alert: Alert | null
  watchMap: Map<string, Watch>
  onClose: () => void
  onDismiss: (id: number) => void
}) {
  const isOpen = alert !== null

  useEscapeKey(onClose, isOpen)

  const watch = alert ? watchMap.get(alert.watch_uuid) : null
  const siteName = alert ? (watch?.title || hostOf(alert.url)) : ''

  return (
    <>
      <div className={`detail-overlay${isOpen ? ' open' : ''}`} onClick={onClose} />
      <div className={`detail-drawer${isOpen ? ' open' : ''}`}>
        {alert && (
          <>
            <div className="detail-header">
              <div className="detail-meta">
                <SiteChip type={alert.type} name={siteName} time={alert.changed_at} />
              </div>
              <div className="detail-header-actions">
                <a href={alert.detail_url || alert.url} target="_blank" rel="noopener noreferrer" className="icon-btn" title="원문 보기">
                  <Icons.External />
                </a>
                <button className="icon-btn" title="닫기" onClick={onClose}><Icons.X /></button>
              </div>
            </div>
            <div className="detail-body">
              <h2>{alert.analysis.title || siteName}</h2>
              {alert.analysis.summary && (
                <div className="summary">{alert.analysis.summary}</div>
              )}
            </div>
            <div className="detail-footer">
              <button className="btn danger" onClick={() => { onDismiss(alert.id); onClose() }}>
                <Icons.X /> 닫기
              </button>
              <a href={alert.detail_url || alert.url} target="_blank" rel="noopener noreferrer" className="btn primary">
                <Icons.External /> 원문 보기
              </a>
            </div>
          </>
        )}
      </div>
    </>
  )
}

// ─── VisualFilterModal ───────────────────────────────────────────────────────

function VisualFilterModal({ uuid, title, onClose }: {
  uuid: string
  title: string
  onClose: () => void
}) {
  const cdBase = `${window.location.protocol}//${window.location.hostname}:5000`
  const url = `${cdBase}/edit/${uuid}#visualselector`

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [onClose])

  return (
    <div className="vf-overlay" onClick={onClose}>
      <div className="vf-modal" onClick={e => e.stopPropagation()}>
        <div className="vf-header">
          <div className="vf-title">
            <Icons.Eye />
            시각적 필터 — {title}
          </div>
          <button className="icon-btn" title="닫기 (Esc)" onClick={onClose}>
            <Icons.X />
          </button>
        </div>
        <iframe
          className="vf-frame"
          src={url}
          title="시각적 필터"
          allow="same-origin"
        />
      </div>
    </div>
  )
}

// ─── ManagePanel ─────────────────────────────────────────────────────────────

function ManagePanel({ watches, onReload, onToast }: {
  watches: Watch[]
  onReload: () => void
  onToast: (msg: string, type?: 'error') => void
}) {
  const [addUrl, setAddUrl] = useState('')
  const [addTitle, setAddTitle] = useState('')
  const [addType, setAddType] = useState<'content' | 'market'>('content')
  const [adding, setAdding] = useState(false)
  const [editingUuid, setEditingUuid] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [editType, setEditType] = useState<'content' | 'market'>('content')
  const [editIgnore, setEditIgnore] = useState('')
  const [filterWatch, setFilterWatch] = useState<Watch | null>(null)

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    if (!addUrl.trim()) return
    setAdding(true)
    try {
      await createWatch({ url: addUrl.trim(), title: addTitle.trim() || addUrl.trim(), type: addType })
      setAddUrl('')
      setAddTitle('')
      setAddType('content')
      onReload()
      onToast('모니터가 추가되었습니다.')
    } catch (err) {
      onToast(errMsg(err), 'error')
    } finally {
      setAdding(false)
    }
  }

  function startEdit(w: Watch) {
    setEditingUuid(w.uuid)
    setEditTitle(w.title)
    setEditType(w.type)
    setEditIgnore(w.ignore_top_lines !== null ? String(w.ignore_top_lines) : '')
  }

  async function handleSave(uuid: string) {
    try {
      await updateWatch(uuid, {
        title: editTitle,
        type: editType,
        ignore_top_lines: editIgnore !== '' ? Number(editIgnore) : null,
      })
      setEditingUuid(null)
      onReload()
      onToast('저장되었습니다.')
    } catch (err) {
      onToast(errMsg(err), 'error')
    }
  }

  async function handleDelete(uuid: string) {
    if (!confirm('이 모니터를 삭제할까요?')) return
    try {
      await deleteWatch(uuid)
      onReload()
      onToast('삭제되었습니다.')
    } catch (err) {
      onToast(errMsg(err), 'error')
    }
  }

  return (
    <>
      <div className="main-header">
        <div className="main-title">모니터 관리</div>
        <div className="main-actions">
          <span className="watch-count-label">{watches.length}개 모니터링 중</span>
        </div>
      </div>
      <div className="manage">
        <form className="add-form" onSubmit={handleAdd}>
          <div className="field">
            <label>URL</label>
            <input type="url" placeholder="https://example.com" value={addUrl} onChange={e => setAddUrl(e.target.value)} required />
          </div>
          <div className="field">
            <label>이름 (선택)</label>
            <input type="text" placeholder="사이트 이름" value={addTitle} onChange={e => setAddTitle(e.target.value)} />
          </div>
          <div className="field">
            <label>유형</label>
            <select value={addType} onChange={e => setAddType(e.target.value as 'content' | 'market')}>
              <option value="content">공지 · 뉴스</option>
              <option value="market">거래 · 상품</option>
            </select>
          </div>
          <button className="btn primary" type="submit" disabled={adding}>
            <Icons.Plus /> 추가
          </button>
        </form>

        <div className="watch-list">
          {watches.length === 0 && (
            <div className="empty">
              <div className="empty-mark"><Icons.Eye /></div>
              <h3>모니터 없음</h3>
              <p>위 폼에서 새 모니터를 추가하세요.</p>
            </div>
          )}
          {watches.map(w => (
            <div className="watch-card" key={w.uuid}>
              <div className="watch-row">
                <div className="watch-info">
                  <span className={`watch-type-pill ${w.type}`}>{typeLabel(w.type)}</span>
                  <div className="watch-text">
                    <div className="watch-title">{w.title || hostOf(w.url)}</div>
                    <a className="watch-url" href={w.url} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}>
                      {w.url}
                    </a>
                  </div>
                </div>
                <div className="watch-actions">
                  <button className="icon-btn" title="시각적 필터" onClick={() => setFilterWatch(w)}>
                    <Icons.Eye />
                  </button>
                  <button className="icon-btn" title="설정" onClick={() => editingUuid === w.uuid ? setEditingUuid(null) : startEdit(w)}>
                    <Icons.Edit />
                  </button>
                  <button className="icon-btn" title="삭제" onClick={() => handleDelete(w.uuid)}>
                    <Icons.Trash />
                  </button>
                </div>
              </div>
              {editingUuid === w.uuid && (
                <div className="settings-panel">
                  <div className="field">
                    <label>이름</label>
                    <input type="text" value={editTitle} onChange={e => setEditTitle(e.target.value)} />
                  </div>
                  <div className="field">
                    <label>유형</label>
                    <select value={editType} onChange={e => setEditType(e.target.value as 'content' | 'market')}>
                      <option value="content">공지 · 뉴스</option>
                      <option value="market">거래 · 상품</option>
                    </select>
                  </div>
                  <div className="field">
                    <label>상단 무시 줄 수</label>
                    <input type="number" min="0" placeholder="0" value={editIgnore} onChange={e => setEditIgnore(e.target.value)} />
                  </div>
                  <div className="save-actions">
                    <button className="btn primary" onClick={() => handleSave(w.uuid)}><Icons.Check /> 저장</button>
                    <button className="btn ghost" onClick={() => setEditingUuid(null)}>취소</button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
      {filterWatch && (
        <VisualFilterModal
          uuid={filterWatch.uuid}
          title={filterWatch.title || hostOf(filterWatch.url)}
          onClose={() => setFilterWatch(null)}
        />
      )}
    </>
  )
}

// ─── InboxApp ────────────────────────────────────────────────────────────────

export function InboxApp() {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [watches, setWatches] = useState<Watch[]>([])
  const [scope, setScope] = useState('all')
  const [detail, setDetail] = useState<Alert | null>(null)
  const [toasts, setToasts] = useState<Toast[]>([])
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const toastTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())

  const watchMap = useMemo(() => new Map(watches.map(w => [w.uuid, w])), [watches])
  const unreadCount = useMemo(() => alerts.filter(a => !a.read && !a.dismissed).length, [alerts])
  const totalAlerts = useMemo(() => alerts.filter(a => !a.dismissed).length, [alerts])

  function showToast(msg: string, type?: 'error') {
    const id = crypto.randomUUID()
    setToasts(prev => [...prev, { id, msg, type }])
    const timer = setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id))
      toastTimers.current.delete(id)
    }, 3000)
    toastTimers.current.set(id, timer)
  }

  const loadData = useCallback(async () => {
    try {
      const [rawAlerts, rawWatches] = await Promise.all([fetchAlerts(), fetchWatches()])
      const readSet = getRead()
      const dismissedSet = getDismissed()
      const enriched: Alert[] = (rawAlerts as Omit<Alert, 'read' | 'dismissed'>[])
        .map(a => ({ ...a, read: readSet.has(a.id), dismissed: dismissedSet.has(a.id) }))
        .sort((a, b) => b.changed_at - a.changed_at)
      setAlerts(enriched)
      setWatches(rawWatches)
      setLastUpdated(new Date())
    } catch (err) {
      showToast(errMsg(err), 'error')
    }
  }, [])

  useEffect(() => { loadData() }, [loadData])

  useEffect(() => {
    const id = setInterval(loadData, 30000)
    return () => clearInterval(id)
  }, [loadData])

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement).tagName
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(tag)) return
      if (e.key === 'r') loadData()
      else if (e.key === '1') setScope('all')
      else if (e.key === '2') setScope('unread')
      else if (e.key === 'g') setScope('manage')
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [loadData])

  useEffect(() => {
    const timers = toastTimers.current
    return () => timers.forEach(t => clearTimeout(t))
  }, [])

  function markRead(id: number) {
    addRead(id)
    setAlerts(prev => prev.map(a => a.id === id ? { ...a, read: true } : a))
  }

  function dismiss(id: number) {
    addDismissed(id)
    setAlerts(prev => prev.map(a => a.id === id ? { ...a, dismissed: true } : a))
  }

  function markAllRead() {
    const uuid = scopeWatchUuid(scope)
    const ids = alerts
      .filter(a => !a.dismissed && !a.read && (uuid === null || a.watch_uuid === uuid))
      .map(a => a.id)
    if (ids.length === 0) return
    addReadAll(ids)
    const idSet = new Set(ids)
    setAlerts(prev => prev.map(a => idSet.has(a.id) ? { ...a, read: true } : a))
  }

  async function reloadWatches() {
    try {
      setWatches(await fetchWatches())
    } catch (err) {
      showToast(errMsg(err), 'error')
    }
  }

  return (
    <div className="app">
      <Header
        unreadCount={unreadCount}
        totalAlerts={totalAlerts}
        totalWatches={watches.length}
        lastUpdated={lastUpdated}
        onRefresh={loadData}
        onManage={() => setScope('manage')}
      />
      <Sidebar scope={scope} watches={watches} alerts={alerts} onScope={setScope} />
      <main className="main">
        {scope === 'manage' ? (
          <ManagePanel watches={watches} onReload={reloadWatches} onToast={showToast} />
        ) : (
          <Inbox
            alerts={alerts}
            watchMap={watchMap}
            scope={scope}
            onOpen={setDetail}
            onDismiss={dismiss}
            onMarkRead={markRead}
            onMarkAllRead={markAllRead}
          />
        )}
      </main>
      <DetailDrawer alert={detail} watchMap={watchMap} onClose={() => setDetail(null)} onDismiss={dismiss} />
      <ToastHost toasts={toasts} />
    </div>
  )
}
