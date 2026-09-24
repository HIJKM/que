"""URL → 마크다운 추출 어댑터.

조사문서(/tmp/ingest-webapp-research.md) 결론을 따른다:
- 일반 웹: trafilatura(Defuddle 대응) → readability+markdownify → bs4 휴리스틱 폴백 (graceful)
- 유튜브: 영상ID 파싱 → iframe/thumbnail/link preview + 자막(youtube-transcript-api, 실패 시 안내)
- X/Threads: 렌더 HTML 직변환 금지. post 객체로 정규화 후 quoted = 1-depth callout.
  마크다운 normalizer 에서 blockquote depth 를 최대 1로 cap.
"""
from __future__ import annotations

import os
import re
from typing import Optional, Tuple
from urllib.parse import urlparse, parse_qs
from html import escape as _html_escape

import json as _json

import httpx

from safe_fetch import safe_get, BlockedURLError  # SSRF-안전 fetch

# 격리 컨테이너의 헤드리스 렌더 서비스(127.0.0.1 전용). safe_get(사설IP 차단) 대상이
# 아니므로 일반 httpx 로 호출한다. Threads 체인 렌더에 사용.
RENDER_URL = os.environ.get("QUE_RENDER_URL", "http://127.0.0.1:8799/render")
RENDER_TOKEN = os.environ.get("QUE_RENDER_TOKEN", "")
RENDER_TIMEOUT = float(os.environ.get("QUE_RENDER_TIMEOUT", "70"))

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HTTP_TIMEOUT = 25.0


# ───────────────────────── URL 종류 판별 ─────────────────────────
def detect_kind(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().lstrip("www.")
    if host in ("youtube.com", "youtu.be", "m.youtube.com") or "youtube.com" in host:
        return "youtube"
    if host in ("x.com", "twitter.com", "mobile.twitter.com", "nitter.net"):
        return "x"
    if host in ("threads.net", "threads.com", "www.threads.net"):
        return "threads"
    if host == "brunch.co.kr" or host.endswith(".brunch.co.kr"):
        return "brunch"
    return "web"


def _fetch_html(url: str) -> str:
    # SSRF-안전: 내부 대역 차단 + IP 핀닝 + redirect 재검증 + 크기/시간 제한
    headers = {"User-Agent": UA, "Accept-Language": "ko,en;q=0.8"}
    r = safe_get(url, headers=headers)
    if r.status_code >= 400:
        raise ValueError(f"HTTP {r.status_code}")
    return r.text


# ───────────────────────── 마크다운 정규화 ─────────────────────────
def cap_blockquote_depth(md: str, max_depth: int = 1) -> str:
    """누적된 '>>>' 인용 중첩을 최대 max_depth 로 cap (X/Threads 꼬리물기 방지)."""
    out = []
    for line in md.splitlines():
        m = re.match(r"^(\s*)((?:>\s*)+)(.*)$", line)
        if m:
            indent, quotes, rest = m.groups()
            depth = quotes.count(">")
            capped = ">" * min(depth, max_depth)
            out.append(f"{indent}{capped} {rest}".rstrip())
        else:
            out.append(line)
    # 3줄 이상 연속 빈 줄 축소
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _frontmatter(title: str, source_url: str, kind: str, author: str = "") -> str:
    safe_title = (title or "").replace('"', "'").strip() or "Untitled"
    lines = [
        "---",
        f'title: "{safe_title}"',
        f"source: {source_url}",
        f"kind: {kind}",
    ]
    if author:
        lines.append(f'author: "{author.replace(chr(34), chr(39))}"')
    lines += ["clipped: true", "---", ""]
    return "\n".join(lines)


# ───────────────────────── 일반 웹 (Defuddle-first 대응) ─────────────────────────
def _extract_web(url: str) -> dict:
    html = _fetch_html(url)
    title, author, body_md = "", "", ""
    used = None

    # 1차: trafilatura (Defuddle 대응 — clutter 제거 + markdown)
    try:
        import trafilatura
        from trafilatura.metadata import extract_metadata

        body_md = trafilatura.extract(
            html, url=url, output_format="markdown",
            include_links=True, include_images=True, favor_precision=True,
        ) or ""
        try:
            md = extract_metadata(html, default_url=url)
            if md:
                title = md.title or ""
                author = md.author or ""
        except Exception:
            pass
        if body_md.strip():
            used = "trafilatura"
    except Exception:
        body_md = ""

    # 2차: readability + markdownify
    if not body_md.strip():
        try:
            from readability import Document
            from markdownify import markdownify as md2

            doc = Document(html)
            title = title or (doc.short_title() or "")
            body_md = md2(doc.summary(html_partial=True), heading_style="ATX") or ""
            if body_md.strip():
                used = "readability"
        except Exception:
            body_md = ""

    # 3차: bs4 휴리스틱 (article/main/최대 <p> 군집)
    if not body_md.strip():
        from bs4 import BeautifulSoup
        from markdownify import markdownify as md2

        soup = BeautifulSoup(html, "html.parser")
        if not title:
            t = soup.find("title")
            title = t.get_text(strip=True) if t else url
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()
        node = soup.find("article") or soup.find("main") or soup.body or soup
        body_md = md2(str(node), heading_style="ATX") or ""
        used = "bs4"

    body_md = cap_blockquote_depth(body_md)
    fm = _frontmatter(title, url, "web", author)
    # 본문이 이미 h1 으로 시작하면 제목 헤딩 중복 추가하지 않음
    head = "" if body_md.lstrip().startswith("# ") else f"# {title or 'Untitled'}\n\n"
    md = fm + head + body_md + f"\n\n---\n원문: {url}\n"
    return {
        "kind": "web", "title": title or url, "author": author,
        "markdown": md, "meta": f"extractor={used}",
    }


# ───────────────────────── 유튜브 ─────────────────────────
def _youtube_id(url: str) -> Optional[str]:
    p = urlparse(url)
    if p.hostname and "youtu.be" in p.hostname:
        return p.path.lstrip("/").split("/")[0] or None
    if p.hostname and "youtube.com" in p.hostname:
        if p.path.startswith("/watch"):
            return parse_qs(p.query).get("v", [None])[0]
        if p.path.startswith(("/embed/", "/shorts/", "/live/")):
            return p.path.split("/")[2]
    return None


def _fmt_ts(sec: float) -> str:
    s = int(sec or 0)
    return f"{s // 60:02d}:{s % 60:02d}"


def _paragraphize_transcript(snippets) -> str:
    """자막 조각(start/duration/text) → [mm:ss] 문단. 침묵 gap 또는 길이 기준으로 묶음."""
    GAP = 1.5           # 침묵 gap(초): 이보다 길면 문단 끊음
    MAX_WORDS = 110     # 문단 최대 단어
    MAX_SECS = 55       # 문단 최대 길이(초)
    paras: list[tuple[float, str]] = []
    cur: list[str] = []
    cur_start = None
    cur_words = 0
    prev_end = None
    for sn in snippets:
        txt = re.sub(r"\s+", " ", (getattr(sn, "text", "") or "")).strip()
        start = getattr(sn, "start", 0.0) or 0.0
        dur = getattr(sn, "duration", 0.0) or 0.0
        if not txt:
            prev_end = start + dur
            continue
        gap = (start - prev_end) if prev_end is not None else 0.0
        if cur and (gap >= GAP or cur_words >= MAX_WORDS or (start - cur_start) >= MAX_SECS):
            paras.append((cur_start, " ".join(cur)))
            cur, cur_words, cur_start = [], 0, None
        if cur_start is None:
            cur_start = start
        cur.append(txt)
        cur_words += len(txt.split())
        prev_end = start + dur
    if cur:
        paras.append((cur_start, " ".join(cur)))
    return "\n\n".join(f"**[{_fmt_ts(st)}]** {re.sub(r'\\s+', ' ', t).strip()}" for st, t in paras)


def _sentenceize_transcript(snippets) -> tuple[str, list[dict]]:
    """자막 조각을 읽기 좋은 문장으로 묶되, 각 문장의 시작 시각은 보존한다.

    유튜브 자막의 개별 cue는 단어 중간에서 끊기는 경우가 많다. 따라서 cue를
    그대로 화면에 노출하면 읽기 어렵지만, 기존처럼 긴 문단 하나로 합치면
    클릭할 수 있는 위치 정보가 사라진다. 문장 경계에서만 묶고, 원본 cue 전체는
    meta의 ``transcript_segments``에 그대로 저장한다.
    """
    # 문장부호가 없는 자동 자막도 있으므로 침묵/길이 제한을 함께 사용한다.
    SENTENCE_END = re.compile(r"[.!?。！？…](?:[\"'”’』】）》)]*)$")
    GAP = 1.4
    MAX_CHARS = 180
    MAX_SECS = 18
    MAX_CUES = 12

    cues: list[dict] = []
    for sn in snippets:
        text = re.sub(r"\s+", " ", (getattr(sn, "text", "") or "")).strip()
        if not text:
            continue
        start = float(getattr(sn, "start", 0.0) or 0.0)
        duration = float(getattr(sn, "duration", 0.0) or 0.0)
        cues.append({"start": start, "duration": duration, "text": text})

    sentences: list[dict] = []
    current: list[dict] = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        sentences.append({
            "start": current[0]["start"],
            "duration": max(
                0.0,
                current[-1]["start"] + current[-1]["duration"] - current[0]["start"],
            ),
            "text": " ".join(cue["text"] for cue in current),
        })
        current = []

    previous_end = None
    for cue in cues:
        gap = cue["start"] - previous_end if previous_end is not None else 0.0
        candidate = " ".join(item["text"] for item in current + [cue])
        too_long = (
            current
            and (gap >= GAP
                 or len(candidate) > MAX_CHARS
                 or cue["start"] - current[0]["start"] >= MAX_SECS
                 or len(current) >= MAX_CUES)
        )
        if too_long:
            flush()
        current.append(cue)
        previous_end = cue["start"] + cue["duration"]
        if SENTENCE_END.search(cue["text"]):
            flush()
    flush()

    # 세 문장씩 한 문단에 넣어 산문처럼 보이게 한다. 버튼 자체는 HTML로
    # 유지되므로 번역 후에도 문장별 클릭/seek가 가능하다.
    paragraphs: list[str] = []
    for offset in range(0, len(sentences), 3):
        buttons = []
        for sentence in sentences[offset:offset + 3]:
            start = f'{sentence["start"]:.3f}'.rstrip("0").rstrip(".")
            buttons.append(
                f'<button class="yt-ts yt-sentence" type="button" data-t="{start}">'
                f'{_html_escape(sentence["text"], quote=False)}</button>'
            )
        paragraphs.append(" ".join(buttons))
    return "\n\n".join(paragraphs), cues


def _extract_youtube(url: str) -> dict:
    vid = _youtube_id(url)
    if not vid:
        raise ValueError("유튜브 영상 ID를 파싱하지 못했습니다.")

    title = url
    # oEmbed 로 제목/작성자 (no auth) — 고정 공개 호스트지만 안전 fetch 경유
    try:
        from urllib.parse import quote
        oembed = (f"https://www.youtube.com/oembed?url="
                  f"{quote(f'https://www.youtube.com/watch?v={vid}', safe='')}&format=json")
        o = safe_get(oembed, headers={"User-Agent": UA})
        if o.status_code == 200:
            j = _json.loads(o.text)
            title = j.get("title", title)
            author = j.get("author_name", "")
        else:
            author = ""
    except Exception:
        author = ""

    thumb = f"https://img.youtube.com/vi/{vid}/maxresdefault.jpg"
    watch = f"https://www.youtube.com/watch?v={vid}"
    parts = [
        _frontmatter(title, watch, "youtube", author),
        f"# {title}\n",
        f"[![thumbnail]({thumb})]({watch})\n",
        f"<iframe width=\"560\" height=\"315\" src=\"https://www.youtube.com/embed/{vid}\" "
        f"frameborder=\"0\" allowfullscreen></iframe>\n",
    ]
    if author:
        parts.append(f"- 채널: {author}")

    # 자막 (graceful) — manual 우선 → generated 폴백. 원본 cue는 meta에 보존하고,
    # 본문은 문장 단위 버튼으로 출력해 읽기와 영상 seek를 함께 지원한다.
    transcript_md = ""
    transcript_meta = None
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        tl = api.list(vid)
        langs = ["ko", "en"]
        tr, kind = None, ""
        try:
            tr, kind = tl.find_manually_created_transcript(langs), "manual"
        except Exception:
            try:
                tr, kind = tl.find_generated_transcript(langs), "generated"
            except Exception:
                for t in tl:  # 아무 언어나(있으면)
                    tr, kind = t, ("generated" if t.is_generated else "manual")
                    break
        if tr is not None:
            snippets = list(tr.fetch())
            prose, segments = _sentenceize_transcript(snippets)
            if prose:
                transcript_md = f"\n## 자막 ({kind}, {tr.language_code})\n\n{prose}\n"
                transcript_meta = {
                    "video_id": vid,
                    "transcript_kind": kind,
                    "language_code": tr.language_code,
                    "transcript_segments": segments,
                }
    except Exception:  # noqa
        transcript_md = ""

    if not transcript_md:
        transcript_md = (
            "\n## 자막\n\n> 자동 자막을 가져오지 못했습니다(비공개·자막없음·지역제한 등). "
            "필요하면 아래에 직접 붙여넣어 편집하세요.\n"
        )

    md = "\n".join(parts) + "\n" + transcript_md + f"\n---\n원문: {watch}\n"
    meta = transcript_meta or {"video_id": vid}
    return {"kind": "youtube", "title": title, "author": author,
            "markdown": cap_blockquote_depth(md),
            "meta": _json.dumps(meta, ensure_ascii=False, separators=(",", ":"))}


# ───────────────────────── X / Threads ─────────────────────────
def _x_status_id(url: str) -> Optional[str]:
    m = re.search(r"/status/(\d+)", url)
    return m.group(1) if m else None


def _render_x_media(media: dict) -> list[str]:
    """FxEmbed media(dict) → 마크다운. photos=![alt](url), videos/gif=썸네일+mp4 링크. 핫링크(다운로드 X)."""
    if not media:
        return []
    photos = media.get("photos")
    videos = media.get("videos")
    if photos is None and videos is None:  # v1/all 폴백: type 으로 분기
        photos, videos = [], []
        for m in (media.get("all") or []):
            (videos if m.get("type") in ("video", "gif") else photos).append(m)
    lines: list[str] = []
    for p in (photos or []):
        u = p.get("url")
        if not u:
            continue
        alt = (p.get("altText") or "photo").replace("]", " ").replace("\n", " ").strip()
        lines.append(f"![{alt}]({u})")
    for v in (videos or []):
        u = v.get("url")
        thumb = v.get("thumbnail_url") or v.get("preview_image_url")
        kind = "GIF" if v.get("type") == "gif" else "영상"
        if thumb and u:
            lines.append(f"[![{kind} preview]({thumb})]({u})")
            lines.append(f"- {kind}: {u}")
        elif u:
            lines.append(f"- {kind}: {u}")
        elif thumb:
            lines.append(f"![{kind} preview]({thumb})")
    return lines


# 트위터 자체/미디어 도메인(외부 링크 카드 대상에서 제외)
_X_SELF_HOSTS = ("twitter.com", "x.com", "t.co", "pic.twitter.com", "pic.x.com")


def _external_links(post: dict) -> list[str]:
    """post 의 외부 링크(type=url facet) expanded URL 목록. 미디어/트윗자체 링크 제외, 중복 제거."""
    rt = post.get("raw_text") or {}
    out: list[str] = []
    for f in (rt.get("facets") or []):
        if f.get("type") != "url":
            continue
        u = (f.get("replacement") or f.get("original") or "")
        if not u.startswith(("http://", "https://")):
            continue
        host = (urlparse(u).hostname or "").lower()
        host = host[4:] if host.startswith("www.") else host
        if any(host == h or host.endswith("." + h) for h in _X_SELF_HOSTS):
            continue
        if u not in out:
            out.append(u)
    return out


def _link_card(url: str, budget: list) -> list[str]:
    """외부 URL → OG 북마크 카드(> [!link] 제목/설명/썸네일/URL). OG는 ★safe_fetch 경유.
    예산 소진/OG 실패시 깔끔한 링크([도메인](url))로 폴백. 썸네일은 핫링크."""
    title = desc = image = ""
    final = url
    if budget and budget[0] > 0:
        budget[0] -= 1
        try:
            r = safe_get(url, headers={"User-Agent": UA}, max_bytes=2 * 1024 * 1024)
            final = getattr(r, "url", url) or url
            if r.status_code < 400 and r.text:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(r.text, "html.parser")

                def meta(*names):
                    for n in names:
                        m = soup.find("meta", property=n) or soup.find("meta", attrs={"name": n})
                        if m and (m.get("content") or "").strip():
                            return m["content"].strip()
                    return ""

                title = meta("og:title", "twitter:title") or (
                    soup.title.get_text(strip=True) if soup.title else "")
                desc = meta("og:description", "twitter:description", "description")
                image = meta("og:image", "twitter:image")
        except Exception:
            pass
    host = (urlparse(final).hostname or final)
    host = host[4:] if host.startswith("www.") else host
    if not title:  # (c) 깔끔한 링크 폴백
        return [f"[{host}]({final})"]
    title = re.sub(r"\s+", " ", title).strip()
    lines = [f"> [!link] [{title}]({final})"]
    if desc:
        d = re.sub(r"\s+", " ", desc).strip()
        lines.append(f"> {d[:300] + ('…' if len(d) > 300 else '')}")
    if image and image.startswith(("http://", "https://")):
        lines += [">", f"> ![]({image})"]
    lines += [">", f"> {host}"]
    return lines


def _x_post_block(post: dict, heading: str = "", show_author: bool = True,
                  og_budget: list | None = None) -> list[str]:
    """X post → 마크다운 블록(헤더 + 본문 + 미디어 + 외부링크 카드). 삭제/비공개면 tombstone."""
    ptype = post.get("type")
    author = post.get("author") or {}
    text = (post.get("text") or "").strip()
    # 언퍼를: 카드(북마크)로 만들 외부 링크 URL 은 본문 텍스트에서 제거(중복 방지)
    ext_links = _external_links(post)
    if ext_links and text:
        strip_forms = set()
        for f in (post.get("raw_text") or {}).get("facets") or []:
            if f.get("type") == "url" and f.get("replacement") in ext_links:
                for form in (f.get("replacement"), f.get("original"), f.get("display")):
                    if form:
                        strip_forms.add(form)
        for form in strip_forms:
            text = text.replace(form, "")
        text = re.sub(r"[ \t]+(\n|$)", r"\1", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if (ptype and ptype not in ("status", "tweet")) or (not text and not author and not post.get("media")):
        reason = (post.get("text") or ptype or "deleted/private").strip()
        return [f"{heading} [unavailable: {reason}]".strip()]
    name = author.get("name", "")
    handle = author.get("screen_name", "")
    created = post.get("created_at", "")
    block: list[str] = []
    if heading and show_author:
        block.append(f"{heading} · {created}".rstrip(" ·") if created else heading)
    elif heading:
        block.append(f"{heading}" + (f" · {created}" if created else ""))
    elif show_author:
        h = f"**{name}** (@{handle})" if handle else (f"**{name}**" if name else "")
        if h:
            block.append(h + (f" · {created}" if created else ""))
    if text:
        block.append("")
        block.append(text)
    media_lines = _render_x_media(post.get("media") or {})
    if media_lines:
        block.append("")
        block += media_lines
    # 본문 속 외부 링크 → 북마크 카드(OG). 인용 트윗 본문과는 무관(quote는 참조만).
    for ext in ext_links:
        card = _link_card(ext, og_budget if og_budget is not None else [0])
        if card:
            block.append("")
            block += card
    # (각 포스트의 자기 퍼머링크 줄은 제거 — 출처는 상단 헤더에 이미 노출, 중복/혼란)
    return block


# ───────────────────────── X Article (Draft.js → 마크다운) ─────────────────────────
def _draft_entity_map(content: dict) -> dict:
    """entityMap(list 또는 dict) → {int key: entity value}."""
    raw = content.get("entityMap")
    out: dict = {}
    if isinstance(raw, list):
        for it in raw:
            try:
                out[int(it.get("key"))] = it.get("value") or {}
            except Exception:
                continue
    elif isinstance(raw, dict):
        for k, v in raw.items():
            try:
                out[int(k)] = v or {}
            except Exception:
                continue
    return out


def _emit_styles(text: str, bold: list, italic: list, s: int, e: int) -> str:
    """[s,e) 구간을 (bold,italic) 연속 런으로 나눠 ** / * 래핑(앞뒤 공백 보존)."""
    parts: list[str] = []
    i = s
    while i < e:
        b, it = bold[i], italic[i]
        j = i
        while j < e and bold[j] == b and italic[j] == it:
            j += 1
        chunk = text[i:j]
        core = chunk.strip()
        if core and (b or it):
            lead = chunk[: len(chunk) - len(chunk.lstrip())]
            trail = chunk[len(chunk.rstrip()):]
            w = "***" if (b and it) else ("**" if b else "*")
            parts.append(f"{lead}{w}{core}{w}{trail}")
        else:
            parts.append(chunk)
        i = j
    return "".join(parts)


def _apply_inline(text: str, styles: list, entities: list, emap: dict) -> str:
    """Draft.js inline 적용: 링크(외곽) + bold/italic(내부)을 offset 기준으로."""
    n = len(text)
    if n == 0:
        return ""
    bold = [False] * n
    italic = [False] * n
    link: list = [None] * n
    for r in (entities or []):
        ent = emap.get(r.get("key"))
        url = ((ent or {}).get("data") or {}).get("url") if ent else None
        if not url:
            continue
        off = max(0, r.get("offset", 0))
        for i in range(off, min(n, off + r.get("length", 0))):
            link[i] = url
    for r in (styles or []):
        st = r.get("style") or ""
        on_b, on_i = (st == "Bold"), (st == "Italic")
        if not (on_b or on_i):
            continue
        off = max(0, r.get("offset", 0))
        for i in range(off, min(n, off + r.get("length", 0))):
            if on_b:
                bold[i] = True
            else:
                italic[i] = True
    out: list[str] = []
    i = 0
    while i < n:
        u = link[i]
        j = i
        while j < n and link[j] == u:
            j += 1
        inner = _emit_styles(text, bold, italic, i, j)
        out.append(f"[{inner.strip()}]({u})" if u else inner)
        i = j
    return "".join(out)


def _fetch_x_status(sid: str) -> dict | None:
    """단일 트윗(status) 최소 조회 — article 임베드 트윗 카드용. 실패 시 None."""
    try:
        r = safe_get(f"https://api.fxtwitter.com/2/status/{sid}", headers={"User-Agent": UA})
        if r.status_code == 200:
            return (_json.loads(r.text).get("status")) or None
    except Exception:
        pass
    return None


def _render_atomic(b: dict, emap: dict, media_map: dict,
                   embed_budget: list, og_budget: list) -> str:
    """X Article atomic 블록 → 마크다운: MEDIA=이미지(+캡션), TWEET=임베드 트윗 카드."""
    out: list[str] = []
    for r in (b.get("entityRanges") or []):
        ent = emap.get(r.get("key")) or {}
        et = ent.get("type")
        data = ent.get("data") or {}
        if et == "MEDIA":
            cap = re.sub(r"\s+", " ", (data.get("caption") or "")).replace("]", " ").strip()
            for mi in (data.get("mediaItems") or []):
                info = media_map.get(str(mi.get("mediaId") or ""))
                u = (info or {}).get("original_img_url")
                if u:
                    out.append(f"![{cap}]({u})")
        elif et == "TWEET":
            tid = str(data.get("tweetId") or "")
            if not tid:
                continue
            st = None
            if embed_budget and embed_budget[0] > 0:
                embed_budget[0] -= 1
                st = _fetch_x_status(tid)
            if st:
                out.append("\n".join(_quote_card(st, og_budget)))
            else:
                out.append(f"> [!quote] 인용 — [트윗](https://x.com/i/status/{tid})")
        elif et in ("IMAGE", "GIF", "VIDEO"):
            u = data.get("url") or data.get("src") or ((data.get("media") or {}) or {}).get("url")
            if u:
                out.append(f"![]({u})")
    return "\n\n".join(x for x in out if x)


def _render_draftjs(content: dict, media_entities: list | None = None,
                    embed_budget: list | None = None, og_budget: list | None = None) -> str:
    """Draft.js content(blocks + entityMap) → 마크다운. 리스트는 타이트하게.
    atomic 블록(이미지·임베드 트윗)은 media_entities 매핑 + 임베드 fetch 로 렌더."""
    blocks = content.get("blocks") or []
    emap = _draft_entity_map(content)
    media_map = {str(me.get("media_id")): (me.get("media_info") or {})
                 for me in (media_entities or []) if me.get("media_id")}
    if embed_budget is None:
        embed_budget = [6]
    if og_budget is None:
        og_budget = [6]
    rendered: list[tuple[bool, str]] = []
    for b in blocks:
        t = b.get("type", "unstyled")
        text = b.get("text", "") or ""
        inline = _apply_inline(text, b.get("inlineStyleRanges") or [],
                               b.get("entityRanges") or [], emap)
        is_list = t in ("unordered-list-item", "ordered-list-item")
        if t == "header-one":
            block = f"# {inline}"
        elif t == "header-two":
            block = f"## {inline}"
        elif t == "header-three":
            block = f"### {inline}"
        elif t == "unordered-list-item":
            block = f"- {inline}"
        elif t == "ordered-list-item":
            block = f"1. {inline}"
        elif t == "blockquote":
            block = f"> {inline}"
        elif t == "code-block":
            block = f"```\n{text}\n```"
        elif t == "atomic":
            block = _render_atomic(b, emap, media_map, embed_budget, og_budget)
            if not block.strip():
                continue
        else:
            block = inline
        if not block.strip():
            continue
        rendered.append((is_list, block))
    out = ""
    prev_list = False
    for idx, (is_list, block) in enumerate(rendered):
        if idx == 0:
            out = block
        else:
            out += ("\n" if (is_list and prev_list) else "\n\n") + block
        prev_list = is_list
    return out.strip()


def _build_x_article(url: str, anchor: dict, art: dict) -> dict:
    """X Article(status.article) → 마크다운(커버 + Draft.js 본문)."""
    author = anchor.get("author") or {}
    author_name = author.get("name", "")
    handle = author.get("screen_name", "")
    title = re.sub(r"\s+", " ", (art.get("title") or "Untitled")).strip() or "Untitled"
    content = art.get("content")
    if isinstance(content, str):
        try:
            content = _json.loads(content)
        except Exception:
            content = {}
    content = content or {}
    body_md = _render_draftjs(content, art.get("media_entities") or [],
                             embed_budget=[6], og_budget=[8])
    parts = [_frontmatter(title, url, "x", author_name), f"# {title}\n"]
    if handle:
        parts.append((f"**{author_name}** (@{handle})\n") if author_name else f"**@{handle}**\n")
    cu = ((art.get("cover_media") or {}).get("media_info") or {}).get("original_img_url")
    if cu:
        parts.append(f"![cover]({cu})\n")
    parts.append(body_md)
    md = "\n".join(parts) + f"\n\n---\n원문: {url}\n"
    nblocks = len(content.get("blocks") or [])
    return {"kind": "x", "title": title, "author": author_name,
            "markdown": cap_blockquote_depth(md, max_depth=1),
            "meta": f"source=fxembed-article; blocks={nblocks}"}


def _quote_card(quote: dict, og_budget: list) -> list[str]:
    """인용 트윗 → 북마크 카드(작성자/본문 스니펫/링크). 인용 안 외부링크는 톱레벨 카드로 뒤에 붙임."""
    qa = quote.get("author") or {}
    qh = qa.get("screen_name") or ""
    qname = qa.get("name") or ""
    qurl = quote.get("url") or ""
    qtext = re.sub(r"\s+", " ", (quote.get("text") or "")).strip()
    label = f"@{qh}" if qh else (qname or "트윗")
    head = f"> [!quote] 인용 — [{label}]({qurl})" if qurl else f"> [!quote] 인용 — {label}"
    out = [head]
    if qtext:
        out.append(f"> {qtext[:280] + ('…' if len(qtext) > 280 else '')}")
    # 인용 안의 외부 링크 → (중첩 대신) 톱레벨 북마크 카드
    for ext in _external_links(quote):
        card = _link_card(ext, og_budget)
        if card:
            out.append("")
            out += card
    return out


def _extract_x(url: str) -> dict:
    """FxEmbed v2(/2/thread → /2/status)로 작성자 스레드 언롤 + 미디어 렌더. v1(/i/status) 폴백.
    status.article 이 있으면 X Article 렌더러로 분기."""
    sid = _x_status_id(url)
    if not sid:
        raise ValueError("X 상태(status) ID를 파싱하지 못했습니다.")

    posts: list[dict] = []   # 작성자 스레드 체인(시간순)
    anchor: dict = {}        # 앵커 글(제목/작성자)
    quote = None             # 인용 글
    src = ""
    last_err = ""

    # 1) FxEmbed v2 thread — 작성자 self-thread 전체 (replies 제외)
    try:
        r = safe_get(f"https://api.fxtwitter.com/2/thread/{sid}", headers={"User-Agent": UA})
        if r.status_code == 200:
            d = _json.loads(r.text)
            status = d.get("status") or {}
            thread = d.get("thread") or []
            anchor = status or (thread[0] if thread else {})
            author_h = ((anchor or {}).get("author") or {}).get("screen_name")
            if thread:
                # 작성자 본인 글만(남의 답글 제외). tombstone(type!=status)은 표시 위해 유지.
                posts = [p for p in thread
                         if (p.get("author") or {}).get("screen_name") == author_h
                         or p.get("type") not in ("status", "tweet")]
                src = "fxembed-v2-thread"
            elif status:
                posts = [status]; src = "fxembed-v2-status"
            quote = (anchor or {}).get("quote")
        else:
            last_err = f"/2/thread -> {r.status_code}"
    except Exception as e:
        last_err = f"/2/thread -> {e}"

    # 2) v2 status(단일) 폴백
    if not posts:
        try:
            r = safe_get(f"https://api.fxtwitter.com/2/status/{sid}", headers={"User-Agent": UA})
            if r.status_code == 200:
                status = (_json.loads(r.text).get("status")) or {}
                if status:
                    anchor = status; posts = [status]; quote = status.get("quote"); src = "fxembed-v2-status"
        except Exception as e:
            last_err = f"/2/status -> {e}"

    # 3) v1(/i/status) 폴백 — 기존 동작 보존
    if not posts:
        for base, s in (("https://api.fxtwitter.com/i/status/", "fx-v1"),
                        ("https://api.vxtwitter.com/i/status/", "vx-v1")):
            try:
                r = safe_get(base + sid, headers={"User-Agent": UA})
                if r.status_code == 200:
                    t = (_json.loads(r.text).get("tweet")) or {}
                    if t:
                        anchor = t; posts = [t]; quote = t.get("quote"); src = s
                        break
                last_err = f"{base} -> {r.status_code}"
            except Exception as e:
                last_err = f"{base} -> {e}"

    if not posts or not anchor:
        raise ValueError(f"X 데이터를 가져오지 못했습니다: {last_err}")

    # X Article(long-form) 분기 — 앵커에 article 객체가 있으면 본문을 Draft.js 로 렌더
    art = anchor.get("article")
    if art:
        return _build_x_article(url, anchor, art)

    author = anchor.get("author") or {}
    title = f"{author.get('name', 'X')} (@{author.get('screen_name', '')})".strip()

    body: list[str] = []
    multi = len(posts) > 1
    og_budget = [6]  # OG fetch 상한(스레드 다링크시 지연 방지)
    for i, p in enumerate(posts, 1):
        if multi:
            if i > 1:
                body += ["", "---", ""]   # 포스트 구분선(Threads 와 동일)
            body += _x_post_block(p, show_author=False, og_budget=og_budget)
        else:
            body += _x_post_block(p, show_author=True, og_budget=og_budget)
        # ★해당 포스트가 인용한 트윗 → 그 포스트 바로 뒤에 인라인 임베드(순서 보존).
        #   본문 언롤 대신 북마크/임베드 카드. 인용 안 외부링크는 톱레벨 카드로.
        pq = p.get("quote")
        if pq:
            body.append("")
            body += _quote_card(pq, og_budget)
        body.append("")

    fm = _frontmatter(title, url, "x", author.get("name", ""))
    md = fm + f"# {title}\n\n" + "\n".join(body) + f"\n\n---\n원문: {url}\n"
    return {"kind": "x", "title": title, "author": author.get("name", ""),
            "markdown": cap_blockquote_depth(md, max_depth=1),
            "meta": f"source={src}; posts={len(posts)}"}


def _render_page(url: str, wait_ms: int = 4000) -> dict:
    """격리 렌더 컨테이너로 JS 렌더된 페이지 받기. {url, html, text}."""
    headers = {"Content-Type": "application/json"}
    if RENDER_TOKEN:
        headers["X-Render-Token"] = RENDER_TOKEN
    r = httpx.post(RENDER_URL, json={"url": url, "wait_ms": wait_ms},
                   headers=headers, timeout=RENDER_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _threads_handle(url: str) -> str:
    m = re.search(r"/@([^/?#]+)", url or "")
    return m.group(1) if m else ""


def _threads_render_handle(data: dict) -> str:
    """렌더된 Threads share 페이지에서 작성자 핸들을 찾는다.

    `/share/<id>/` URL에는 핸들이 들어있지 않으므로 URL만으로는 체인 파싱을
    시작할 수 없다. 렌더 HTML의 최상위 pressable 컨테이너에서 먼저 찾고,
    HTML이 바뀐 경우를 위해 작성자 링크를 직접 훑는 폴백을 둔다.
    """
    from bs4 import BeautifulSoup

    html = data.get("html") or ""
    soup = BeautifulSoup(html, "html.parser")
    containers = soup.select("div[data-pressable-container]")
    tops = [c for c in containers
            if not c.find_parent("div", attrs={"data-pressable-container": True})]
    for container in tops:
        handle = _container_handle(container)
        if handle:
            return handle

    for link in soup.find_all("a", href=True):
        match = _HANDLE_RE.search(link["href"])
        if match:
            return match.group(1).strip().lower()
    return ""


_TH_META = {
    "·", "작성자", "AI Threads", "로그인", "앱 다운로드", "팔로우", "Follow",
    "더 보기", "번역 보기", "Translate", "View on Threads", "답글", "공유",
    "접근할 수 없는 게시물에 남긴 답글", "리포스트", "좋아요",
}


def _th_is_time(s: str) -> bool:
    s = s.strip()
    return bool(re.match(r"^\d+\s*(일|시간|분|초|주|개월|년)\s*(전)?$", s)      # 1일, 8시간 전
                or re.match(r"^\d+\s*[dhmswy]$", s)                            # 1d, 8h
                or re.match(r"^\d{4}-\d{1,2}-\d{1,2}$", s)                     # 2026-06-08
                or re.match(r"^\d{1,2}월\s*\d{1,2}일$", s))                    # 6월 8일


def _th_is_meta(s: str) -> bool:
    s = s.strip()
    return (not s) or (s in _TH_META) or _th_is_time(s)


def _th_is_count(s: str) -> bool:
    # 좋아요/리포스트 등 숫자 카운트 라인(1.2천, 3.4K, 449)
    return bool(re.match(r"^[\d][\d.,]*\s*[KMB만천억]?$", s.strip()))


def _th_other_handle_at(lines: list[str], i: int, author: str) -> bool:
    """lines[i] 가 '다른 사용자 핸들'(핸들꼴 + 다음 비어있지 않은 줄이 시간)인지 → 답글 섹션 시작."""
    s = lines[i].strip()
    if s == author or not re.match(r"^[a-z0-9._]{2,30}$", s):
        return False
    if s.replace(".", "").replace("_", "").isdigit():
        return False
    j = i + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    return j < len(lines) and _th_is_time(lines[j])


def _th_clean(text: str) -> str:
    """포스트 본문 정리: 재생 불가 영상 에러 → 🎬 마커, ' 더 알아보기' UI 제거."""
    out: list[str] = []
    for ln in text.split("\n"):
        s = ln.strip()
        if re.search(r"이 동영상을 재생하는 중 문제가 발생", s):
            out.append("🎬 (영상)")
            continue
        if s in ("더 알아보기", "더보기"):
            continue
        out.append(ln)
    t = "\n".join(out)
    t = re.sub(r"(?:🎬 \(영상\)\s*){2,}", "🎬 (영상)\n", t)   # 연속 마커 dedup
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _parse_threads_chain(text: str, handle: str,
                         accept_unmarked_first: bool = True) -> list[str]:
    """렌더된 innerText → 작성자 self-thread 포스트 텍스트 목록.
    상단의 작성자 연속 블록만 취하고, 다른 사용자 핸들(답글 섹션)이 나오면 중단."""
    lines = (text or "").split("\n")
    n = len(lines)
    posts: list[str] = []
    i = 0
    while i < n and lines[i].strip() != handle:   # 첫 핸들까지 스킵(상단 chrome)
        i += 1
    first_block = True
    while i < n:
        if _th_other_handle_at(lines, i, handle):  # 답글 섹션 시작 → 종료
            break
        if lines[i].strip() != handle:
            i += 1
            continue
        i += 1
        has_author = False
        while i < n and _th_is_meta(lines[i]):     # 시간/작성자/날짜 등 메타 스킵
            if lines[i].strip() == "작성자":
                has_author = True
            i += 1
        # 앵커(첫 글) 또는 '작성자' 마커가 있는 블록만 작성자 thread 포스트.
        # 그 외 핸들 블록(작성자 본인 글의 인용/리포스트)은 본문 수집 후 폐기.
        accept = (first_block and accept_unmarked_first) or has_author
        first_block = False
        buf: list[str] = []
        while (i < n and lines[i].strip() != handle
               and not _th_is_count(lines[i]) and not _th_other_handle_at(lines, i, handle)):
            buf.append(lines[i])
            i += 1
        while i < n and (_th_is_count(lines[i]) or not lines[i].strip()):
            i += 1
        txt = _th_clean("\n".join(buf))
        if accept and txt:
            posts.append(txt)
    return posts


def _threads_post_media(container, handle: str) -> list[str]:
    """pressable container 안의 미디어 이미지(아바타/프로필 사진 제외) → 마크다운 이미지 라인.
    Threads 영상은 blob/HLS 라 직접 링크가 없어 포스터(미리보기) 이미지만 핫링크로 가져온다."""
    out: list[str] = []
    seen: set = set()
    for im in container.find_all("img", src=True):
        src = im["src"]
        if "cdninstagram" not in src:
            continue
        alt = (im.get("alt") or "").strip()
        try:
            w = int(im.get("width") or 0)
        except Exception:
            w = 0
        # 프로필 아바타(작은 width=36, alt='…프로필 사진') 제외
        if "프로필 사진" in alt or "profile photo" in alt.lower() or (0 < w <= 60):
            continue
        if src in seen:
            continue
        seen.add(src)
        a = alt.replace("]", " ").replace("\n", " ").strip()
        out.append(f"![{a}]({src})")
    # 영상 포스터(<video poster=…>) 도 미리보기로
    for v in container.find_all("video"):
        poster = v.get("poster") or ""
        if poster.startswith("http") and poster not in seen:
            seen.add(poster)
            out.append(f"![🎬 영상]({poster})")
    return out


def _unwrap_threads_link(href: str) -> str:
    """Threads 외부 링크는 `l.threads.com/?u=<encoded>` 리다이렉트로 감싸진다.
    실제 목적지 URL 을 풀어 반환(래퍼가 아니면 원본 그대로)."""
    from urllib.parse import unquote
    host = (urlparse(href).hostname or "").lower()
    if host in ("l.threads.com", "l.instagram.com") or host.endswith(".l.threads.com"):
        u = parse_qs(urlparse(href).query).get("u", [None])[0]
        if u:
            return unquote(u)
    return href


_TRACK_PARAMS = {"utm_id", "utm_source", "utm_medium", "utm_campaign", "utm_term",
                 "utm_content", "fbclid", "igshid", "igsh", "xmt", "slof"}


def _dedup_key(url: str) -> str:
    """중복 판정용 정규화 키 — 추적 파라미터(utm_*/fbclid/igsh 등) 무시."""
    p = urlparse(url)
    q = "&".join(sorted(f"{k}={v}" for k, vs in parse_qs(p.query).items()
                        for v in vs if k.lower() not in _TRACK_PARAMS))
    return f"{p.scheme}://{(p.hostname or '').lower()}{p.path.rstrip('/')}?{q}"


def _threads_post_links(container, og_budget: list, seen: set | None = None) -> list[str]:
    """pressable container 안의 외부 링크 → 북마크 카드(OG). threads/instagram 자체 링크 제외.
    `l.threads.com` 리다이렉트는 실제 목적지로 언래핑 후 판정. 카드 사이엔 `<!-- -->` 를
    끼워 python-markdown 이 인접 blockquote(콜아웃)를 하나로 병합하는 것을 막는다."""
    out: list[str] = []
    if seen is None:
        seen = set()
    for a in container.find_all("a", href=True):
        href = _unwrap_threads_link(a["href"])
        if not href.startswith("http"):
            continue
        host = (urlparse(href).hostname or "").lower()
        if ("threads." in host or "instagram." in host or host.endswith("cdninstagram.com")
                or host.endswith("fbcdn.net") or host in ("apps.apple.com", "play.google.com")):
            continue
        key = _dedup_key(href)
        if key in seen:
            continue
        seen.add(key)
        card = _link_card(href, og_budget)
        if card:
            out.append("")
            out.append("<!-- -->")
            out.append("")
            out += card
    return out


_HANDLE_RE = re.compile(r"/@([^/?#]+)")


def _container_handle(container) -> str:
    """컨테이너의 주 작성자 핸들 — 상대/절대 href 어느 쪽이든 첫 '/@handle' 을 정규화(소문자)."""
    from urllib.parse import unquote
    for a in container.find_all("a", href=True):
        m = _HANDLE_RE.search(a["href"])
        if m:
            return unquote(m.group(1)).strip().lower()
    return ""


def _threads_chain_assets(html: str, handle: str, n: int) -> list[list[str]]:
    """렌더 HTML 의 작성자 연속 포스트(data-pressable-container)에서 포스트별
    [미디어 이미지 + 외부 링크 카드] 마크다운 라인 묶음을 추출(상위 n개, 답글 전까지).

    답글(다른 작성자) 컨테이너가 나오면 종료. 첫 컨테이너 매칭 실패로 전체가 조용히
    누락되는 것을 막기 위해, '작성자 핸들 컨테이너를 한 번도 만나기 전'에는 break 하지
    않고 skip 한다(상단 chrome/헤더 컨테이너 흡수)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html or "", "html.parser")
    conts = soup.select("div[data-pressable-container]")
    # 중첩 컨테이너(인용 등)는 제외 — 다른 컨테이너의 자손이면 skip
    tops = [c for c in conts
            if not c.find_parent("div", attrs={"data-pressable-container": True})]
    want = (handle or "").strip().lower()
    og_budget = [6]
    link_seen: set = set()   # 체인 전체에서 동일 외부링크 카드 중복 방지
    assets: list[list[str]] = []
    started = False
    for c in tops:
        h = _container_handle(c)
        if h == want:
            started = True
            assets.append(_threads_post_media(c, handle)
                          + _threads_post_links(c, og_budget, link_seen))
            if len(assets) >= n:
                break
        elif started:
            break          # 작성자 글이 시작된 뒤 다른 핸들 → 답글 섹션, 종료
        # 아직 작성자 글 전(상단 chrome 등)이면 계속 탐색
    return assets


def _build_threads_render_md(url: str, handle: str, posts: list[str],
                             assets: list[list[str]] | None = None) -> dict:
    first = posts[0].splitlines()[0].strip() if posts else "Threads"
    title = re.sub(r"^\d+/\s*", "", first)[:80] or "Threads"   # 선두 "1/ " 제거
    author_disp = f"@{handle}" if handle else "Threads"
    # 각 포스트 = 본문 + (미디어/링크 카드). 포스트 사이에 가로선(체인 경계)
    blocks: list[str] = []
    for i, p in enumerate(posts):
        extra = assets[i] if (assets and i < len(assets)) else []
        seg = p + ("\n\n" + "\n".join(extra) if extra else "")
        blocks.append(seg)
    body = "\n\n---\n\n".join(blocks)
    parts = [_frontmatter(title, url, "threads", handle),
             f"# {title}\n", f"**{author_disp}**\n", body]
    md = "\n".join(parts) + f"\n\n---\n원문: {url}\n"
    nmedia = sum(1 for a in (assets or []) for ln in a if ln.startswith("!["))
    return {"kind": "threads", "title": title, "author": handle,
            "markdown": cap_blockquote_depth(md),
            "meta": f"source=threads-render; posts={len(posts)}; media={nmedia}"}


def _threads_embed_url(url: str) -> str:
    """Threads 포스트 URL → /embed 엔드포인트(쿼리 제거)."""
    from urllib.parse import urlsplit, urlunsplit
    p = urlsplit(url)
    path = p.path.rstrip("/")
    if not path.endswith("/embed"):
        path += "/embed"
    return urlunsplit((p.scheme or "https", p.netloc, path, "", ""))


def _extract_threads(url: str) -> dict:
    """Threads: /embed 엔드포인트(클린 HTML)에서 본문·작성자·미디어·외부링크 추출.

    메인 페이지는 JS 렌더 Relay JSON 이라 HTTP 추출이 약하지만, /embed 는 서버
    렌더 HTML 을 준다. 실패 시 기존 웹 추출로 폴백.

    체인(작성자 self-thread 2글+)은 격리 렌더 컨테이너로 풀 체인을 받아 처리하고,
    단일 글은 embed(이미지·링크 풍부)로 처리한다.
    """
    # 0) 렌더 컨테이너로 share/canonical 페이지 시도.
    #    share URL은 URL에 핸들이 없으므로 렌더 HTML에서 핸들을 복원한다.
    try:
        handle = _threads_handle(url)
        data = _render_page(url, wait_ms=4000)
        from_url = bool(handle)
        if not from_url:
            handle = _threads_render_handle(data)
        if handle:
            # share URL 첫 글은 `작성자` 마커가 없다. 마커가 있는 이어쓰기만
            # 모으면 스레드 오프너가 빠지므로 첫 미표시 블록도 포함한다.
            # 중간의 같은-작성자 인용(날짜 블록)은 first_block 이후라 그대로 제외된다.
            posts = _parse_threads_chain(
                data.get("text", ""), handle,
                accept_unmarked_first=True,
            )
            if not posts and not from_url:
                posts = _parse_threads_chain(data.get("text", ""), handle)
            # canonical 단일 글은 기존 embed 경로를 우선한다. share URL은
            # embed가 404이므로 렌더 결과의 단일 글도 바로 사용한다.
            if len(posts) >= 2 or (not _threads_handle(url) and posts):
                # 포스트별 미디어/외부링크(북마크) 동반 추출 — 실패해도 본문은 유지
                try:
                    assets = _threads_chain_assets(data.get("html", ""), handle, len(posts))
                except Exception:
                    assets = None
                return _build_threads_render_md(url, handle, posts, assets)
    except Exception:
        pass

    try:
        from bs4 import BeautifulSoup

        # 주의: 데스크톱 크롬 UA 를 주면 Threads 가 embed 에도 JS SPA 를 내려준다.
        # 모바일 Safari UA 일 때 서버 렌더된 클린 embed HTML 을 받는다.
        embed_ua = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
        embed_url = _threads_embed_url(url)
        r = safe_get(embed_url, headers={"User-Agent": embed_ua, "Accept-Language": "ko,en;q=0.8"})
        if r.status_code >= 400 or not r.text:
            raise ValueError(f"embed HTTP {r.status_code}")
        soup = BeautifulSoup(r.text, "html.parser")

        # 작성자 핸들: 프로필 이미지 alt 가 핸들(e.g. "choi.openai")
        handle = ""
        for img in soup.find_all("img", alt=True):
            a = (img.get("alt") or "").strip()
            if a and " " not in a and "." in a:
                handle = a
                break

        # 본문: 자식 블록이 없는 leaf 중 가장 긴 텍스트
        body_text = ""
        for el in soup.find_all(["div", "span", "p"]):
            if el.find(["div", "span", "p"], recursive=False):
                continue
            txt = el.get_text("\n", strip=True)
            if txt and len(txt) > len(body_text) and txt != handle and "View on Threads" not in txt:
                body_text = txt
        if not body_text.strip():
            raise ValueError("embed 본문 비어있음")

        # 포스트 미디어(프로필 이미지 alt==handle 은 제외), 중복 제거
        imgs: list[str] = []
        for img in soup.find_all("img", src=True):
            src = img["src"]
            alt = (img.get("alt") or "").strip()
            if "cdninstagram" in src and alt != handle and src not in imgs:
                imgs.append(src)

        # 외부 링크 → 북마크 카드
        og_budget = [4]
        link_cards: list[str] = []
        seen_links: set = set()
        for a in soup.find_all("a", href=True):
            href = _unwrap_threads_link(a["href"])
            host = (urlparse(href).hostname or "").lower()
            key = _dedup_key(href)
            if (href.startswith("http") and "threads." not in host
                    and "instagram." not in host and not host.endswith("cdninstagram.com")
                    and not host.endswith("fbcdn.net") and key not in seen_links):
                seen_links.add(key)
                card = _link_card(href, og_budget)
                if card:
                    link_cards.append("")
                    link_cards.append("<!-- -->")
                    link_cards.append("")
                    link_cards += card

        lines = body_text.splitlines()
        first = lines[0].strip() if lines else "Threads"
        title = first[:80] or "Threads"
        # H1 제목과 본문 첫 줄 중복 제거(제목이 첫 줄 전체일 때만)
        body_out = "\n".join(lines[1:]).lstrip("\n") if (lines and first == title) else body_text
        author_disp = f"@{handle}" if handle else "Threads"
        parts = [_frontmatter(title, url, "threads", handle),
                 f"# {title}\n", f"**{author_disp}**\n", body_out]
        for u in imgs:
            parts.append(f"\n![]({u})")
        md = "\n".join(parts) + "\n" + "\n".join(link_cards) + f"\n\n---\n원문: {url}\n"
        return {"kind": "threads", "title": title, "author": handle,
                "markdown": cap_blockquote_depth(md),
                "meta": f"source=threads-embed; imgs={len(imgs)}"}
    except Exception:
        pass

    # 폴백: 기존 웹 추출(trafilatura)
    try:
        res = _extract_web(url)
        fallback_md = res.get("markdown") or ""
        if (res.get("meta") == "extractor=bs4"
                and len(fallback_md) <= 300
                and "Threads embed 추출 실패" in fallback_md):
            raise ValueError("Threads 본문 추출 실패: 빈 웹 추출 폴백")
        res["kind"] = "threads"
        res["markdown"] = (
            "> [!note] Threads embed 추출 실패 → best-effort 웹 추출. 필요 시 다듬으세요.\n\n"
            + res["markdown"]
        )
        return res
    except Exception as e:
        md = _frontmatter(url, url, "threads") + (
            f"# Threads\n\n원문: {url}\n\n> 본문 추출 실패: {e}\n"
        )
        return {"kind": "threads", "title": url, "author": "",
                "markdown": md, "meta": "threads-fallback"}


# ───────────────────────── 브런치 ─────────────────────────
def _extract_brunch(url: str) -> dict:
    """브런치: 서버렌더 HTML 의 .wrap_body(텍스트+이미지)를 마크다운으로.
    (safe_get 쿠키 자 덕분에 auto_login 리다이렉트 루프 없이 fetch 됨)"""
    from bs4 import BeautifulSoup
    from markdownify import markdownify as md2

    html = _fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")

    def meta(*names):
        for n in names:
            m = soup.find("meta", property=n) or soup.find("meta", attrs={"name": n})
            if m and (m.get("content") or "").strip():
                return m["content"].strip()
        return ""

    title = meta("og:title") or (soup.title.get_text(strip=True) if soup.title else url)
    author = meta("og:article:author", "author")
    body = soup.select_one(".wrap_body") or soup.select_one("article")
    if body is None:                       # 구조 못 찾으면 일반 웹 추출로 폴백
        res = _extract_web(url)
        res["kind"] = "brunch"
        return res
    for t in body(["script", "style"]):
        t.decompose()
    body_md = md2(str(body), heading_style="ATX") or ""
    body_md = re.sub(r"\n{3,}", "\n\n", body_md).strip()
    # 브런치 이미지/링크는 protocol-relative(//img...) → https 로 보정
    body_md = re.sub(r"(\]\()//", r"\1https://", body_md)
    fm = _frontmatter(title, url, "brunch", author)
    head = "" if body_md.lstrip().startswith("# ") else f"# {title}\n\n"
    md = fm + head + body_md + f"\n\n---\n원문: {url}\n"
    return {"kind": "brunch", "title": title or url, "author": author,
            "markdown": cap_blockquote_depth(md), "meta": "source=brunch"}


# ───────────────────────── 진입점 ─────────────────────────
def extract(url: str) -> dict:
    kind = detect_kind(url)
    if kind == "youtube":
        return _extract_youtube(url)
    if kind == "x":
        return _extract_x(url)
    if kind == "threads":
        return _extract_threads(url)
    if kind == "brunch":
        return _extract_brunch(url)
    return _extract_web(url)
