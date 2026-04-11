# app-hoster

A small web application for hosting application releases across several platforms. It provides a timeline-style UI, authenticated uploads, download links, optional web redirects for web releases, and JSON endpoints for tooling and compatibility checks.

Stack: **FastAPI**, **Jinja2**, **SQLite** (via SQLAlchemy), **Tailwind CSS**-style utility classes in templates, and **uv** for dependency management.

## Features

- Per-platform tabs (Android, iOS, macOS placeholders, Windows, Linux, Web) with a paginated build timeline.
- Upload releases with metadata (version, build type, server version, artifact kind, optional web URL).
- Protected upload and server-link ingestion using a shared secret (`UPLOAD_SECRET`).
- File downloads and optional external redirect for web artifacts.
- `GET /api-version` for client compatibility checks.
- Optional logo from `./svgs/` and configurable display name.

## Requirements

- **Python 3.11+**
- [**uv**](https://docs.astral.sh/uv/) (recommended; used by `run.sh`)

## Quick start

1. Clone or copy this repository and enter the project directory.

2. Create a local environment file:

   ```bash
   cp .env.example .env
   ```

3. Edit `.env` and set **`UPLOAD_SECRET`** to a long random string. Without it, upload routes will reject requests in production-oriented setups.

4. Install dependencies and start the app:

   ```bash
   ./run.sh
   ```

   This runs `uv sync` then `uv run fastapi run` with a single worker. Open the URL shown in the terminal (by default FastAPI’s dev server prints a local address).

Alternatively, after `uv sync`:

```bash
uv run fastapi run --entrypoint main:app --workers 1
```

## Configuration

| Variable | Purpose |
|----------|---------|
| `UPLOAD_SECRET` | Secret required for authenticated uploads and server-link uploads. |
| `API_VERSION` | Returned by `GET /api-version` as JSON `{"version": "..."}`. |
| `PROJECT_NAME` | Shown in the UI (default: `App Host`). |
| `DATABASE_URL` | SQLAlchemy URL (default: SQLite file `releases.db` in the project directory). |
| `LOGO_SVG` | Basename of an SVG under `./svgs/` (default: `logo.svg`). |
| `TIMELINE_PER_PAGE` | Number of timeline rows per platform page (default: `8`). |

See `.env.example` for commented defaults.

## Project layout

| Path | Role |
|------|------|
| `main.py` | FastAPI app, routes, static mount for `/svgs`. |
| `models.py` | ORM models, DB init, timeline helpers, platform rules. |
| `schemas.py` | Pydantic schemas for API responses. |
| `templates/` | HTML templates and partials. |
| `svgs/` | Icons and optional logo asset. |
| `run.sh` | Convenience script to sync and run the server. |

## License

This work is licensed under **[Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/)** (**CC BY 4.0**, SPDX: `CC-BY-4.0`). You may share, adapt, and use the material for any purpose, including commercially, as long as you give **appropriate credit** as described in the license.

- Full legal text: [`LICENSE`](LICENSE) (official `legalcode.txt` from Creative Commons).
- Attribution line and SPDX id: [`NOTICES`](NOTICES).

Creative Commons [recommends against using CC licenses for software](https://creativecommons.org/faq/#can-i-apply-a-creative-commons-license-to-software) in favor of dedicated software licenses (for example MIT or Apache-2.0), mainly because CC does not address patents or typical source-distribution practice. CC BY 4.0 is still a valid choice if you prefer it; many projects use MIT or Apache-2.0 for code instead.
