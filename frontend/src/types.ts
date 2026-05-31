export interface Alert {
  id: number
  watch_uuid: string
  url: string
  type: 'content' | 'market'
  analysis: { title?: string; summary?: string; href?: string }
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
  css_selector: string | null
  next_page_selector: string | null
  last_crawled: number
  crawl_interval_hours: number
}

export interface Toast {
  id: string
  msg: string
  type?: 'error'
}
