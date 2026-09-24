from __future__ import annotations

import re
import secrets
import threading
import time
import uuid
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import extract
import store
from config import HOST, PORT, INBOX_DIR, ensure_inbox, ensure_ingest_target, load_api_token
import legacy_main as legacy

BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"

app = FastAPI(title="Que")
_API_TOKEN = load_api_token()


class AddItemPayload(BaseModel):
    url: str


class IngestPayload(BaseModel):
    view: str = "orig"
    target: str = "inbox"


class ImportItemPayload(BaseModel):
    markdown: str
    title: str
    url: str | None = None
    author: str | None = None
    kind: str | None = None


IMPORT_KINDS = frozenset({"web", "youtube", "x", "threads", "brunch", "md"})
MAX_IMPORT_BYTES = 5 * 1024 * 1024


def _valid_api_token(request: Request) -> bool:
    if not _API_TOKEN:
        return False
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return scheme.lower() == "bearer" and bool(token) and secrets.compare_digest(token.strip(), _API_TOKEN)


def _spa_index() -> Response:
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"detail": "frontend dist not built", "hint": "cd frontend && npm install && npm run build"}, status_code=503)


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path
    if path == "/health" or path.startswith("/assets/") or path.startswith("/static/") or path.startswith("/app-assets/"):
        return await call_next(request)
    if path.startswith("/api/v1/") or path == "/api/v1/items":
        if not _API_TOKEN:
            return JSONResponse({"detail": "api token not configured"}, status_code=503)
        if not _valid_api_token(request):
            return JSONResponse({"detail": "invalid api token"}, status_code=401)
        return await call_next(request)
    if path.startswith("/api/"):
        return await call_next(request)
    return await call_next(request)


@app.on_event("startup")
def startup() -> None:
    store.init_db()
    ensure_inbox()


app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
if (BASE_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(BASE_DIR / "assets")), name="assets")
if (FRONTEND_DIST / "app-assets").exists():
    app.mount("/app-assets", StaticFiles(directory=str(FRONTEND_DIST / "app-assets")), name="app-assets")


def _item_or_404(item_id: int) -> dict:
    row = store.get_item(item_id)
    if not row:
        raise HTTPException(status_code=404, detail="없는 항목")
    return legacy._row_to_dict(row)


def _item_list_response(
    rows: list,
    *,
    next_cursor: str | None,
    has_more: bool,
    total_count: int,
) -> dict:
    return {
        "items": [legacy._row_to_dict(row) for row in rows],
        "next_cursor": next_cursor,
        "has_more": has_more,
        "total_count": total_count,
    }


@app.get("/api/items")
def api_items(
    limit: int = Query(default=store.LIST_DEFAULT_LIMIT, ge=1, le=store.LIST_MAX_LIMIT),
    cursor: str | None = Query(default=None, max_length=64),
    kind: str | None = Query(default=None, max_length=32),
):
    try:
        rows, next_cursor, has_more = store.list_items_page(limit=limit, cursor=cursor, kind=kind)
    except ValueError:
        raise HTTPException(status_code=400, detail="잘못된 cursor 입니다.")
    return _item_list_response(
        rows,
        next_cursor=next_cursor,
        has_more=has_more,
        total_count=store.count_items(kind),
    )


@app.get("/api/items/search")
def api_search_items(
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=store.LIST_DEFAULT_LIMIT, ge=1, le=store.LIST_MAX_LIMIT),
    cursor: str | None = Query(default=None, max_length=64),
    kind: str | None = Query(default=None, max_length=32),
):
    query = q.strip()
    try:
        if query:
            rows, next_cursor, has_more = store.search_items_page(
                query, limit=limit, cursor=cursor, kind=kind,
            )
            total_count = store.count_search_items(query, kind)
        else:
            rows, next_cursor, has_more = store.list_items_page(
                limit=limit, cursor=cursor, kind=kind,
            )
            total_count = store.count_items(kind)
    except ValueError:
        raise HTTPException(status_code=400, detail="잘못된 cursor 입니다.")
    return _item_list_response(
        rows,
        next_cursor=next_cursor,
        has_more=has_more,
        total_count=total_count,
    )


@app.post("/api/items")
def api_add_item(payload: AddItemPayload):
    url = (payload.url or "").strip()
    if not re.match(r"^https?://", url):
        raise HTTPException(status_code=400, detail="http(s) URL 을 입력하세요.")
    kind = extract.detect_kind(url)
    item_id, existing = store.add_or_bump_item(url, kind)
    row = store.get_item(item_id)
    share_code = row["share_code"] if row else None
    if not existing:
        threading.Thread(target=legacy._run_extraction, args=(item_id, url), daemon=True).start()
    return JSONResponse(
        {
            "id": item_id,
            "share_code": share_code,
            "kind": row["kind"] if row else kind,
            "status": row["status"] if row else "pending",
            "existing": existing,
        },
        status_code=200 if existing else 202,
    )


def _resolve_import_identity(url: str | None, kind: str | None) -> tuple[str, str]:
    source = (url or "").strip()
    selected = (kind or "").strip().lower() or None
    if selected and selected not in IMPORT_KINDS:
        raise ValueError("허용되지 않은 kind 입니다.")
    if source:
        if not re.match(r"^https?://", source):
            raise ValueError("http(s) URL 을 입력하세요.")
        return source, selected or extract.detect_kind(source)
    return f"que://md/{uuid.uuid4().hex}", selected or "md"


def _import_markdown_item(payload: ImportItemPayload) -> dict:
    markdown = payload.markdown if payload.markdown is not None else ""
    if not markdown.strip():
        raise HTTPException(status_code=400, detail="마크다운이 없습니다.")
    if len(markdown.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=400, detail="마크다운이 너무 큽니다.")
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="제목을 입력하세요.")
    author = (payload.author or "").strip() or None
    try:
        url, kind = _resolve_import_identity(payload.url, payload.kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    item_id = store.add_imported_item(
        url=url,
        kind=kind,
        title=title,
        markdown=markdown,
        author=author,
    )
    row = store.get_item(item_id)
    return {
        "id": item_id,
        "share_code": row["share_code"] if row else None,
        "kind": kind,
        "status": "extracted",
        "url": url,
        "existing": False,
    }


@app.post("/api/items/import")
def api_import_item(payload: ImportItemPayload):
    return JSONResponse(_import_markdown_item(payload), status_code=201)


@app.get("/api/items/{item_id}")
def api_item(item_id: int, view: str = "orig"):
    row = store.get_item(item_id)
    if not row:
        raise HTTPException(status_code=404, detail="없는 항목")
    if row["status"] in ("extracted", "ingested"):
        store.mark_viewed(item_id)
    item = legacy._row_to_dict(row)
    html, effective = legacy._render_item_body(item, view)
    return {
        "item": item,
        "body": {"html": html, "view": effective},
        "ingest_targets": legacy._ingest_target_options_for_item(item),
    }


@app.get("/api/items/{item_id}/body")
def api_item_body(item_id: int, view: str = "orig"):
    item = _item_or_404(item_id)
    html, effective = legacy._render_item_body(item, view)
    return {"html": html, "view": effective}


@app.api_route("/api/items/{item_id}/translate", methods=["GET", "POST"])
def api_translate_disabled(item_id: int):
    raise HTTPException(status_code=410, detail="번역 기능은 공개 브랜치에서 임시 비활성화되었습니다.")


@app.get("/api/items/{item_id}/markdown")
def api_markdown(item_id: int, view: str = "orig"):
    item = _item_or_404(item_id)
    return Response(item.get("markdown") or "", media_type="text/markdown; charset=utf-8", headers={"X-Que-View": "orig"})


@app.post("/api/items/{item_id}/ingest")
def api_ingest(item_id: int, payload: IngestPayload):
    row = store.get_item(item_id)
    if not row:
        raise HTTPException(status_code=404, detail="없는 항목")
    item = legacy._row_to_dict(row)
    content, effective = item.get("markdown") or "", "orig"
    if not (content or "").strip():
        raise HTTPException(status_code=400, detail="추출된 마크다운이 없습니다.")
    if store.has_ingest_target(item_id, payload.target):
        raise HTTPException(status_code=400, detail="이미 저장된 위치입니다.")
    try:
        ingest_dir = ensure_ingest_target(payload.target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    fname = f"{time.strftime('%Y%m%d-%H%M%S')}-{legacy._slugify(row['title'])}.md"
    dest = (ingest_dir / fname).resolve()
    if ingest_dir.resolve() not in dest.parents:
        raise HTTPException(status_code=500, detail="저장 경로 위반")
    dest.write_text(content, encoding="utf-8")
    store.mark_ingested(item_id, payload.target, str(dest))
    return {"ok": True, "path": str(dest), "target": payload.target}


@app.delete("/api/items/{item_id}")
def api_delete(item_id: int):
    store.delete_item(item_id)
    return {"ok": True}


@app.get("/api/v1/items")
def public_items():
    return {"items": [legacy._public_item_summary(legacy._row_to_dict(row)) for row in store.list_items()]}


@app.post("/api/v1/items")
def public_import_item(payload: ImportItemPayload):
    return JSONResponse(_import_markdown_item(payload), status_code=201)


@app.get("/api/v1/items/by-code/{code}")
def public_item_by_code(code: str):
    row = store.get_item_by_share_code(code)
    if not row:
        raise HTTPException(status_code=404, detail="없는 항목")
    return legacy._public_item_detail(legacy._row_to_dict(row))


@app.get("/api/v1/items/{item_id}")
def public_item(item_id: int):
    return legacy._public_item_detail(_item_or_404(item_id))


@app.get("/health")
def health():
    return {"status": "ok", "inbox": str(INBOX_DIR) if INBOX_DIR else "", "app": "que"}


@app.get("/{path:path}")
def spa_fallback(path: str):
    return _spa_index()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host=HOST, port=PORT, reload=False)
