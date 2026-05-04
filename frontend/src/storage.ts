const DISMISSED_KEY = 'dismissedAlerts'
const READ_KEY = 'inboxRead'

function load(key: string): Set<number> {
  return new Set(JSON.parse(localStorage.getItem(key) || '[]') as number[])
}

function save(key: string, s: Set<number>) {
  localStorage.setItem(key, JSON.stringify([...s]))
}

export function getDismissed() { return load(DISMISSED_KEY) }
export function addDismissed(id: number) { const s = load(DISMISSED_KEY); s.add(id); save(DISMISSED_KEY, s) }

export function getRead() { return load(READ_KEY) }
export function addRead(id: number) { const s = load(READ_KEY); s.add(id); save(READ_KEY, s) }
export function addReadAll(ids: number[]) {
  const s = load(READ_KEY)
  for (const id of ids) s.add(id)
  save(READ_KEY, s)
}
