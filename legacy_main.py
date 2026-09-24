"""Legacy Que 웹앱 — URL 붙여넣기 → 추출 → 검토 → inbox 적재."""
import html as _html
import hashlib
import json
import re
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import markdown as md_lib
import bleach
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import store
import extract
from config import (HOST, PORT, ensure_inbox, ensure_ingest_target,
                    ingest_target_options, INBOX_DIR, load_api_token,
                    )

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _static_ver() -> str:
    """정적 파일 캐시버스팅용 버전(가장 최근 수정된 static 파일 mtime)."""
    try:
        sdir = BASE_DIR / "static"
        return str(int(max(p.stat().st_mtime for p in sdir.glob("*"))))
    except Exception:
        return "1"


templates.env.globals["static_ver"] = _static_ver()
_RENDER_CACHE_VERSION = "render-v1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db()
    ensure_inbox()
    yield


app = FastAPI(title="Quartz Ingest", lifespan=lifespan)


# ───────────────────────── API access ─────────────────────────
# Browser/local app routes are intentionally open. The external API keeps its
# optional Bearer-token boundary for integrations that are reachable remotely.
_API_TOKEN = load_api_token()


def _is_public_api_path(path: str) -> bool:
    return path == "/api/v1/items" or path.startswith("/api/v1/items/")


def _valid_api_token(request: Request) -> bool:
    if not _API_TOKEN:
        return False
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return False
    return secrets.compare_digest(token.strip(), _API_TOKEN)


@app.middleware("http")
async def session_guard(request: Request, call_next):
    path = request.url.path
    if _is_public_api_path(path):
        if not _API_TOKEN:
            return JSONResponse({"detail": "api token not configured"}, status_code=503)
        if not _valid_api_token(request):
            return JSONResponse({"detail": "invalid api token"}, status_code=401)
    return await call_next(request)


app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
if (BASE_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(BASE_DIR / "assets")), name="assets")


# ───────────────────────── 백그라운드 추출 ─────────────────────────
def _run_extraction(item_id: int, url: str) -> None:
    try:
        res = extract.extract(url)
        markdown = res.get("markdown") or ""
        store.update_extraction(
            item_id, status="extracted",
            title=res.get("title"), author=res.get("author"),
            markdown=markdown, meta_json=res.get("meta"),
        )
    except Exception as e:  # noqa
        store.update_extraction(item_id, status="error", error=str(e)[:1000])


def _kind_label(kind: str) -> str:
    return {"web": "Web", "youtube": "YouTube", "x": "X", "threads": "Threads",
            "brunch": "Brunch", "md": "Markdown"}.get(kind, kind)


_X_PATH = ('<path d="M18.9 1.2h3.7l-8 9.2L24 22.8h-7.4l-5.8-7.6-6.6 7.6H.5l8.6-9.8L0 1.2h7.6'
           'l5.2 6.9 6.1-6.9Zm-1.3 19.5h2L6.5 3.2H4.3l13.3 17.5Z"></path>')


def _kind_icon_html(kind: str, label: str, article: bool = False) -> str:
    title = _html.escape(label or kind or "Source")
    if kind == "brunch":
        # 제3자 브랜드 자산 대신 소스 유형의 중립적인 표식을 사용한다.
        return (f'<span class="kind-logo kind-brunch" aria-hidden="true">B</span>'
                f'<span class="sr-only">{title}</span>')
    if kind == "x" and not article:
        # 일반 X 트윗: 검은 라운드 배경 + 흰 X 로고 (X Article 과 구분)
        x_white = _X_PATH.replace("></path>", ' fill="#fff"></path>')
        return (
            '<svg class="kind-logo" viewBox="0 0 24 24" width="16" height="16" '
            'aria-hidden="true" focusable="false">'
            '<rect x="0" y="0" width="24" height="24" rx="5" fill="var(--ink)"></rect>'
            f'<g transform="translate(4.5,4.5) scale(0.625)">{x_white}</g>'
            f'</svg><span class="sr-only">{title}</span>'
        )
    common = (
        'class="kind-logo" viewBox="0 0 24 24" width="16" height="16" '
        'aria-hidden="true" focusable="false"'
    )
    if kind == "youtube":
        path = (
            '<path d="M23.5 6.2a3 3 0 0 0-2.1-2.1C19.5 3.6 12 3.6 12 3.6s-7.5 0-9.4.5A3 3 0 0 0 .5 6.2 31.5 31.5 0 0 0 0 12a31.5 31.5 0 0 0 .5 5.8 3 3 0 0 0 2.1 2.1c1.9.5 9.4.5 9.4.5s7.5 0 9.4-.5a3 3 0 0 0 2.1-2.1A31.5 31.5 0 0 0 24 12a31.5 31.5 0 0 0-.5-5.8Z"></path>'
            '<path d="M9.6 15.5 15.8 12 9.6 8.5v7Z" fill="var(--canvas)"></path>'
        )
    elif kind == "x":
        path = (
            '<path d="M18.9 1.2h3.7l-8 9.2L24 22.8h-7.4l-5.8-7.6-6.6 7.6H.5l8.6-9.8L0 1.2h7.6l5.2 6.9 6.1-6.9Zm-1.3 19.5h2L6.5 3.2H4.3l13.3 17.5Z"></path>'
        )
    elif kind == "threads":
        path = (
            '<path d="M12.1 1.2c3.1 0 5.5 1 7.2 3 1.6 1.9 2.4 4.5 2.4 7.8s-.8 5.9-2.4 7.8c-1.7 2-4.1 3-7.2 3s-5.5-1-7.2-3C3.3 17.9 2.5 15.3 2.5 12s.8-5.9 2.4-7.8c1.7-2 4.1-3 7.2-3Zm0 2.2c-2.4 0-4.2.8-5.4 2.2-1.2 1.5-1.8 3.6-1.8 6.4s.6 4.9 1.8 6.4c1.2 1.4 3 2.2 5.4 2.2s4.2-.8 5.4-2.2c1.2-1.5 1.8-3.6 1.8-6.4s-.6-4.9-1.8-6.4c-1.2-1.4-3-2.2-5.4-2.2Z"></path>'
            '<path d="M16.4 10.6c-.2-2.3-1.8-3.8-4.3-3.8-2.3 0-4 1.3-4.2 3.2h2.3c.2-.8.8-1.3 1.9-1.3 1.2 0 1.9.7 2 1.8l-2.4.4c-2.7.4-4.2 1.6-4.2 3.7 0 2 1.6 3.4 4 3.4 2.6 0 4.5-1.5 4.8-4.1 1.1.5 1.7 1.2 1.7 2.2 0 .8-.3 1.6-1 2.2l1.6 1.3c1-.9 1.6-2.1 1.6-3.6 0-2.5-1.4-4.2-3.8-5.4Zm-4.7 5.5c-1.1 0-1.8-.6-1.8-1.5 0-.9.7-1.5 2.2-1.7l2.1-.3v.4c0 1.9-.9 3.1-2.5 3.1Z"></path>'
        )
    else:
        path = (
            '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"></circle>'
            '<path d="M3 12h18M12 3c2.4 2.6 3.6 5.6 3.6 9S14.4 18.4 12 21c-2.4-2.6-3.6-5.6-3.6-9S9.6 5.6 12 3Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"></path>'
        )
    return f'<svg {common}>{path}</svg><span class="sr-only">{title}</span>'


def _source_host(url: str) -> str:
    parts = urlparse(url or "")
    if parts.scheme not in ("http", "https"):
        return ""
    host = (parts.hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _format_article_date(ts) -> str:
    try:
        t = time.localtime(float(ts))
    except Exception:
        return ""
    return f"{time.strftime('%b', t)} {t.tm_mday}, {t.tm_year}"


def _estimate_read_minutes(markdown: str) -> int:
    text = re.sub(r"```.*?```", " ", markdown or "", flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[[^\]]+\]\([^)]+\)", " ", text)
    tokens = re.findall(r"[A-Za-z0-9가-힣]+", text)
    chars = len(re.sub(r"\s+", "", text))
    minutes = max(len(tokens) / 220, chars / 900)
    return max(1, min(99, round(minutes or 1)))


def _author_initial(label: str) -> str:
    m = re.search(r"[A-Za-z0-9가-힣]", label or "")
    return (m.group(0).upper() if m else "Q")


def _row_to_dict(r) -> dict:
    d = dict(r)
    d["ingested_targets"] = store.ingest_targets_for_item(d["id"])
    d["ingest_count"] = len(d["ingested_targets"])
    d["kind_label"] = _kind_label(d.get("kind", "web"))
    is_x_article = d.get("kind") == "x" and "article" in (d.get("meta_json") or "")
    if is_x_article:
        d["kind_label"] = "X Article"
    d["kind_icon_html"] = _kind_icon_html(d.get("kind", "web"), d["kind_label"], article=is_x_article)
    d["source_host"] = _source_host(d.get("url", ""))
    d["author_display"] = (d.get("author") or d["source_host"] or d["kind_label"]).strip()
    d["author_initial"] = _author_initial(d["author_display"])
    d["article_date"] = _format_article_date(d.get("extracted_at") or d.get("created_at"))
    d["read_minutes"] = _estimate_read_minutes(d.get("markdown") or "")
    d["is_unread"] = d.get("status") == "extracted" and not d.get("viewed_at")
    return d


def _ingest_target_options_for_item(item: dict) -> list[dict]:
    ingested = set(item.get("ingested_targets") or [])
    options = ingest_target_options()
    for option in options:
        option["ingested"] = option["key"] in ingested
    return options


def _api_timestamp(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except Exception:
        return None


def _api_meta(meta_json: str | None):
    if not meta_json:
        return None
    try:
        return json.loads(meta_json)
    except Exception:
        return meta_json


def _public_item_summary(item: dict) -> dict:
    markdown = item.get("markdown") or ""
    return {
        "id": item.get("id"),
        "share_code": item.get("share_code"),
        "title": item.get("title") or item.get("url"),
        "url": item.get("url"),
        "kind": item.get("kind"),
        "kind_label": item.get("kind_label"),
        "status": item.get("status"),
        "author": item.get("author"),
        "source_host": item.get("source_host"),
        "created_at": _api_timestamp(item.get("created_at")),
        "extracted_at": _api_timestamp(item.get("extracted_at")),
        "ingested_at": _api_timestamp(item.get("ingested_at")),
        "read_minutes": item.get("read_minutes"),
        "has_markdown": bool(markdown.strip()),
        "markdown_length": len(markdown),
        "error": item.get("error") or None,
    }


def _public_item_detail(item: dict) -> dict:
    data = _public_item_summary(item)
    data.update({
        "markdown": item.get("markdown") or "",
        "meta": _api_meta(item.get("meta_json")),
    })
    return data


# ───────────────────────── 렌더: 콜아웃 → HTML 카드 ─────────────────────────
# 저장 마크다운은 Obsidian 콜아웃(`> [!link]` / `> [!quote]`) 그대로 두고,
# 웹 미리보기에서만 blockquote 를 카드 컴포넌트로 치환한다.
def _strip_meta(md_text: str) -> str:
    """웹 미리보기용: 선두 YAML 프론트매터와 말미 `원문:` footer 제거.
    (저장/ingest 되는 마크다운 원본은 그대로 — 출처는 상단 source-bar 에 이미 노출)."""
    s = md_text or ""
    m = re.match(r"^﻿?---\n.*?\n---\n", s, re.S)
    if m:
        s = s[m.end():]
    s = s.lstrip("\n")
    # 선두 H1 제거 — 제목은 상세 헤더(detail-head)에 이미 노출돼 중복
    s = re.sub(r"^#\s+[^\n]*\n+", "", s, count=1)
    s = re.sub(r"\n*-{3,}\n+원문:[^\n]*\n*$", "\n", s)
    return s.strip()


def _wrap_chain(soup) -> bool:
    """X/Threads 체인: 최상위 노드를 <hr>(포스트 경계) 기준으로 끊어 깃그래프식
    체인으로 감싼다(좌측 세로선 + 노드 점). 포스트가 2개 미만이면 손대지 않음."""
    from bs4 import BeautifulSoup
    nodes = list(soup.children)
    segments: list[list] = [[]]
    has_hr = False
    for n in nodes:
        if getattr(n, "name", None) == "hr":
            has_hr = True
            segments.append([])
        else:
            segments[-1].append(n)
    # 빈 세그먼트(공백 텍스트만) 제거
    def _nonempty(seg):
        return any(getattr(x, "name", None) or (isinstance(x, str) and x.strip()) for x in seg)
    segments = [s for s in segments if _nonempty(s)]
    if not has_hr or len(segments) < 2:
        return False
    chain = soup.new_tag("div")
    chain["class"] = "chain"
    for seg in segments:
        post = soup.new_tag("div")
        post["class"] = "chain-post"
        rail = soup.new_tag("span")
        rail["class"] = "chain-rail"
        rail["aria-hidden"] = "true"
        body = soup.new_tag("div")
        body["class"] = "chain-body"
        for x in seg:
            body.append(x.extract())
        post.append(rail)
        post.append(body)
        chain.append(post)
    # 남은 원본 노드(포스트 경계 <hr> + 빈 세그먼트 공백) 제거 후 체인만 남김.
    # (안 하면 체인 앞에 orphan <hr/> 가 그대로 렌더됨)
    soup.clear()
    soup.append(chain)
    return True


_TS_RE = re.compile(r"^\[(?:(\d+):)?(\d{1,2}):(\d{2})\]$")


_ALLOWED_HTML_TAGS = {
    "a", "abbr", "blockquote", "br", "button", "code", "del", "details", "div",
    "em", "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6", "hr",
    "iframe", "img", "li", "ol", "p", "pre", "span", "strong", "summary",
    "table", "tbody", "td", "th", "thead", "tr", "ul",
}
_GLOBAL_HTML_ATTRS = {"aria-hidden", "class", "id", "title"}
_TAG_HTML_ATTRS = {
    "a": {"href", "rel", "target"},
    "blockquote": {"data-dnt", "data-theme"},
    "button": {"data-t", "type"},
    "iframe": {"allow", "allowfullscreen", "frameborder", "height", "src", "width"},
    "img": {"alt", "height", "loading", "src", "width"},
    "td": {"align", "colspan", "rowspan"},
    "th": {"align", "colspan", "rowspan"},
}


def _allowed_html_attr(tag: str, name: str, value: str) -> bool:
    if name in _GLOBAL_HTML_ATTRS or name in _TAG_HTML_ATTRS.get(tag, set()):
        if tag == "iframe" and name == "src":
            return (value or "").startswith("https://www.youtube.com/embed/")
        if name in {"href", "src"}:
            if name == "href" and re.match(r"^#yt-t=\d+$", value or ""):
                return True
            return bool(re.match(r"^https?://", value or ""))
        return True
    return False


def _sanitize_rendered_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", "", html or "")
    cleaned = bleach.clean(
        html,
        tags=_ALLOWED_HTML_TAGS,
        attributes=_allowed_html_attr,
        protocols=["http", "https"],
        strip=True,
        strip_comments=True,
    )
    return re.sub(r"(?is)<iframe(?![^>]*\bsrc=)[^>]*></iframe>", "", cleaned)


def _enhance_youtube(soup) -> None:
    """유튜브 렌더 가공(웹 미리보기 전용):
    - 임베드 iframe 을 상단 고정(sticky) 플레이어로 감싸고 IFrame API 연동(enablejsapi).
    - 본문 위쪽 중복 썸네일 링크 제거(플레이어가 곧 히어로).
    - 자막 타임스탬프 `[mm:ss]` 를 클릭 시 해당 구간으로 점프하는 버튼으로 치환.
    저장 마크다운 원본은 그대로 — 표시 가공만 한다."""
    from bs4 import BeautifulSoup
    iframe = soup.find("iframe", src=re.compile(r"youtube\.com/embed/"))
    if iframe is not None:
        src = iframe.get("src", "")
        if "enablejsapi=1" not in src:
            src += ("&" if "?" in src else "?") + "enablejsapi=1"
        iframe["src"] = src
        iframe["id"] = "yt-player"
        # 중복 썸네일 링크(![thumbnail]) 제거 — 보통 iframe 바로 앞 <p><a><img></a></p>
        for img in soup.find_all("img", alt="thumbnail"):
            wrap = img.find_parent(["p", "a"]) or img
            (wrap.find_parent("p") or wrap).decompose()
        # iframe 을 sticky 컨테이너로 감싼다(16:9 반응형 .yt-frame).
        sticky = soup.new_tag("div"); sticky["class"] = "yt-sticky"
        frame = soup.new_tag("div"); frame["class"] = "yt-frame"
        iframe.wrap(frame)
        frame.wrap(sticky)
    # 타임스탬프 strong → 점프 버튼
    for st in soup.find_all("strong"):
        m = _TS_RE.match(st.get_text(strip=True))
        if not m:
            continue
        hh, mm, ss = m.group(1), m.group(2), m.group(3)
        secs = (int(hh) * 3600 if hh else 0) + int(mm) * 60 + int(ss)
        btn = soup.new_tag("button")
        btn["class"] = "yt-ts"
        btn["data-t"] = str(secs)
        btn["type"] = "button"
        btn.string = st.get_text()
        st.replace_with(btn)


def _render_markdown(md_text: str, kind: str | None = None) -> str:
    html = md_lib.markdown(
        _strip_meta(md_text),
        extensions=["extra", "sane_lists", "nl2br", "tables", "fenced_code"],
    )
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return _sanitize_rendered_html(html)
    soup = BeautifulSoup(html, "html.parser")
    needs_twitter = False
    for bq in soup.find_all("blockquote"):
        head = bq.get_text(" ", strip=True)
        if head.startswith("[!link]"):
            _bq_to_link_card(soup, bq)
        elif head.startswith("[!quote]"):
            if _bq_to_quote_card(soup, bq):
                needs_twitter = True
    if kind == "youtube":
        _enhance_youtube(soup)
    # X/Threads 체인이면 깃그래프식 체인으로 묶고(hr=포스트 경계), 그 외엔 hr→장식
    chained = _wrap_chain(soup) if kind in ("x", "threads") else False
    if not chained:
        for hr in soup.find_all("hr"):
            orn = BeautifulSoup('<div class="post-sep" aria-hidden="true"><span>q</span></div>',
                                "html.parser")
            hr.replace_with(orn)
    out = _sanitize_rendered_html(str(soup))
    if needs_twitter:
        # X 공식 임베드 위젯 — 트윗 status 링크를 실제 임베드 카드로 렌더(다크 테마)
        out += ('\n<script async src="https://platform.twitter.com/widgets.js" '
                'charset="utf-8"></script>')
    return out


def _render_cache_key(md_text: str, kind: str | None, view: str) -> str:
    h = hashlib.sha256()
    h.update(_RENDER_CACHE_VERSION.encode("utf-8"))
    h.update(b"\0")
    h.update((kind or "").encode("utf-8"))
    h.update(b"\0")
    h.update(view.encode("utf-8"))
    h.update(b"\0")
    h.update((md_text or "").encode("utf-8"))
    return h.hexdigest()


def _render_markdown_cached(item_id: int, md_text: str, kind: str | None, view: str) -> str:
    cache_key = _render_cache_key(md_text, kind, view)
    cached = store.get_render_cache(item_id, view, cache_key)
    if cached is not None:
        return cached
    html = _render_markdown(md_text, kind=kind)
    store.set_render_cache(item_id, view, cache_key, html)
    return html


# 트윗 status URL 판별(공식 임베드 대상)
_TWEET_URL_RE = re.compile(
    r"https?://(?:www\.|mobile\.)?(?:x\.com|twitter\.com)/(?:[^/\s]+|i)/status/\d+", re.I)


def _bq_lines(bq) -> list[str]:
    return [ln.strip() for ln in bq.get_text("\n").split("\n") if ln.strip()]


def _bq_to_link_card(soup, bq) -> None:
    from bs4 import BeautifulSoup
    a = bq.find("a")
    url = (a.get("href") if a else "") or ""
    title = (a.get_text(strip=True) if a else "") or (urlparse(url).hostname or url)
    img = bq.find("img")
    thumb = (img.get("src") if img else "") or ""
    lines = _bq_lines(bq)
    lines = [ln for ln in lines if ln and not ln.startswith("[!link]") and ln != title]
    host = lines[-1] if lines else (urlparse(url).hostname or "")
    desc = " ".join(lines[:-1]) if len(lines) > 1 else ""
    e = _html.escape
    thumb_html = f'<div class="bm-thumb"><img src="{e(thumb)}" alt="" loading="lazy"></div>' if thumb else ""
    desc_html = f'<div class="bm-desc">{e(desc)}</div>' if desc else ""
    card = (f'<a class="bookmark-card" href="{e(url)}" target="_blank" rel="noopener">'
            f'{thumb_html}<div class="bm-body"><div class="bm-title">{e(title)}</div>'
            f'{desc_html}<div class="bm-host">{e(host)}</div></div></a>')
    bq.replace_with(BeautifulSoup(card, "html.parser"))


def _bq_to_quote_card(soup, bq) -> bool:
    """[!quote] 콜아웃 변환. 트윗 status URL 이면 X 공식 임베드(True 반환),
    그 외엔 커스텀 인용 카드(False)."""
    from bs4 import BeautifulSoup
    a = bq.find("a")
    qurl = (a.get("href") if a else "") or ""
    label = (a.get_text(strip=True) if a else "") or "트윗"
    body = []
    for ln in _bq_lines(bq):
        if ln.startswith("[!quote]") or ln == label or ln in ("인용", "—", "인용 —"):
            continue
        body.append(ln)
    snippet = " ".join(body)
    e = _html.escape
    # 트윗이면 X 공식 임베드 위젯으로
    if qurl and _TWEET_URL_RE.match(qurl):
        fallback = f'<p>{e(snippet)}</p>' if snippet else ''
        embed = (f'<blockquote class="twitter-tweet" data-theme="dark" data-dnt="true">'
                 f'{fallback}<a href="{e(qurl)}">{e(label)} 트윗 보기 →</a></blockquote>')
        bq.replace_with(BeautifulSoup(embed, "html.parser"))
        return True
    head = (f'<a href="{e(qurl)}" target="_blank" rel="noopener">{e(label)}</a>'
            if qurl else e(label))
    card = (f'<div class="quote-card"><div class="qc-head">↩ 인용 · {head}</div>'
            f'<div class="qc-body">{e(snippet)}</div></div>')
    bq.replace_with(BeautifulSoup(card, "html.parser"))
    return False


# ───────────────────────── 라우트 ─────────────────────────
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    items = [_row_to_dict(r) for r in store.list_items()]
    return templates.TemplateResponse("index.html", {"request": request, "items": items})


@app.post("/items")
def add_item(url: str = Form(...)):
    url = (url or "").strip()
    if not re.match(r"^https?://", url):
        raise HTTPException(status_code=400, detail="http(s) URL 을 입력하세요.")
    kind = extract.detect_kind(url)
    item_id = store.add_item(url, kind)
    threading.Thread(target=_run_extraction, args=(item_id, url), daemon=True).start()
    return JSONResponse({"id": item_id, "kind": kind, "status": "pending"})


@app.get("/api/items")
def api_items():
    return JSONResponse([_row_to_dict(r) for r in store.list_items()])


@app.get("/api/v1/items")
def public_api_items():
    items = [_public_item_summary(_row_to_dict(r)) for r in store.list_items()]
    return JSONResponse({"items": items})


@app.get("/api/v1/items/{item_id}")
def public_api_item(item_id: int):
    r = store.get_item(item_id)
    if not r:
        raise HTTPException(status_code=404, detail="없는 항목")
    return JSONResponse(_public_item_detail(_row_to_dict(r)))


def _render_item_body(item: dict, view: str) -> tuple[str, str]:
    """상세 본문 HTML 렌더. 공개 브랜치는 원문만 제공한다."""
    source_md, effective = item.get("markdown"), "orig"
    html_body = (
        _render_markdown_cached(item["id"], source_md, item.get("kind"), effective)
        if source_md else ""
    )
    return html_body, effective


@app.get("/items/{item_id}", response_class=HTMLResponse)
def detail(request: Request, item_id: int, view: str = "orig"):
    r = store.get_item(item_id)
    if not r:
        raise HTTPException(status_code=404, detail="없는 항목")
    if r["status"] in ("extracted", "ingested"):
        store.mark_viewed(item_id)
    item = _row_to_dict(r)
    html_body, item["view"] = _render_item_body(item, view)
    return templates.TemplateResponse(
        "detail.html",
        {
            "request": request,
            "item": item,
            "html_body": html_body,
            "ingest_targets": _ingest_target_options_for_item(item),
        },
    )


@app.get("/items/{item_id}/body")
def item_body(item_id: int, view: str = "orig"):
    """SPA용 원문 본문 HTML을 JSON으로 반환한다."""
    r = store.get_item(item_id)
    if not r:
        raise HTTPException(status_code=404, detail="없는 항목")
    item = _row_to_dict(r)
    html_body, effective = _render_item_body(item, view)
    return JSONResponse({"html": html_body, "view": effective})


@app.api_route("/items/{item_id}/translate", methods=["GET", "POST"])
def translate_disabled(item_id: int):
    raise HTTPException(status_code=410, detail="번역 기능은 공개 브랜치에서 임시 비활성화되었습니다.")


@app.get("/items/{item_id}/markdown", response_class=PlainTextResponse)
def raw_markdown(item_id: int, view: str = "orig"):
    r = store.get_item(item_id)
    if not r:
        raise HTTPException(status_code=404, detail="없는 항목")
    return PlainTextResponse(r["markdown"] or "", media_type="text/markdown; charset=utf-8")


def _slugify(text: str) -> str:
    text = (text or "untitled").strip()
    text = re.sub(r"[\\/:*?\"<>|#\[\]]", "", text)
    text = re.sub(r"\s+", "-", text)
    return text[:80] or "untitled"


@app.post("/items/{item_id}/ingest")
def ingest(item_id: int, view: str = "orig", target: str = "inbox"):
    r = store.get_item(item_id)
    if not r:
        raise HTTPException(status_code=404, detail="없는 항목")
    content = r["markdown"] or ""
    if not (content or "").strip():
        raise HTTPException(status_code=400, detail="추출된 마크다운이 없습니다.")
    if store.has_ingest_target(item_id, target):
        raise HTTPException(status_code=400, detail="이미 저장된 위치입니다.")

    try:
        ingest_dir = ensure_ingest_target(target)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # 안전장치: 반드시 선택된 허용 폴더 안에만 기록
    stamp = time.strftime("%Y%m%d-%H%M%S")
    fname = f"{stamp}-{_slugify(r['title'])}.md"
    dest = (ingest_dir / fname).resolve()
    if ingest_dir.resolve() not in dest.parents:
        raise HTTPException(status_code=500, detail="저장 경로 위반")
    dest.write_text(content, encoding="utf-8")
    store.mark_ingested(item_id, target, str(dest))
    return JSONResponse({"ok": True, "path": str(dest), "target": target})


@app.post("/items/{item_id}/delete")
def delete(item_id: int):
    store.delete_item(item_id)
    return JSONResponse({"ok": True})


@app.get("/health")
def health():
    return {"status": "ok", "inbox": str(INBOX_DIR) if INBOX_DIR else ""}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
