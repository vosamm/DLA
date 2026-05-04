import type { Watch } from './types'

export async function fetchAlerts(watchUuid?: string) {
  const url = watchUuid
    ? `/api/alerts/?watch_uuid=${watchUuid}&limit=200`
    : '/api/alerts/?limit=200'
  const res = await fetch(url)
  if (!res.ok) throw new Error('fetch alerts failed')
  return res.json()
}

export async function fetchWatches(): Promise<Watch[]> {
  const res = await fetch('/api/watches/')
  if (!res.ok) throw new Error('fetch watches failed')
  return res.json()
}

export async function createWatch(body: { url: string; title: string; type: 'content' | 'market' }) {
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
  body: { title?: string; type?: 'content' | 'market'; ignore_top_lines?: number | null }
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
