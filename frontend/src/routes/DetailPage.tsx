import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Archive, ClipboardCheck, ClipboardPen, Copy, Database, ExternalLink, FileText, Link2, Share2, Trash2, X } from 'lucide-react';
import { api } from '../lib/api';
import { MarkdownBody } from '../components/MarkdownBody';
import type { IngestTarget } from '../types';

function useActionbarMotion(active: boolean, suppressResizeUntil: { current: number }) {
  useEffect(() => {
    if (!active) return;
    const bar = document.getElementById('actionbar');
    if (!bar) return;

    let lastY = window.scrollY;
    let ticking = false;
    let dragPointerId: number | null = null;
    let dragStartY = 0;
    let dragStartX = 0;
    let trackingBar = false;
    let draggingBar = false;
    let dragMoved = false;
    let suppressNextClick = false;

    const updateBarDrag = (clientX: number, clientY: number, event?: Event) => {
      if (!trackingBar) return;
      const dy = clientY - dragStartY;
      const dx = clientX - dragStartX;
      const distance = Math.hypot(dx, dy);
      if (distance <= 4 && !draggingBar) return;
      dragMoved = true;
      if (!draggingBar) {
        draggingBar = true;
        bar.classList.add('dragging');
      }
      const pull = Math.max(-34, Math.min(34, dy * 0.46));
      const stretch = Math.min(0.065, distance * 0.0022);
      bar.style.setProperty('--bar-drag-y', `${pull}px`);
      bar.style.setProperty('--bar-scale-x', String(1 + stretch));
      bar.style.setProperty('--bar-scale-y', String(1 + stretch * 0.55));
      if (dragMoved && event?.cancelable) event.preventDefault();
    };

    const onPointerMove = (event: PointerEvent) => {
      if (event.pointerId !== dragPointerId) return;
      updateBarDrag(event.clientX, event.clientY, event);
    };
    const onTouchMove = (event: TouchEvent) => {
      const touch = event.touches?.[0];
      if (touch) updateBarDrag(touch.clientX, touch.clientY, event);
    };
    const resetBarDrag = (event?: PointerEvent | TouchEvent) => {
      if (event instanceof PointerEvent && dragPointerId !== null && event.pointerId !== dragPointerId) return;
      document.removeEventListener('pointermove', onPointerMove, true);
      document.removeEventListener('pointerup', resetBarDrag as EventListener, true);
      document.removeEventListener('pointercancel', resetBarDrag as EventListener, true);
      document.removeEventListener('touchmove', onTouchMove, true);
      document.removeEventListener('touchend', resetBarDrag as EventListener, true);
      document.removeEventListener('touchcancel', resetBarDrag as EventListener, true);
      if (dragMoved) {
        suppressNextClick = true;
        window.setTimeout(() => { suppressNextClick = false; }, 160);
      }
      dragPointerId = null;
      trackingBar = false;
      draggingBar = false;
      dragMoved = false;
      bar.classList.remove('dragging');
      bar.style.setProperty('--bar-drag-y', '0px');
      bar.style.setProperty('--bar-scale-x', '1');
      bar.style.setProperty('--bar-scale-y', '1');
    };
    const onPointerDown = (event: PointerEvent) => {
      if (event.button !== undefined && event.button !== 0) return;
      dragPointerId = event.pointerId;
      dragStartY = event.clientY;
      dragStartX = event.clientX;
      trackingBar = true;
      draggingBar = false;
      dragMoved = false;
      document.addEventListener('pointermove', onPointerMove, true);
      document.addEventListener('pointerup', resetBarDrag as EventListener, true);
      document.addEventListener('pointercancel', resetBarDrag as EventListener, true);
    };
    const onTouchStart = (event: TouchEvent) => {
      if (window.PointerEvent) return;
      const touch = event.touches?.[0];
      if (!touch) return;
      dragPointerId = null;
      dragStartY = touch.clientY;
      dragStartX = touch.clientX;
      trackingBar = true;
      draggingBar = false;
      dragMoved = false;
      document.addEventListener('touchmove', onTouchMove, { capture: true, passive: false });
      document.addEventListener('touchend', resetBarDrag as EventListener, true);
      document.addEventListener('touchcancel', resetBarDrag as EventListener, true);
    };
    const onClick = (event: MouseEvent) => {
      if (!suppressNextClick) return;
      event.preventDefault();
      event.stopPropagation();
    };
    const onScroll = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        const y = window.scrollY;
        if (performance.now() >= suppressResizeUntil.current) {
          if (y > lastY + 2 && y > 48) bar.classList.add('compact');
          else if (y < lastY - 2) bar.classList.remove('compact');
        }
        lastY = y;
        ticking = false;
      });
    };

    bar.addEventListener('pointerdown', onPointerDown, { capture: true });
    bar.addEventListener('touchstart', onTouchStart, { capture: true, passive: true });
    bar.addEventListener('click', onClick, true);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      bar.removeEventListener('pointerdown', onPointerDown, true);
      bar.removeEventListener('touchstart', onTouchStart, true);
      bar.removeEventListener('click', onClick, true);
      window.removeEventListener('scroll', onScroll);
      resetBarDrag();
    };
  }, [active, suppressResizeUntil]);
}

type FloatingPillPosition = { left: number; bottom: number };

function floatingPillStyle(position: FloatingPillPosition | null): React.CSSProperties {
  return position ? { left: position.left, bottom: position.bottom } : {};
}

function ActionPill({ children, className = '', role = 'menu', ariaLabel, ariaLive, pillRef, style, ariaHidden }: { children: React.ReactNode; className?: string; role?: string; ariaLabel: string; ariaLive?: 'off' | 'polite' | 'assertive'; pillRef?: React.Ref<HTMLDivElement>; style?: React.CSSProperties; ariaHidden?: boolean }) {
  return (
    <div ref={pillRef} className={`share-pill${className ? ` ${className}` : ''}`} role={role} aria-label={ariaLabel} aria-live={ariaLive} aria-hidden={ariaHidden} style={style}>
      {children}
    </div>
  );
}

function Modal({ open, title, description, children, onClose, initialFocus }: { open: boolean; title: string; description: string; children: React.ReactNode; onClose: () => void; initialFocus?: string }) {
  const lastFocus = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    lastFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    document.body.classList.add('modal-open');
    const focusTimer = window.setTimeout(() => {
      const target = initialFocus ? document.querySelector<HTMLElement>(initialFocus) : null;
      target?.focus?.();
    }, 0);
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onCloseRef.current(); };
    document.addEventListener('keydown', onKey);
    return () => {
      window.clearTimeout(focusTimer);
      document.body.classList.remove('modal-open');
      document.removeEventListener('keydown', onKey);
      lastFocus.current?.focus?.();
    };
  }, [initialFocus, open]);

  if (!open) return null;
  return (
    <div className="modal-backdrop" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="modal-card" role="dialog" aria-modal="true" aria-labelledby="modalTitle" aria-describedby="modalDesc">
        <div className="modal-head">
          <h2 id="modalTitle">{title}</h2>
          <button className="modal-close" type="button" onClick={onClose} aria-label="닫기"><X size={18} /></button>
        </div>
        <p id="modalDesc">{description}</p>
        {children}
      </div>
    </div>
  );
}

function targetLabel(targets: IngestTarget[], key: string) {
  return targets.find((target) => target.key === key)?.label || key || 'Quartz';
}

type ScrollAnchor =
  | { type: 'pixel'; probeY: number; fallbackY: number }
  | { type: 'youtube-time'; sec: number; ratio: number; probeY: number; fallbackY: number }
  | { type: 'block'; index: number; progress: number; ratio: number; probeY: number; fallbackY: number };

function readerEl() {
  return document.querySelector<HTMLElement>('article.reader');
}

function scrollProbeY(reader: HTMLElement | null) {
  const sticky = reader?.querySelector<HTMLElement>('.yt-sticky');
  const rect = sticky?.getBoundingClientRect();
  if (rect && rect.bottom > 80 && rect.top < window.innerHeight) {
    return Math.min(window.innerHeight - 24, rect.bottom + 14);
  }
  return Math.min(window.innerHeight - 24, 96);
}

function captionRowFor(button: Element) {
  return button.closest('p, li, blockquote, .chain-body') || button.parentElement;
}

function captionTime(button: HTMLElement) {
  const dataTime = parseInt(button.dataset.t || '', 10);
  if (!Number.isNaN(dataTime)) return dataTime;
  if (!button.classList.contains('yt-sentence')) return Number.NaN;
  try {
    const url = new URL(button.getAttribute('href') || '', window.location.href);
    return parseInt(url.searchParams.get('t') || url.hash.match(/^#yt-t=(\d+)$/)?.[1] || '', 10);
  } catch {
    return Number.NaN;
  }
}

function visibleBlockCandidates(root: HTMLElement | null) {
  if (!root) return [] as Element[];
  const selector = ['p', 'h1', 'h2', 'h3', 'h4', 'li', 'blockquote', 'pre', 'table', 'img', '.bookmark-card', '.quote-card', '.twitter-tweet'].join(',');
  return Array.from(root.querySelectorAll(selector)).filter((el) => {
    if (el.closest('.yt-sticky')) return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  });
}

function nearestByProbe<T>(items: T[], probeY: number, rectFor: (item: T) => DOMRect | null | undefined): { item: T; rect: DOMRect } | null {
  let best: { item: T; rect: DOMRect } | null = null;
  let bestDistance = Infinity;
  for (const item of items) {
    const rect = rectFor(item);
    if (!rect || rect.width <= 0 || rect.height <= 0) continue;
    const distance = rect.top <= probeY && rect.bottom >= probeY
      ? 0
      : Math.min(Math.abs(rect.top - probeY), Math.abs(rect.bottom - probeY));
    if (distance < bestDistance) {
      best = { item, rect };
      bestDistance = distance;
    }
  }
  return best;
}

function captureScrollAnchor(): ScrollAnchor {
  const reader = readerEl();
  const probeY = scrollProbeY(reader);
  const fallbackY = window.scrollY;
  const timestampItems = Array.from(reader?.querySelectorAll<HTMLElement>('.yt-ts, .yt-sentence[href], .yt-sentence[data-t]') || [])
    .map((button) => ({ button, row: captionRowFor(button), sec: captionTime(button) }))
    .filter((item): item is { button: HTMLElement; row: Element; sec: number } => Boolean(item.row) && !Number.isNaN(item.sec));
  const timestampAnchor = nearestByProbe(timestampItems, probeY, (item) => item.row.getBoundingClientRect());
  if (timestampAnchor) {
    return {
      type: 'youtube-time',
      sec: timestampAnchor.item.sec,
      ratio: (probeY - timestampAnchor.rect.top) / Math.max(1, timestampAnchor.rect.height),
      probeY,
      fallbackY,
    };
  }

  const blocks = visibleBlockCandidates(reader);
  const blockAnchor = nearestByProbe(blocks, probeY, (el) => el.getBoundingClientRect());
  if (!blockAnchor) return { type: 'pixel', probeY, fallbackY };
  const index = blocks.indexOf(blockAnchor.item);
  return {
    type: 'block',
    index,
    progress: blocks.length > 1 ? index / (blocks.length - 1) : 0,
    ratio: (probeY - blockAnchor.rect.top) / Math.max(1, blockAnchor.rect.height),
    probeY,
    fallbackY,
  };
}

function scrollToElementRatio(el: Element | null | undefined, ratio: number, probeY: number, fallbackY: number) {
  if (!el) {
    window.scrollTo(0, fallbackY);
    return false;
  }
  const rect = el.getBoundingClientRect();
  const docTop = rect.top + window.scrollY;
  const offset = Math.max(0, Math.min(1, Number(ratio) || 0)) * rect.height;
  window.scrollTo(0, Math.max(0, docTop + offset - probeY));
  return true;
}

function restoreScrollAnchor(anchor: ScrollAnchor | null) {
  const reader = readerEl();
  if (!anchor || anchor.type === 'pixel') {
    window.scrollTo(0, anchor?.fallbackY || 0);
    return;
  }
  if (anchor.type === 'youtube-time') {
    const match = Array.from(reader?.querySelectorAll<HTMLElement>('.yt-ts, .yt-sentence[href], .yt-sentence[data-t]') || [])
      .find((button) => captionTime(button) === anchor.sec);
    if (match && scrollToElementRatio(captionRowFor(match), anchor.ratio, scrollProbeY(reader), anchor.fallbackY)) return;
  }
  if (anchor.type === 'block') {
    const blocks = visibleBlockCandidates(reader);
    const index = anchor.index < blocks.length
      ? anchor.index
      : Math.round((anchor.progress || 0) * Math.max(0, blocks.length - 1));
    if (scrollToElementRatio(blocks[index], anchor.ratio, anchor.probeY, anchor.fallbackY)) return;
  }
  window.scrollTo(0, anchor.fallbackY || 0);
}

export function DetailPage() {
  const params = useParams();
  const id = Number(params.id);
  const view = 'orig';
  const [toast, setToast] = useState('');
  const [ingestOpen, setIngestOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [selectedTarget, setSelectedTarget] = useState('');
  const [markdownCopied, setMarkdownCopied] = useState(false);
  const [sourceCopied, setSourceCopied] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [shareCopied, setShareCopied] = useState<'markdown' | 'source' | 'lookup' | ''>('');
  const [floatingPills, setFloatingPills] = useState<{ share: FloatingPillPosition | null }>({ share: null });
  const shareRef = useRef<HTMLDivElement | null>(null);
  const shareButtonRef = useRef<HTMLButtonElement | null>(null);
  const sharePillRef = useRef<HTMLDivElement | null>(null);
  const pendingScrollAnchor = useRef<ScrollAnchor | null>(null);
  const suppressActionbarResizeUntil = useRef(0);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const detail = useQuery({
    queryKey: ['item', id],
    queryFn: () => api.getItem(id, view),
    enabled: Number.isFinite(id),
    placeholderData: keepPreviousData,
    refetchInterval: (query) => {
      const data = query.state.data;
      return data?.item.status === 'pending' ? 2500 : false;
    },
  });
  const item = detail.data?.item;
  const targets = detail.data?.ingest_targets || [];
  const defaultTarget = useMemo(() => targets.find((target) => target.default && !target.ingested)?.key || targets.find((target) => !target.ingested)?.key || '', [targets]);

  useActionbarMotion(Boolean(item), suppressActionbarResizeUntil);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(''), 1800);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    if (!shareOpen) return;
    const close = (event: PointerEvent) => {
      if (shareRef.current?.contains(event.target as Node)) return;
      if (sharePillRef.current?.contains(event.target as Node)) return;
      setShareOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setShareOpen(false);
    };
    document.addEventListener('pointerdown', close);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', close);
      document.removeEventListener('keydown', onKey);
    };
  }, [shareOpen]);

  const positionForButton = useCallback((button: HTMLElement | null, visible: boolean): FloatingPillPosition | null => {
    if (!visible || !button) return null;
    const rect = button.getBoundingClientRect();
    return {
      left: rect.left + rect.width / 2,
      bottom: window.innerHeight - rect.top + 9,
    };
  }, []);

  const updateFloatingPills = useCallback(() => {
    const next = {
      share: positionForButton(shareButtonRef.current, shareOpen),
    };
    setFloatingPills((current) => (
      current.share?.left === next.share?.left &&
      current.share?.bottom === next.share?.bottom
        ? current
        : next
    ));
  }, [positionForButton, shareOpen]);

  const toggleShare = useCallback((event: React.MouseEvent<HTMLButtonElement>) => {
    if (shareOpen) {
      setShareOpen(false);
      return;
    }
    const share = positionForButton(event.currentTarget, true);
    setFloatingPills((current) => ({ ...current, share }));
    setShareOpen(true);
  }, [positionForButton, shareOpen]);

  useEffect(() => {
    if (!shareOpen) return;
    let frame = 0;
    const scheduleUpdate = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(updateFloatingPills);
    };
    scheduleUpdate();
    window.addEventListener('resize', scheduleUpdate);
    window.addEventListener('scroll', scheduleUpdate, { passive: true });
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener('resize', scheduleUpdate);
      window.removeEventListener('scroll', scheduleUpdate);
    };
  }, [shareOpen, updateFloatingPills]);

  useEffect(() => {
    if (!selectedTarget || !targets.some((target) => target.key === selectedTarget && !target.ingested)) {
      setSelectedTarget(defaultTarget);
    }
  }, [defaultTarget, selectedTarget, targets]);

  const ingest = useMutation({
    mutationFn: () => api.ingest(id, view, selectedTarget),
    onSuccess: async (result) => {
      setIngestOpen(false);
      setToast(`${targetLabel(targets, result.target)}에 저장됨`);
      await qc.invalidateQueries({ queryKey: ['item', id] });
      await qc.invalidateQueries({ queryKey: ['items'] });
    },
    onError: (err) => setToast(err instanceof Error ? err.message : '저장 실패'),
  });
  const remove = useMutation({ mutationFn: () => api.deleteItem(id), onSuccess: async () => { await qc.invalidateQueries({ queryKey: ['items'] }); navigate('/'); } });

  const restorePendingScroll = useCallback(() => {
    const anchor = pendingScrollAnchor.current;
    if (!anchor) return;
    restoreScrollAnchor(anchor);
  }, []);
  const copyText = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
    }
  };
  const markShareCopied = (kind: 'markdown' | 'source' | 'lookup') => {
    setShareCopied(kind);
    window.setTimeout(() => {
      setShareCopied((current) => (current === kind ? '' : current));
      setShareOpen(false);
    }, 850);
  };
  const copySource = async () => {
    if (!item?.url) return;
    await copyText(item.url);
    setSourceCopied(true);
    markShareCopied('source');
    setToast('COPIED');
    window.setTimeout(() => setSourceCopied(false), 1150);
  };
  const copyMarkdown = async () => {
    const res = await fetch(`/api/items/${id}/markdown?view=${view}`, { credentials: 'same-origin' });
    const text = await res.text();
    await copyText(text);
    setMarkdownCopied(true);
    markShareCopied('markdown');
    setToast('COPIED');
    window.setTimeout(() => setMarkdownCopied(false), 1150);
  };
  const copyLookupCode = async () => {
    const text = item?.share_code
      ? `que:${item.share_code}`
      : JSON.stringify({ app: 'que', item_id: id, api_path: `/api/v1/items/${id}` }, null, 2);
    await copyText(text);
    markShareCopied('lookup');
    setToast('COPIED');
  };
  const openIngest = () => {
    if (!targets.length) {
      setToast('저장 가능한 위치가 없습니다.');
      return;
    }
    setIngestOpen(true);
  };
  if (detail.isLoading) return <main className="container"><div className="empty">불러오는 중입니다.</div></main>;
  if (!item) return <main className="container"><div className="empty">항목을 찾을 수 없습니다.</div></main>;

  const hasHttpSource = /^https?:\/\//i.test(item.url || '');

  return (
    <>
      <main className="container" data-id={id} data-source-url={hasHttpSource ? item.url : undefined}>
        <Link className="article-kicker" to="/">← All posts</Link>
        <div className="detail-head">
          <h1>{item.title || item.url}</h1>
          <section className="article-meta">
            <div className="author-row">
              <div className="author-avatar" aria-hidden="true">{item.author_initial}</div>
              <div className="author-name">{item.author_display}<span className="source-mark" aria-hidden="true"><svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3v18" /><path d="M3 12h18" /><path d="m5.6 5.6 12.8 12.8" /><path d="m18.4 5.6-12.8 12.8" /></svg></span></div>
              <span className="read-meta">{item.read_minutes} min read</span>
              {item.article_date && <><span className="dot">·</span><span className="read-meta">{item.article_date}</span></>}
            </div>
            <div className="engagement-bar">
              <div className="engagement-left detail-meta">
                <span className="badge kind" title={item.kind_label} aria-label={item.kind_label} dangerouslySetInnerHTML={{ __html: item.kind_icon_html || item.kind_label }} />
                <span className={`badge ${item.status}`}>{item.status}</span>
              </div>
              <div className="engagement-right">
                {hasHttpSource && (
                  <>
                    <button className={`meta-icon-btn source-copy-btn${sourceCopied ? ' copied icon-enter' : ''}`} type="button" onClick={copySource} title="링크 복사" aria-label="링크 복사">
                      {sourceCopied ? <ClipboardCheck size={18} /> : <Copy size={18} />}
                    </button>
                    <a className="meta-icon-btn" href={item.url} target="_blank" rel="noopener" title="출처 열기" aria-label="출처 열기"><ExternalLink size={18} /></a>
                  </>
                )}
                <a className="meta-icon-btn" href={`/api/items/${id}/markdown?view=${view}`} target="_blank" rel="noopener" title="마크다운 원본" aria-label="마크다운 원본"><FileText size={18} /></a>
              </div>
            </div>
          </section>
        </div>
        {item.status === 'pending' && <p className="empty">추출 중입니다.</p>}
        {item.status === 'error' && (
          <>
            <div className="error-box">추출 실패: {item.error}</div>
            {hasHttpSource && <p>출처를 직접 열어 확인하세요: <a href={item.url} target="_blank" rel="noopener">{item.url}</a></p>}
          </>
        )}
        {item.status !== 'pending' && item.status !== 'error' && <MarkdownBody html={detail.data?.body.html || ''} onRendered={restorePendingScroll} />}
      </main>

      <div className="actionbar" id="actionbar">
        <button className={`ab-btn ab-primary${ingest.isPending ? ' loading' : ''}`} id="ingestbtn" type="button" onClick={openIngest} disabled={ingest.isPending} title="저장 위치 선택" aria-label="저장 위치 선택">
          {item.ingest_count > 1 && <span className="ingest-count-badge" aria-label={`${item.ingest_count}곳에 저장됨`}>{item.ingest_count}</span>}
          <Archive size={20} />
        </button>
        <div className={`share-action${shareOpen ? ' open' : ''}`} ref={shareRef}>
          <button ref={shareButtonRef} className={`ab-btn${shareOpen ? ' active' : ''}`} id="sharebtn" type="button" onClick={toggleShare} title="공유" aria-label="공유" aria-expanded={shareOpen}>
            <Share2 size={20} />
          </button>
        </div>
        <button className="ab-btn ab-danger" id="delbtn" type="button" onClick={() => setDeleteOpen(true)} title="삭제" aria-label="삭제"><Trash2 size={20} /></button>
      </div>

      <ActionPill className={`actionbar-sibling-pill${shareOpen ? ' open' : ''}`} ariaLabel="공유 옵션" pillRef={sharePillRef} style={floatingPillStyle(floatingPills.share)} ariaHidden={!shareOpen}>
          <button className={`share-pill-btn${shareCopied === 'markdown' ? ' copied icon-enter' : ''}`} type="button" role="menuitem" onClick={copyMarkdown} title="마크다운 복사" aria-label="마크다운 복사" tabIndex={shareOpen ? 0 : -1}>
            {shareCopied === 'markdown' || markdownCopied ? <ClipboardCheck size={16} /> : <ClipboardPen size={16} />}
            <span>Markdown</span>
          </button>
          {hasHttpSource && (
            <button className={`share-pill-btn${shareCopied === 'source' ? ' copied icon-enter' : ''}`} type="button" role="menuitem" onClick={copySource} title="링크 복사" aria-label="링크 복사" tabIndex={shareOpen ? 0 : -1}>
              {shareCopied === 'source' ? <ClipboardCheck size={16} /> : <Link2 size={16} />}
              <span>Link</span>
            </button>
          )}
          <button className={`share-pill-btn${shareCopied === 'lookup' ? ' copied icon-enter' : ''}`} type="button" role="menuitem" onClick={copyLookupCode} title="자료 검색 코드 복사" aria-label="자료 검색 코드 복사" tabIndex={shareOpen ? 0 : -1}>
            {shareCopied === 'lookup' ? <ClipboardCheck size={16} /> : <Database size={16} />}
            <span>DB code</span>
          </button>
      </ActionPill>

      <Modal open={ingestOpen} title="Save to" description="저장할 위치를 선택하세요." onClose={() => !ingest.isPending && setIngestOpen(false)} initialFocus=".ingest-target-option.active:not(:disabled), .modal-actions .btn-primary">
        <div className="ingest-target-list" role="listbox" aria-label="저장 위치">
          {targets.map((target) => {
            const active = selectedTarget === target.key && !target.ingested;
            return (
              <button
                key={target.key}
                className={`ingest-target-option${active ? ' active' : ''}${target.ingested ? ' ingested' : ''}`}
                type="button"
                data-ingest-target={target.key}
                data-ingest-label={target.label}
                role="option"
                aria-selected={active}
                disabled={target.ingested || ingest.isPending}
                aria-disabled={target.ingested || ingest.isPending}
                onClick={() => setSelectedTarget(target.key)}
              >
                <span>{target.label}</span>
                <small>{target.ingested ? 'saved' : target.relative_path}</small>
              </button>
            );
          })}
        </div>
        <div className="modal-actions">
          <button className="btn btn-secondary" type="button" onClick={() => setIngestOpen(false)} disabled={ingest.isPending}>Cancel</button>
          <button className="btn btn-primary" type="button" onClick={() => ingest.mutate()} disabled={!selectedTarget || ingest.isPending}>{ingest.isPending ? 'Saving' : 'Save'}</button>
        </div>
      </Modal>

      <Modal open={deleteOpen} title="Delete item" description="이 항목을 목록에서 삭제할까요?" onClose={() => !remove.isPending && setDeleteOpen(false)} initialFocus=".modal-actions .btn-danger">
        <div className="modal-actions">
          <button className="btn btn-secondary" type="button" onClick={() => setDeleteOpen(false)} disabled={remove.isPending}>Cancel</button>
          <button className="btn btn-danger" type="button" onClick={() => remove.mutate()} disabled={remove.isPending}>{remove.isPending ? 'Deleting' : 'Delete'}</button>
        </div>
      </Modal>

      <div className={`toast${toast ? ' show' : ''}`}>{toast}</div>
    </>
  );
}
