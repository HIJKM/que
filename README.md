# que

<p align="center">
  <strong>a local-first read-later inbox for the web.</strong>
</p>

<p align="center">
  <a href="#install">install</a> · <a href="#quick-start">quick start</a> · <a href="#configuration">configuration</a> · <a href="#limitations">limitations</a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-666666?labelColor=333333" alt="MIT license" /></a>
</p>

---

Que saves links, extracts readable content, and lets you read it later in a small local web app.
It is designed for personal use on your own computer, with optional access from a trusted LAN or VPN.

- **save links** — add URLs from the browser and keep them in a local SQLite database
- **extract content** — turn web pages, YouTube, X, Threads, and Brunch posts into Markdown
- **read comfortably** — browse an inbox and open a focused reading view
- **ingest locally** — write finished Markdown into folders you explicitly allow
- **bring your own setup** — no hosted service, account, or login required

The browser app is served by FastAPI and the interface is a React/Vite SPA. External URL fetching happens on the machine running Que.

## install

Requirements: Python 3.10+, Node.js, and npm.

```bash
git clone https://github.com/HIJKM/que.git
cd que

python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

cd frontend
npm ci
npm run build
cd ..
```

## quick start

```bash
./.venv/bin/python -m backend.app.main
```

Open <http://127.0.0.1:8788>.

The default inbox is `~/QueInbox`. Set `QUE_INGEST_INBOX` before starting Que if you want another folder:

```bash
QUE_INGEST_INBOX="$PWD/inbox" ./.venv/bin/python -m backend.app.main
```

To use Que from another device on the same trusted LAN or VPN:

```bash
QUE_HOST=0.0.0.0 ./.venv/bin/python -m backend.app.main
```

Then open `http://<server-ip>:8788` from that device.

## configuration

| variable | purpose | default |
| --- | --- | --- |
| `QUE_HOST` | backend listen address | `127.0.0.1` |
| `QUE_PORT` | backend port | `8788` |
| `QUE_INGEST_INBOX` | local Markdown inbox | `~/QueInbox` |
| `QUE_INGEST_MEMEX_RAW_DROPBOX` | optional ingest target | disabled |
| `QUE_INGEST_FLYWHEEL_RAW` | optional ingest target | disabled |
| `QUE_RENDER_URL` | optional Threads renderer | `http://127.0.0.1:8799/render` |

`que-render` is optional. Without it, Que still runs and uses its extraction fallback for Threads where possible.

## limitations

- Que has no browser login or user authentication. Anyone who can reach the server can read, add, delete, fetch, and ingest items.
- Keep it on localhost, a trusted LAN, or a VPN. Do not expose it to the public internet or use port forwarding.
- Translation is temporarily disabled in this open-source branch.
- YouTube, X, Threads, Brunch, and other third-party services may change their access rules, terms, rate limits, or response formats.

Check the server with:

```bash
curl -fsS http://127.0.0.1:8788/health
```

## development

Run the backend on port `8790` and use the Vite development server:

```bash
QUE_PORT=8790 ./.venv/bin/python -m backend.app.main
cd frontend
npm run dev
```

Run the backend tests from the repository root:

```bash
./.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

## license

Que is licensed under the [MIT License](LICENSE).
