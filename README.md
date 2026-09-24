# Que

Que는 웹에서 글을 모아 저장하고 읽는 개인용 read-later 앱이다. FastAPI 백엔드(`backend/app/main.py`)가 항목을 SQLite(`store.py`, 로컬 `data.db`)에 두고, `extract.py`가 URL 종류에 따라 본문을 Markdown으로 뽑는다. 일반 웹은 trafilatura와 readability, YouTube는 자막과 임베드, X는 FxEmbed(`api.fxtwitter.com`), Threads와 Brunch는 전용 추출 경로를 쓴다. React SPA(`frontend/`)는 목록과 읽기 화면을 제공하고, 서버 sanitizer를 거친 HTML만 `MarkdownBody`에 넣는다. 저장(ingest)은 `config.py`에 적힌 허용 폴더로만 Markdown 파일을 쓴다. 각자 자신의 컴퓨터에서 실행하는 앱이며, 별도 호스팅 서비스는 제공하지 않는다. 제3자 URL fetch도 이 프로세스가 돌아가는 머신에서 일어난다.

<!-- 스크린샷: 목록 화면. 파일을 넣은 뒤 아래 주석을 해제한다.
![목록](docs/screenshot-list.png)
-->

<!-- 스크린샷: 읽기 화면. 파일을 넣은 뒤 아래 주석을 해제한다.
![읽기](docs/screenshot-detail.png)
-->

## 요구 사항

- Python 3.10+
- Node.js (프론트엔드 빌드)
- Threads 동적 렌더를 쓰려면 로컬 `que-render` (`QUE_RENDER_URL`, 기본 `http://127.0.0.1:8799/render`)

## 설치

```sh
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cd frontend && npm install && npm run build
cd ..
```

이어서 필요하면 **설정**을 끝낸 다음 서버를 띄운다. 브라우저 앱은 로그인 없이 로컬에서 바로 열린다. 기동 시 `ensure_inbox()`가 설정된 inbox 폴더를 만든다. 기본값은 `~/QueInbox`이므로, 다른 경로를 쓰려면 서버를 켜기 전에 환경변수를 지정한다. 모든 ingest 경로를 비우면 폴더를 만들지 않고 ingest는 비활성이다.

```sh
./.venv/bin/python -m backend.app.main
```

기본 주소는 `http://127.0.0.1:8788`. 백엔드는 `QUE_HOST`(기본 `127.0.0.1`)와 `QUE_PORT`(기본 `8788`)로 listen한다. 다른 기기에서 접근해야 할 때만 `QUE_HOST=0.0.0.0`으로 명시한다. 프론트엔드 빌드 산출물(`frontend/dist`)이 없으면 SPA는 503을 반환한다.

## 접근 범위와 보안

Que는 개인용 도구이며 브라우저 앱에 로그인이나 사용자 인증이 없다. 기본값인
`QUE_HOST=127.0.0.1`에서는 실행한 컴퓨터에서만 접근할 수 있다. 다른 기기에서
사용해야 할 때는 신뢰할 수 있는 LAN 또는 VPN 안에서만 다음처럼 listen한다.

```sh
QUE_HOST=0.0.0.0 ./.venv/bin/python -m backend.app.main
```

접속 가능한 기기는 목록 조회, URL 추가, 삭제, ingest, 외부 URL fetch를 수행할
수 있다. 인터넷에 포트를 직접 공개하거나 포트포워딩하지 말고, 방화벽과 VPN의
접근 제어를 사용한다. `/api/v1`의 선택적 Bearer token은 브라우저 앱의 `/api`
경로를 보호하지 않는다.

프론트엔드 개발 서버:

```sh
QUE_PORT=8790 ./.venv/bin/python -m backend.app.main
cd frontend && npm run dev
```

Vite(`frontend/vite.config.ts`)는 `/api`, `/assets`, `/static`, `/health`를 `QUE_DEV_API`(기본 `http://127.0.0.1:8790`)로 프록시한다. 백엔드를 8788에 띄운 채로 Vite를 쓰려면 `QUE_DEV_API=http://127.0.0.1:8788 npm run dev`.

헬스체크:

```sh
curl -fsS http://127.0.0.1:8788/health
```

## 기능 제한과 외부 서비스

- 공개 배포본에서는 번역 기능을 임시 비활성화했다. 관련 API는 `410`을 반환한다.
- `que-render`는 선택 서비스다. 설치하지 않아도 앱은 실행되지만, Threads의
  동적 렌더링 품질이 제한될 수 있으며 추출 경로의 폴백이 사용된다.
- YouTube, X, Threads, Brunch 등 제3자 서비스의 접근 정책, 이용약관, rate
  limit, 응답 형식 변경은 각 사용자가 확인해야 한다. Que는 이 서비스들을
  호스팅하거나 사용 권한을 보장하지 않는다.

## 설정

Que는 `.env` 파일을 자동으로 읽지 않는다. 키 목록은 [`.env.example`](.env.example)에 있다. 값을 채운 `.env`를 쓰려면 셸에서 export한 뒤 프로세스를 띄운다.

```sh
set -a
source .env
set +a
./.venv/bin/python -m backend.app.main
```

외부 API token은 환경변수를 우선하고, 없으면 로컬 `auth.json`의 `api_token`을 사용한다.

### 1. Ingest 경로

저장은 `config.py` allowlist에 있는 경로로만 허용된다. 경로는 환경변수로 정한다.

| 키 | 역할 | 기본 |
| --- | --- | --- |
| `QUE_INGEST_INBOX` | 기본 inbox (`key=inbox`) | `~/QueInbox` |
| `QUE_INGEST_MEMEX_RAW_DROPBOX` | 선택 타깃 (`key=memex-raw-dropbox`) | 빈 값(비활성) |
| `QUE_INGEST_FLYWHEEL_RAW` | 선택 타깃 (`key=flywheel-raw`) | 빈 값(비활성) |

`~`는 홈 디렉터리로 펼친다. 값을 비우면 그 타깃은 목록에서 빠진다. 세 값을 모두 비우면 ingest UI/API는 허용 위치가 없고, 기동 시 폴더를 만들지 않는다.

### 2. 선택 설정

| 키 | 역할 | 기본 |
| --- | --- | --- |
| `QUE_HOST` | 백엔드 listen 주소 | `127.0.0.1` |
| `QUE_PORT` | 백엔드 포트 | `8788` |
| `QUE_RENDER_URL` | Threads 렌더 서비스 | `http://127.0.0.1:8799/render` |
| `QUE_RENDER_TOKEN` | 렌더 서비스 토큰 | 빈 문자열 |
| `QUE_RENDER_TIMEOUT` | 렌더 타임아웃(초) | `70` |
| `QUE_DEV_API` | Vite 개발 프록시 대상 (`frontend/vite.config.ts`) | `http://127.0.0.1:8790` |

## 로컬 상태

아래는 실행 산출물이며 git에 포함하지 않는다.

- `data.db`
- `auth.json`
- `logs/`
- `.venv/`
- `frontend/dist/`
- `frontend/node_modules/`

## 라이선스

[MIT](LICENSE). Copyright (c) 2026 HIJKM.
