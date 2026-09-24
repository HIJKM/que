"""SQLite 기반 ingest 아이템 저장소.

아이템 상태: pending(추출 대기) → extracted(추출 완료) | error(실패) → ingested(적재됨)
대화 본문(markdown)은 추출 산출물로 보관하고, ingest 시 inbox 로 기록한다.
"""
import hashlib
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from config import DB_PATH, INGEST_TARGETS


_BASE62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ra", "slof", "xmt"}


def _base62(value: int) -> str:
    if value <= 0:
        return "0"
    chars: list[str] = []
    while value:
        value, rem = divmod(value, len(_BASE62))
        chars.append(_BASE62[rem])
    return "".join(reversed(chars))


def _normalize_url(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
    except Exception:
        return (url or "").strip()
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    query_items = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in _TRACKING_QUERY_KEYS:
            continue
        query_items.append((key, value))
    query = urlencode(sorted(query_items), doseq=True)
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, query, ""))


def _make_share_code(item_id: int, url: str) -> str:
    digest = hashlib.sha256(_normalize_url(url).encode("utf-8")).hexdigest()[:6]
    return f"{_base62(item_id)}-{digest}"


def normalize_share_code(code: str) -> str:
    value = (code or "").strip()
    if value.lower().startswith("que:"):
        value = value[4:]
    return value


@contextmanager
def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def init_db() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                url          TEXT NOT NULL,
                normalized_url TEXT,
                share_code   TEXT,
                kind         TEXT NOT NULL DEFAULT 'web',
                status       TEXT NOT NULL DEFAULT 'pending',
                title        TEXT,
                author       TEXT,
                markdown     TEXT,
                meta_json    TEXT,
                error        TEXT,
                inbox_path   TEXT,
                created_at   REAL NOT NULL,
                bumped_at    REAL,
                extracted_at REAL,
                ingested_at  REAL
            )
            """
        )
        # 마이그레이션: 번역본(markdown_ko) + 번역 상태 컬럼 추가(없으면)
        cols = {row["name"] for row in c.execute("PRAGMA table_info(items)").fetchall()}
        if "share_code" not in cols:
            c.execute("ALTER TABLE items ADD COLUMN share_code TEXT")
        if "normalized_url" not in cols:
            c.execute("ALTER TABLE items ADD COLUMN normalized_url TEXT")
        if "bumped_at" not in cols:
            c.execute("ALTER TABLE items ADD COLUMN bumped_at REAL")
        if "markdown_ko" not in cols:
            c.execute("ALTER TABLE items ADD COLUMN markdown_ko TEXT")
        if "translation_status" not in cols:
            c.execute("ALTER TABLE items ADD COLUMN translation_status TEXT")
        if "translation_error" not in cols:
            c.execute("ALTER TABLE items ADD COLUMN translation_error TEXT")
        if "viewed_at" not in cols:
            c.execute("ALTER TABLE items ADD COLUMN viewed_at REAL")
            c.execute(
                """UPDATE items
                   SET viewed_at=COALESCE(extracted_at, ingested_at, created_at)
                   WHERE status IN ('extracted', 'ingested', 'error')"""
            )
        c.execute(
            """UPDATE items
               SET translation_status='done'
               WHERE markdown_ko IS NOT NULL
                 AND trim(markdown_ko) <> ''
                 AND (translation_status IS NULL OR translation_status='')"""
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS render_cache (
                item_id    INTEGER NOT NULL,
                view       TEXT NOT NULL,
                cache_key  TEXT NOT NULL,
                html       TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (item_id, view)
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS item_ingests (
                item_id     INTEGER NOT NULL,
                target      TEXT NOT NULL,
                path        TEXT NOT NULL,
                ingested_at REAL NOT NULL,
                PRIMARY KEY (item_id, target)
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS item_translations (
                item_id     INTEGER NOT NULL,
                engine      TEXT NOT NULL,
                markdown_ko TEXT,
                status      TEXT NOT NULL,
                error       TEXT,
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL,
                PRIMARY KEY (item_id, engine)
            )
            """
        )
        translation_cols = {row["name"] for row in c.execute("PRAGMA table_info(item_translations)").fetchall()}
        if "elapsed_seconds" not in translation_cols:
            c.execute("ALTER TABLE item_translations ADD COLUMN elapsed_seconds REAL")
        if "estimated_seconds" not in translation_cols:
            c.execute("ALTER TABLE item_translations ADD COLUMN estimated_seconds REAL")
        if "estimated_tokens" not in translation_cols:
            c.execute("ALTER TABLE item_translations ADD COLUMN estimated_tokens INTEGER")
        if "started_at" not in translation_cols:
            c.execute("ALTER TABLE item_translations ADD COLUMN started_at REAL")
        _backfill_share_codes(c)
        _backfill_normalized_urls(c)
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_items_share_code ON items(share_code)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_items_normalized_url ON items(normalized_url)")
        _backfill_item_translations(c)
        _backfill_item_ingests(c)


def _backfill_share_codes(c: sqlite3.Connection) -> None:
    rows = c.execute(
        "SELECT id, url FROM items WHERE share_code IS NULL OR trim(share_code)=''"
    ).fetchall()
    for row in rows:
        c.execute(
            "UPDATE items SET share_code=? WHERE id=?",
            (_make_share_code(int(row["id"]), row["url"] or ""), row["id"]),
        )


def _backfill_normalized_urls(c: sqlite3.Connection) -> None:
    rows = c.execute(
        "SELECT id, url FROM items WHERE normalized_url IS NULL OR trim(normalized_url)=''"
    ).fetchall()
    for row in rows:
        c.execute(
            "UPDATE items SET normalized_url=? WHERE id=?",
            (_normalize_url(row["url"] or ""), row["id"]),
        )


def _target_for_path(path: str) -> str:
    try:
        resolved = Path(path).resolve()
    except Exception:
        return "inbox"
    for target in INGEST_TARGETS:
        try:
            if target["path"].resolve() in (resolved, *resolved.parents):
                return target["key"]
        except Exception:
            continue
    return "inbox"


def _backfill_item_ingests(c: sqlite3.Connection) -> None:
    rows = c.execute(
        """SELECT id, inbox_path, ingested_at
           FROM items
           WHERE inbox_path IS NOT NULL
             AND trim(inbox_path) <> ''
             AND ingested_at IS NOT NULL"""
    ).fetchall()
    for row in rows:
        c.execute(
            """INSERT OR IGNORE INTO item_ingests (item_id, target, path, ingested_at)
               VALUES (?, ?, ?, ?)""",
            (row["id"], _target_for_path(row["inbox_path"]), row["inbox_path"], row["ingested_at"]),
        )


def _backfill_item_translations(c: sqlite3.Connection) -> None:
    rows = c.execute(
        """SELECT id, markdown_ko, translation_status, translation_error, extracted_at, created_at
           FROM items
           WHERE (markdown_ko IS NOT NULL AND trim(markdown_ko) <> '')
              OR translation_status IN ('pending', 'error')"""
    ).fetchall()
    now = time.time()
    for row in rows:
        status = "done" if (row["markdown_ko"] or "").strip() else (row["translation_status"] or "none")
        c.execute(
            """INSERT OR IGNORE INTO item_translations
               (item_id, engine, markdown_ko, status, error, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                row["id"],
                "v1",
                row["markdown_ko"],
                status,
                row["translation_error"],
                row["extracted_at"] or row["created_at"] or now,
                now,
            ),
        )


def add_item(url: str, kind: str) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO items (url, normalized_url, kind, status, created_at) VALUES (?,?,?,?,?)",
            (url, _normalize_url(url), kind, "pending", time.time()),
        )
        item_id = int(cur.lastrowid)
        c.execute(
            "UPDATE items SET share_code=? WHERE id=?",
            (_make_share_code(item_id, url), item_id),
        )
        return item_id


def add_or_bump_item(url: str, kind: str) -> tuple[int, bool]:
    """Create an item, or move the same normalized URL to the top of the list."""
    normalized_url = _normalize_url(url)
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        existing = c.execute(
            """SELECT id FROM items
               WHERE normalized_url=?
               ORDER BY COALESCE(bumped_at, created_at) DESC, id DESC
               LIMIT 1""",
            (normalized_url,),
        ).fetchone()
        if existing:
            item_id = int(existing["id"])
            c.execute("UPDATE items SET bumped_at=? WHERE id=?", (time.time(), item_id))
            return item_id, True

        now = time.time()
        cur = c.execute(
            """INSERT INTO items (url, normalized_url, kind, status, created_at, bumped_at)
               VALUES (?,?,?,?,?,?)""",
            (url, normalized_url, kind, "pending", now, now),
        )
        item_id = int(cur.lastrowid)
        c.execute(
            "UPDATE items SET share_code=? WHERE id=?",
            (_make_share_code(item_id, url), item_id),
        )
        return item_id, False


def add_imported_item(
    *,
    url: str,
    kind: str,
    title: str,
    markdown: str,
    author: Optional[str] = None,
) -> int:
    """Create an already-extracted item from caller markdown. Always inserts."""
    with _conn() as c:
        now = time.time()
        cur = c.execute(
            """INSERT INTO items (
                   url, normalized_url, kind, status, title, author, markdown,
                   created_at, bumped_at, extracted_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                url,
                _normalize_url(url),
                kind,
                "extracted",
                title,
                author,
                markdown,
                now,
                now,
                now,
            ),
        )
        item_id = int(cur.lastrowid)
        c.execute(
            "UPDATE items SET share_code=? WHERE id=?",
            (_make_share_code(item_id, url), item_id),
        )
        return item_id


def get_item(item_id: int) -> Optional[sqlite3.Row]:
    with _conn() as c:
        return c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()


ITEM_SORT_SQL = "COALESCE(bumped_at, created_at)"
LIST_DEFAULT_LIMIT = 20
LIST_MAX_LIMIT = 100


def encode_list_cursor(row: sqlite3.Row) -> str:
    sort_at = row["bumped_at"] if row["bumped_at"] is not None else row["created_at"]
    return f"{sort_at}:{row['id']}"


def decode_list_cursor(cursor: str) -> tuple[float, int]:
    parts = cursor.split(":", 1)
    if len(parts) != 2:
        raise ValueError("invalid cursor")
    sort_at, item_id = float(parts[0]), int(parts[1])
    if sort_at < 0 or item_id < 1:
        raise ValueError("invalid cursor")
    return sort_at, item_id


def _list_cursor_clause(cursor: Optional[str]) -> tuple[str, list]:
    if not cursor:
        return "", []
    sort_at, item_id = decode_list_cursor(cursor)
    return (
        f"AND ({ITEM_SORT_SQL} < ? OR ({ITEM_SORT_SQL} = ? AND id < ?))",
        [sort_at, sort_at, item_id],
    )


def _list_kind_clause(kind: Optional[str]) -> tuple[str, list]:
    if not kind or kind == "all":
        return "", []
    return "AND kind = ?", [kind]


def list_items() -> list[sqlite3.Row]:
    with _conn() as c:
        return c.execute(
            f"SELECT * FROM items ORDER BY {ITEM_SORT_SQL} DESC, id DESC"
        ).fetchall()


def list_items_page(
    *,
    limit: int = LIST_DEFAULT_LIMIT,
    cursor: Optional[str] = None,
    kind: Optional[str] = None,
) -> tuple[list[sqlite3.Row], Optional[str], bool]:
    limit = max(1, min(limit, LIST_MAX_LIMIT))
    kind_clause, kind_params = _list_kind_clause(kind)
    cursor_clause, cursor_params = _list_cursor_clause(cursor)
    sql = f"""SELECT * FROM items
              WHERE 1=1 {kind_clause} {cursor_clause}
              ORDER BY {ITEM_SORT_SQL} DESC, id DESC
              LIMIT ?"""
    params = [*kind_params, *cursor_params, limit + 1]
    with _conn() as c:
        rows = c.execute(sql, params).fetchall()
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    next_cursor = encode_list_cursor(rows[-1]) if has_more and rows else None
    return rows, next_cursor, has_more


def count_items(kind: Optional[str] = None) -> int:
    kind_clause, kind_params = _list_kind_clause(kind)
    with _conn() as c:
        row = c.execute(f"SELECT COUNT(*) AS count FROM items WHERE 1=1 {kind_clause}", kind_params).fetchone()
    return int(row["count"])


def search_items(query: str) -> list[sqlite3.Row]:
    """Search title, author, and original/translated body text."""
    escaped = (query.replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_"))
    pattern = f"%{escaped}%"
    with _conn() as c:
        return c.execute(
            f"""SELECT * FROM items
               WHERE title LIKE ? ESCAPE '\\'
                  OR author LIKE ? ESCAPE '\\'
                  OR markdown LIKE ? ESCAPE '\\'
                  OR markdown_ko LIKE ? ESCAPE '\\'
               ORDER BY {ITEM_SORT_SQL} DESC, id DESC""",
            (pattern, pattern, pattern, pattern),
        ).fetchall()


def search_items_page(
    query: str,
    *,
    limit: int = LIST_DEFAULT_LIMIT,
    cursor: Optional[str] = None,
    kind: Optional[str] = None,
) -> tuple[list[sqlite3.Row], Optional[str], bool]:
    limit = max(1, min(limit, LIST_MAX_LIMIT))
    escaped = (query.replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_"))
    pattern = f"%{escaped}%"
    kind_clause, kind_params = _list_kind_clause(kind)
    cursor_clause, cursor_params = _list_cursor_clause(cursor)
    sql = f"""SELECT * FROM items
              WHERE (title LIKE ? ESCAPE '\\'
                 OR author LIKE ? ESCAPE '\\'
                 OR markdown LIKE ? ESCAPE '\\'
                 OR markdown_ko LIKE ? ESCAPE '\\')
                 {kind_clause} {cursor_clause}
              ORDER BY {ITEM_SORT_SQL} DESC, id DESC
              LIMIT ?"""
    params = [pattern, pattern, pattern, pattern, *kind_params, *cursor_params, limit + 1]
    with _conn() as c:
        rows = c.execute(sql, params).fetchall()
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    next_cursor = encode_list_cursor(rows[-1]) if has_more and rows else None
    return rows, next_cursor, has_more


def count_search_items(query: str, kind: Optional[str] = None) -> int:
    escaped = (query.replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_"))
    pattern = f"%{escaped}%"
    kind_clause, kind_params = _list_kind_clause(kind)
    sql = f"""SELECT COUNT(*) AS count FROM items
               WHERE (title LIKE ? ESCAPE '\\'
                  OR author LIKE ? ESCAPE '\\'
                  OR markdown LIKE ? ESCAPE '\\'
                  OR markdown_ko LIKE ? ESCAPE '\\')
                  {kind_clause}"""
    params = [pattern, pattern, pattern, pattern, *kind_params]
    with _conn() as c:
        row = c.execute(sql, params).fetchone()
    return int(row["count"])


def get_item_by_share_code(code: str) -> Optional[sqlite3.Row]:
    with _conn() as c:
        return c.execute(
            "SELECT * FROM items WHERE share_code=?",
            (normalize_share_code(code),),
        ).fetchone()


def update_extraction(
    item_id: int,
    *,
    status: str,
    title: Optional[str] = None,
    author: Optional[str] = None,
    markdown: Optional[str] = None,
    meta_json: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    with _conn() as c:
        c.execute(
            """UPDATE items SET status=?, title=?, author=?, markdown=?,
                   meta_json=?, error=?, extracted_at=? WHERE id=?""",
            (status, title, author, markdown, meta_json, error, time.time(), item_id),
        )


def get_translation(item_id: int, engine: str = "v1") -> Optional[sqlite3.Row]:
    with _conn() as c:
        return c.execute(
            "SELECT * FROM item_translations WHERE item_id=? AND engine=?",
            (item_id, engine),
        ).fetchone()


def set_translation(item_id: int, markdown_ko: str, engine: str = "v1", *, promote: bool = True) -> None:
    with _conn() as c:
        now = time.time()
        c.execute(
            """INSERT INTO item_translations
               (item_id, engine, markdown_ko, status, error, created_at, updated_at)
               VALUES (?, ?, ?, 'done', NULL, ?, ?)
               ON CONFLICT(item_id, engine) DO UPDATE SET
                   markdown_ko=excluded.markdown_ko,
                   status='done',
                   error=NULL,
                   updated_at=excluded.updated_at""",
            (item_id, engine, markdown_ko, now, now),
        )
        if not promote:
            c.execute(
                "UPDATE items SET translation_status='done', translation_error=NULL WHERE id=?",
                (item_id,),
            )
            return
        c.execute(
            """UPDATE items
               SET markdown_ko=?, translation_status='done', translation_error=NULL
               WHERE id=?""",
            (markdown_ko, item_id),
        )


def set_translation_pending(
    item_id: int,
    engine: str = "v1",
    *,
    estimated_tokens: int | None = None,
    estimated_seconds: float | None = None,
) -> None:
    with _conn() as c:
        now = time.time()
        c.execute(
            """INSERT INTO item_translations
               (item_id, engine, markdown_ko, status, error, created_at, updated_at,
                started_at, estimated_tokens, estimated_seconds)
               VALUES (?, ?, NULL, 'pending', NULL, ?, ?, ?, ?, ?)
               ON CONFLICT(item_id, engine) DO UPDATE SET
                   status='pending',
                   error=NULL,
                   started_at=excluded.started_at,
                   estimated_tokens=excluded.estimated_tokens,
                   estimated_seconds=excluded.estimated_seconds,
                   updated_at=excluded.updated_at""",
            (item_id, engine, now, now, now, estimated_tokens, estimated_seconds),
        )
        c.execute(
            "UPDATE items SET translation_status='pending', translation_error=NULL WHERE id=?",
            (item_id,),
        )


def set_translation_error(item_id: int, error: str, engine: str = "v1") -> None:
    with _conn() as c:
        now = time.time()
        clipped = (error or "")[:1000]
        c.execute(
            """INSERT INTO item_translations
               (item_id, engine, markdown_ko, status, error, created_at, updated_at)
               VALUES (?, ?, NULL, 'error', ?, ?, ?)
               ON CONFLICT(item_id, engine) DO UPDATE SET
                   status='error',
                   error=excluded.error,
                   updated_at=excluded.updated_at""",
            (item_id, engine, clipped, now, now),
        )
        c.execute(
            "UPDATE items SET translation_status='error', translation_error=? WHERE id=?",
            (clipped, item_id),
        )


def set_translation_elapsed(item_id: int, engine: str, elapsed_seconds: float) -> None:
    with _conn() as c:
        c.execute(
            """UPDATE item_translations
               SET elapsed_seconds=?, updated_at=?
               WHERE item_id=? AND engine=?""",
            (float(elapsed_seconds), time.time(), item_id, engine),
        )


def translation_timing_samples(engine: str) -> list[sqlite3.Row]:
    with _conn() as c:
        return c.execute(
            """SELECT t.elapsed_seconds, length(i.markdown) AS markdown_chars
               FROM item_translations t
               JOIN items i ON i.id=t.item_id
               WHERE t.engine=?
                 AND t.status='done'
                 AND t.elapsed_seconds IS NOT NULL
                 AND i.markdown IS NOT NULL
                 AND length(i.markdown) > 0""",
            (engine,),
        ).fetchall()


def mark_stale_translations_error() -> int:
    """서버 재시작 후 남아 있는 pending 번역은 실행 중 worker가 없으므로 실패 처리."""
    with _conn() as c:
        c.execute(
            """UPDATE item_translations
               SET status='error',
                   error='translation interrupted by server restart',
                   updated_at=?
               WHERE status='pending'""",
            (time.time(),),
        )
        cur = c.execute(
            """UPDATE items
               SET translation_status='error',
                   translation_error='translation interrupted by server restart'
               WHERE translation_status='pending'"""
        )
        return int(cur.rowcount or 0)


def ingest_targets_for_item(item_id: int) -> list[str]:
    with _conn() as c:
        rows = c.execute(
            "SELECT target FROM item_ingests WHERE item_id=? ORDER BY ingested_at",
            (item_id,),
        ).fetchall()
        return [row["target"] for row in rows]


def ingest_count(item_id: int) -> int:
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM item_ingests WHERE item_id=?",
            (item_id,),
        ).fetchone()
        return int(row["n"] or 0)


def has_ingest_target(item_id: int, target: str) -> bool:
    with _conn() as c:
        row = c.execute(
            "SELECT 1 FROM item_ingests WHERE item_id=? AND target=?",
            (item_id, target),
        ).fetchone()
        return row is not None


def mark_ingested(item_id: int, target: str, inbox_path: str) -> None:
    with _conn() as c:
        now = time.time()
        c.execute(
            """INSERT INTO item_ingests (item_id, target, path, ingested_at)
               VALUES (?, ?, ?, ?)""",
            (item_id, target, inbox_path, now),
        )
        c.execute(
            "UPDATE items SET status=?, inbox_path=?, ingested_at=? WHERE id=?",
            ("ingested", inbox_path, now, item_id),
        )


def mark_viewed(item_id: int) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE items SET viewed_at=COALESCE(viewed_at, ?) WHERE id=?",
            (time.time(), item_id),
        )


def get_render_cache(item_id: int, view: str, cache_key: str) -> Optional[str]:
    with _conn() as c:
        row = c.execute(
            """SELECT html FROM render_cache
               WHERE item_id=? AND view=? AND cache_key=?""",
            (item_id, view, cache_key),
        ).fetchone()
        return row["html"] if row else None


def set_render_cache(item_id: int, view: str, cache_key: str, html: str) -> None:
    with _conn() as c:
        c.execute(
            """INSERT INTO render_cache (item_id, view, cache_key, html, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(item_id, view) DO UPDATE SET
                   cache_key=excluded.cache_key,
                   html=excluded.html,
                   updated_at=excluded.updated_at""",
            (item_id, view, cache_key, html, time.time()),
        )


def delete_item(item_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM item_ingests WHERE item_id=?", (item_id,))
        c.execute("DELETE FROM render_cache WHERE item_id=?", (item_id,))
        c.execute("DELETE FROM item_translations WHERE item_id=?", (item_id,))
        c.execute("DELETE FROM items WHERE id=?", (item_id,))
