export interface Alert {
  id: number
  watch_uuid: string
  url: string
  type: 'content' | 'market'
  analysis: { title?: string; summary?: string }
  detail_url: string | null
  changed_at: number
  // client-side state
  read: boolean
  dismissed: boolean
}

export interface Watch {
  uuid: string
  url: string
  title: string
  type: 'content' | 'market'
  ignore_top_lines: number | null
  last_changed: number | null
}

export interface Toast {
  id: string
  msg: string
  type?: 'error'
}
