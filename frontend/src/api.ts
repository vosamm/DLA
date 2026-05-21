import type { Watch } from './types'

export async function deleteAlerts(ids: number[]): Promise<{ ok: boolean; deleted: number }> {
  const res = await fetch('/api/alerts/', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchAlerts(watchUuid?: string) {
  const url = watchUuid
    ? `/api/alerts/?watch_uuid=${watchUuid}&limit=200`
    : '/api/alerts/?limit=200'
  const res = await fetch(url)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchWatches(): Promise<Watch[]> {
  const res = await fetch('/api/watches/')
  if (!res.ok) throw new Error('fetch watches failed')
  return res.json()
}

export async function createWatch(body: { url: string; title: string }) {
  const res = await fetch('/api/watches/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function updateWatch(
  uuid: string,
  body: { title?: string; crawl_interval_hours?: number | null; next_page_selector?: string | null }
) {
  const res = await fetch(`/api/watches/${uuid}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteWatch(uuid: string) {
  const res = await fetch(`/api/watches/${uuid}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
}


export async function getElementMap(uuid: string): Promise<{
  image: string
  page_height: number
  viewport_width: number
  elements: { selector: string; bbox: { x: number; y: number; w: number; h: number }; text: string }[]
}> {
  const res = await fetch(`/api/watches/${uuid}/element-map`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function triggerCrawl(uuid: string): Promise<{ ok: boolean }> {
  const res = await fetch(`/api/watches/${uuid}/crawl`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}


export async function navigateElementMap(
  uuid: string,
  currentUrl: string,
  nextSelector: string
): Promise<{
  image: string
  page_height: number
  viewport_width: number
  elements: { selector: string; bbox: { x: number; y: number; w: number; h: number }; text: string }[]
  current_url: string
}> {
  const res = await fetch(`/api/watches/${uuid}/element-map/navigate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_url: currentUrl, next_selector: nextSelector }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function analyzeRegion(
  uuid: string,
  region: { x1: number; y1: number; x2: number; y2: number; page_height: number; viewport_width: number },
  elements: { selector: string; bbox: { x: number; y: number; w: number; h: number }; text: string }[]
): Promise<{ css_selector: string | null; next_page_selector: string | null; next_page_image: string | null; titles: string[]; error: string }> {
  const res = await fetch(`/api/watches/${uuid}/analyze-region`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...region, elements }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}
