"""Que 웹앱 설정 — 경로와 포트."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# 앱 포트
HOST = os.environ.get("QUE_HOST", "127.0.0.1").strip() or "127.0.0.1"
PORT = int(os.environ.get("QUE_PORT", "8788"))

# 앱 상태 DB (vault 와 무관, 앱 디렉터리 안)
DB_PATH = BASE_DIR / "data.db"

def _env_path(name: str, default: str = "") -> Path | None:
    raw = os.environ.get(name, default).strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _home_relative(path: Path) -> str:
    text = str(path.expanduser())
    home = str(Path.home())
    if text == home:
        return "~"
    prefix = home + os.sep
    if text.startswith(prefix):
        return "~/" + text[len(prefix):].replace(os.sep, "/")
    return text


# 적재 대상 allowlist. 경로는 환경변수. 기본 inbox는 ~/QueInbox.
# 빈 값이면 그 타깃은 빼고, 전부 비면 ingest는 꺼지며 ensure_inbox는 no-op.
INBOX_DIR = _env_path("QUE_INGEST_INBOX", "~/QueInbox")
MEMEX_RAW_DROPBOX_DIR = _env_path("QUE_INGEST_MEMEX_RAW_DROPBOX")
FLYWHEEL_RAW_DIR = _env_path("QUE_INGEST_FLYWHEEL_RAW")
INGEST_TARGETS = tuple(
    item for item in (
        {"key": "inbox", "label": "Quartz inbox", "path": INBOX_DIR} if INBOX_DIR is not None else None,
        {"key": "memex-raw-dropbox", "label": "Memex raw/dropbox", "path": MEMEX_RAW_DROPBOX_DIR} if MEMEX_RAW_DROPBOX_DIR is not None else None,
        {"key": "flywheel-raw", "label": "Flywheel raw", "path": FLYWHEEL_RAW_DIR} if FLYWHEEL_RAW_DIR is not None else None,
    ) if item is not None
)
DEFAULT_INGEST_TARGET = "inbox"

# 안전장치: 적재는 오직 allowlist에 있는 폴더로만 허용.
def ingest_target_options() -> list[dict]:
    options = []
    for target in INGEST_TARGETS:
        path = target["path"]
        options.append({
            "key": target["key"],
            "label": target["label"],
            "path": str(path),
            "relative_path": _home_relative(path),
            "default": target["key"] == DEFAULT_INGEST_TARGET,
        })
    return options


def ensure_ingest_target(key: str = DEFAULT_INGEST_TARGET) -> Path:
    selected = key if key else DEFAULT_INGEST_TARGET
    target = next((item for item in INGEST_TARGETS if item["key"] == selected), None)
    if target is None:
        raise ValueError("허용되지 않은 저장 위치입니다.")
    path = target["path"]
    path.mkdir(parents=True, exist_ok=True)
    resolved = path.resolve()
    allowed = {item["path"].resolve() for item in INGEST_TARGETS}
    if resolved not in allowed:
        raise ValueError("저장 위치가 허용 목록 밖입니다.")
    return path


# 이전 호출부 호환용. 허용 타깃이 없으면 폴더를 만들지 않는다.
def ensure_inbox() -> Path | None:
    if not INGEST_TARGETS:
        return None
    key = DEFAULT_INGEST_TARGET
    if not any(item["key"] == key for item in INGEST_TARGETS):
        key = INGEST_TARGETS[0]["key"]
    return ensure_ingest_target(key)


# ───────────────────────── 외부 API access ─────────────────────────
# 브라우저 앱은 로컬 개인 사용을 전제로 로그인 없이 동작한다.
# 외부 연동을 켤 때만 Bearer token을 선택적으로 사용한다.
import json

AUTH_FILE = BASE_DIR / "auth.json"

def load_api_token() -> str | None:
    """외부 API Bearer 토큰. 없으면 /api/v1 은 fail-safe 로 비활성화."""
    tok = os.environ.get("QUE_API_TOKEN")
    if tok and tok.strip():
        return tok.strip()
    if AUTH_FILE.exists():
        try:
            d = json.loads(AUTH_FILE.read_text())
            tok = d.get("api_token")
            if tok and str(tok).strip():
                return str(tok).strip()
        except Exception:
            return None
    return None
