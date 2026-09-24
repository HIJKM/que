import type { ItemDetailResponse, ItemListResponse } from '../types';

export type ItemListParams = {
  cursor?: string;
  limit?: number;
  kind?: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: 'same-origin',
    headers: init?.body && !(init.body instanceof FormData)
      ? { 'Content-Type': 'application/json', ...(init.headers || {}) }
      : init?.headers,
    ...init,
  });
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    throw new Error(payload.detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listItems: (params: ItemListParams = {}) => {
    const qs = new URLSearchParams();
    if (params.cursor) qs.set('cursor', params.cursor);
    if (params.limit) qs.set('limit', String(params.limit));
    if (params.kind && params.kind !== 'all') qs.set('kind', params.kind);
    const suffix = qs.toString();
    return request<ItemListResponse>(suffix ? `/api/items?${suffix}` : '/api/items');
  },
  searchItems: (query: string, params: ItemListParams = {}) => {
    const qs = new URLSearchParams({ q: query });
    if (params.cursor) qs.set('cursor', params.cursor);
    if (params.limit) qs.set('limit', String(params.limit));
    if (params.kind && params.kind !== 'all') qs.set('kind', params.kind);
    return request<ItemListResponse>(`/api/items/search?${qs.toString()}`);
  },
  addItem: (url: string) => request<{ id: number; kind: string; status: string; existing: boolean }>('/api/items', {
    method: 'POST',
    body: JSON.stringify({ url }),
  }),
  importItem: (payload: { markdown: string; title: string; url?: string; author?: string; kind?: string }) =>
    request<{ id: number; share_code: string | null; kind: string; status: string; url: string; existing: boolean }>('/api/items/import', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getItem: (id: number, view = 'orig') => request<ItemDetailResponse>(`/api/items/${id}?view=${encodeURIComponent(view)}`),
  getBody: (id: number, view: string) => request<{ html: string; view: string }>(`/api/items/${id}/body?view=${encodeURIComponent(view)}`),
  ingest: (id: number, view: string, target: string) => request<{ ok: boolean; path: string; target: string }>(`/api/items/${id}/ingest`, {
    method: 'POST',
    body: JSON.stringify({ view, target }),
  }),
  deleteItem: (id: number) => request<{ ok: boolean }>(`/api/items/${id}`, { method: 'DELETE' }),
};
