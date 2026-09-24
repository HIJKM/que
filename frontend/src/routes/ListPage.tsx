import { FormEvent, useEffect, useState } from 'react';
import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import type { ItemSummary } from '../types';

const KIND_FILTERS = [
  { value: 'all', label: '전체' },
  { value: 'web', label: 'Web' },
  { value: 'youtube', label: 'YouTube' },
  { value: 'x', label: 'X' },
  { value: 'threads', label: 'Threads' },
  { value: 'brunch', label: 'Brunch' },
  { value: 'md', label: 'Markdown' },
] as const;

function initial(label: string) {
  return label.match(/[A-Za-z0-9가-힣]/)?.[0]?.toUpperCase() || 'Q';
}

function ItemRow({ item }: { item: ItemSummary }) {
  const qc = useQueryClient();
  const prefetch = () => qc.prefetchQuery({ queryKey: ['item', item.id], queryFn: () => api.getItem(item.id, 'orig'), staleTime: 15_000 });
  const author = item.author_display || item.source_host || item.kind_label || 'Que';
  return (
    <div className="item-wrap" data-id={item.id} onMouseEnter={prefetch} onTouchStart={prefetch}>
      <Link className={`item${item.is_unread ? ' unread' : ''}`} to={`/items/${item.id}`}>
        <div className="meta">
          <div className="item-title-row"><div className="title">{item.title || item.url}</div></div>
          <div className="list-author-row">
            <span className="list-author-avatar" aria-hidden="true">{item.author_initial || initial(author)}</span>
            <span className="list-author-name">{author}</span>
            <span className="list-read-meta">{item.read_minutes || 1} min read</span>
            {item.article_date && <><span className="list-dot">·</span><span className="list-read-meta">{item.article_date}</span></>}
          </div>
          <div className="sub">
            <span className="badge kind" title={item.kind_label || item.kind} aria-label={item.kind_label || item.kind} dangerouslySetInnerHTML={{ __html: item.kind_icon_html || item.kind_label || item.kind }} />
            <span className={`badge ${item.status}`}>{item.status}</span>
          </div>
        </div>
      </Link>
    </div>
  );
}

const LIST_PAGE_SIZE = 20;

export function ListPage() {
  const [url, setUrl] = useState('');
  const [toast, setToast] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const [kindFilter, setKindFilter] = useState<(typeof KIND_FILTERS)[number]['value']>('all');
  const [filterOpen, setFilterOpen] = useState(false);
  const [page, setPage] = useState(0);
  const qc = useQueryClient();
  const items = useInfiniteQuery({
    queryKey: ['items', searchQuery, kindFilter],
    queryFn: ({ pageParam }) => {
      const params = { cursor: pageParam, limit: LIST_PAGE_SIZE, kind: kindFilter };
      return searchQuery ? api.searchItems(searchQuery, params) : api.listItems(params);
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => (lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined),
    refetchInterval: (query) => {
      const firstPage = query.state.data?.pages[0];
      return firstPage?.items.some((item) => item.status === 'pending') ? 2000 : false;
    },
  });
  useEffect(() => {
    setPage(0);
  }, [searchQuery, kindFilter]);
  const add = useMutation({
    mutationFn: api.addItem,
    onSuccess: async (item) => {
      setUrl('');
      setToast(item.existing ? '이미 있던 글을 상단으로 올렸습니다.' : '추가됨 — 추출 시작');
      await qc.invalidateQueries({ queryKey: ['items'] });
    },
    onError: (err) => setToast(err instanceof Error ? err.message : '추가 실패'),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (url.trim()) add.mutate(url.trim());
  };
  const submitSearch = (e: FormEvent) => {
    e.preventDefault();
    setSearchQuery(searchInput.trim());
    setSearchOpen(false);
  };
  const clearSearch = () => {
    setSearchInput('');
    setSearchQuery('');
    setSearchOpen(false);
  };
  const pages = items.data?.pages ?? [];
  const totalCount = pages[0]?.total_count ?? 0;
  const pageCount = Math.ceil(totalCount / LIST_PAGE_SIZE);
  const visibleItems = pages[page]?.items ?? [];
  const goToPage = async (nextPage: number) => {
    if (nextPage < 0 || nextPage >= pageCount || items.isFetchingNextPage) return;
    let loadedPages = pages.length;
    let result = items;
    while (loadedPages <= nextPage && result.hasNextPage) {
      result = await items.fetchNextPage();
      loadedPages = result.data?.pages.length ?? loadedPages;
    }
    if (loadedPages > nextPage) {
      setPage(nextPage);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };
  const selectedFilter = KIND_FILTERS.find((filter) => filter.value === kindFilter) || KIND_FILTERS[0];

  return (
    <main className="container">
      <form className="addform" onSubmit={submit}>
        <input type="url" placeholder="URL 붙여넣기 (글 / 유튜브 / X)" value={url} onChange={(e) => setUrl(e.target.value)} required />
        <button className="btn btn-primary" disabled={add.isPending}>{add.isPending ? '추가 중...' : '추가'}</button>
      </form>
      <div className="list-toolbar">
        {searchOpen ? (
          <form className="list-search-form" onSubmit={submitSearch}>
            <input
              type="search"
              aria-label="자료 검색"
              placeholder="제목, 본문, 저자 검색"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              autoFocus
            />
            <button className="list-search-submit icon-only" type="submit" aria-label="검색" title="검색">
              <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" /><path d="m13 13 4 4" /></svg>
            </button>
            <button className="list-search-cancel icon-only" type="button" aria-label="검색 취소" title="취소" onClick={() => setSearchOpen(false)}>
              <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m5 5 10 10M15 5 5 15" /></svg>
            </button>
          </form>
        ) : (
          <button
            className={`list-toolbar-btn icon-only${searchQuery ? ' active' : ''}`}
            type="button"
            aria-label="검색 열기"
            title={searchQuery ? `검색 중: ${searchQuery}` : '검색'}
            onClick={() => setSearchOpen(true)}
          >
            <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" /><path d="m13 13 4 4" /></svg>
          </button>
        )}
        <div className={`kind-filter${filterOpen ? ' open' : ''}`}>
          <button
            className="kind-filter-toggle"
            type="button"
            aria-haspopup="menu"
            aria-expanded={filterOpen}
            onClick={() => setFilterOpen((open) => !open)}
          >
            자료형: {selectedFilter.label}
            <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg>
          </button>
          {filterOpen && (
            <div className="kind-filter-menu" role="menu" aria-label="자료형 필터">
              {KIND_FILTERS.map((filter) => (
                <button
                  key={filter.value}
                  className={`kind-filter-option${kindFilter === filter.value ? ' selected' : ''}`}
                  type="button"
                  role="menuitemradio"
                  aria-checked={kindFilter === filter.value}
                  onClick={() => {
                    setKindFilter(filter.value);
                    setFilterOpen(false);
                  }}
                >
                  <span>{filter.label}</span>
                  {kindFilter === filter.value && <span aria-hidden="true">✓</span>}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="list">
        {items.isLoading && <div className="empty">불러오는 중입니다.</div>}
        {!items.isLoading && !visibleItems.length && (
          <div className="empty">
            {searchQuery ? `“${searchQuery}” 검색 결과가 없습니다.` : '아직 항목이 없습니다. 위에 URL을 붙여넣어 추가하세요.'}
          </div>
        )}
        {visibleItems.map((item) => <ItemRow key={item.id} item={item} />)}
        {pageCount > 1 && (
          <nav className="pagination" aria-label="목록 페이지">
            <button className="pagination-arrow" type="button" disabled={page === 0 || items.isFetchingNextPage} onClick={() => goToPage(page - 1)} aria-label="이전 페이지">‹</button>
            <div className="pagination-pages">
              {Array.from({ length: pageCount }, (_, index) => (
                <button
                  key={index}
                  className={`pagination-page${page === index ? ' active' : ''}`}
                  type="button"
                  aria-current={page === index ? 'page' : undefined}
                  disabled={items.isFetchingNextPage}
                  onClick={() => goToPage(index)}
                >
                  {index + 1}
                </button>
              ))}
            </div>
            <button className="pagination-arrow" type="button" disabled={page >= pageCount - 1 || items.isFetchingNextPage} onClick={() => goToPage(page + 1)} aria-label="다음 페이지">›</button>
          </nav>
        )}
      </div>
      <div className={`toast${toast ? ' show' : ''}`}>{toast}</div>
    </main>
  );
}
