from __future__ import annotations

import os
import re
import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode, urlparse

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from models import (
    PLATFORMS,
    Release,
    SessionLocal,
    allowed_artifacts_for_platform,
    artifact_extension,
    build_timeline_tree,
    filter_by_platform,
    init_db,
    paginate_timeline_versions,
    is_valid_semver,
    latest_by_platform,
    media_type_for_artifact,
    sort_releases_desc,
    uploads_dir,
)
from schemas import ReleaseOut

load_dotenv()

UPLOAD_SECRET = os.environ.get("UPLOAD_SECRET", "")
PROJECT_NAME = os.environ.get("PROJECT_NAME", "App Host")
LOGO_SVG_PATH = os.environ.get("LOGO_SVG_PATH", "").strip()
MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB

PLATFORM_TAB_ORDER = ("android", "apple", "windows", "linux", "web")

try:
    TIMELINE_PER_PAGE = max(1, int(os.environ.get("TIMELINE_PER_PAGE", "8")))
except ValueError:
    TIMELINE_PER_PAGE = 8


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _resolve_logo_file() -> Path | None:
    if not LOGO_SVG_PATH:
        return None
    raw = Path(LOGO_SVG_PATH).expanduser()
    if not raw.is_absolute():
        raw = (Path(__file__).resolve().parent / raw).resolve()
    try:
        resolved = raw.resolve()
    except OSError:
        return None
    if not resolved.is_file() or resolved.suffix.lower() != ".svg":
        return None
    return resolved


def get_logo_url() -> str | None:
    return "/logo.svg" if _resolve_logo_file() else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    uploads_dir()
    yield


app = FastAPI(title="APK Host", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")


def list_sorted_releases(db: Session, platform: str | None = None) -> list[Release]:
    rows = list(db.scalars(select(Release)).all())
    if platform:
        if platform not in PLATFORMS:
            raise HTTPException(status_code=400, detail="Invalid platform")
        rows = filter_by_platform(rows, platform)
    return sort_releases_desc(rows)


def safe_download_filename(version: str, build_type: str, artifact_kind: str) -> str:
    ext = artifact_extension(artifact_kind)
    base = f"{version}_{build_type}".lower()
    base = re.sub(r"[^a-z0-9._-]+", "-", base).strip("-") or "app"
    if ext and not base.endswith(ext):
        base += ext
    elif not ext:
        base += ".bin"
    return base


def latest_platform_payload(m: dict[str, Release | None]) -> dict[str, dict | None]:
    out: dict[str, dict | None] = {}
    for k, v in m.items():
        if v is None:
            out[k] = None
        else:
            out[k] = {"version": v.version, "server_version": v.server_version}
    return out


def resolve_initial_tab(request: Request) -> str:
    tab = (request.query_params.get("tab") or "android").lower().strip()
    if tab not in PLATFORM_TAB_ORDER:
        return "android"
    return tab


def parse_timeline_page(request: Request, platform: str) -> int:
    raw = request.query_params.get(f"page_{platform}", "1")
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def timeline_query_href(request: Request, platform: str, timeline_page: int) -> str:
    page_key = f"page_{platform}"
    pairs: list[tuple[str, str]] = []
    for k, v in request.query_params.multi_items():
        if k == page_key or k == "tab":
            continue
        pairs.append((k, v))
    pairs.append(("tab", platform))
    if timeline_page > 1:
        pairs.append((page_key, str(timeline_page)))
    q = urlencode(pairs)
    path = request.url.path
    return f"{path}?{q}" if q else path


def build_timeline_pager(request: Request, platform: str, meta: dict) -> dict | None:
    if meta["total"] == 0:
        return None
    page = meta["page"]
    pages = meta["pages"]
    out = dict(meta)
    out["prev_href"] = timeline_query_href(request, platform, page - 1) if meta["has_prev"] else None
    out["next_href"] = timeline_query_href(request, platform, page + 1) if meta["has_next"] else None
    if meta.get("show") and pages <= 12:
        out["page_hrefs"] = [
            {"n": n, "href": timeline_query_href(request, platform, n), "current": n == page}
            for n in range(1, pages + 1)
        ]
    else:
        out["page_hrefs"] = []
    return out


def duplicate_release(
    db: Session,
    platform: str,
    version: str,
    build_type: str,
    server_version: str,
) -> bool:
    q = select(Release.id).where(
        Release.platform == platform,
        Release.version == version,
        Release.build_type == build_type,
        Release.server_version == server_version,
    )
    return db.scalar(q.limit(1)) is not None


@app.get("/logo.svg")
def logo_svg():
    path = _resolve_logo_file()
    if path is None:
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="image/svg+xml", filename="logo.svg")


@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    rows = list(db.scalars(select(Release)).all())
    latest_map = latest_by_platform(rows)
    initial_tab = resolve_initial_tab(request)

    timeline_trees: dict[str, list] = {}
    timeline_pagers: dict[str, dict | None] = {}
    for p in PLATFORM_TAB_ORDER:
        if p == "apple":
            timeline_trees[p] = []
            timeline_pagers[p] = None
            continue
        full_tree = build_timeline_tree(p, rows)
        page = parse_timeline_page(request, p)
        sliced, meta = paginate_timeline_versions(full_tree, page, TIMELINE_PER_PAGE)
        timeline_trees[p] = sliced
        timeline_pagers[p] = build_timeline_pager(request, p, meta)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "latest_by_platform": latest_map,
            "latest_platform_data": latest_platform_payload(latest_map),
            "timeline_trees": timeline_trees,
            "timeline_pagers": timeline_pagers,
            "initial_tab": initial_tab,
            "project_name": PROJECT_NAME,
            "logo_url": get_logo_url(),
            "platforms": sorted(PLATFORMS),
            "platform_tab_order": PLATFORM_TAB_ORDER,
        },
    )


@app.get("/releases")
def releases_json(platform: str | None = None, db: Session = Depends(get_db)):
    sorted_rows = list_sorted_releases(db, platform)
    data = [ReleaseOut.model_validate(r).model_dump(mode="json") for r in sorted_rows]
    return {"releases": data}


@app.get("/download/{release_id}")
def download(release_id: int, db: Session = Depends(get_db)):
    r = db.get(Release, release_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Release not found")
    if r.platform == "web" and r.web_url:
        return RedirectResponse(url=r.web_url, status_code=302)
    if not r.file_path:
        raise HTTPException(status_code=404, detail="No file for this release")
    path = uploads_dir() / r.file_path
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File missing on server")
    return FileResponse(
        path,
        filename=safe_download_filename(r.version, r.build_type, r.artifact_kind),
        media_type=media_type_for_artifact(r.artifact_kind),
    )


@app.post("/upload")
async def upload(
    db: Session = Depends(get_db),
    platform: str = Form(...),
    build_type: str = Form(...),
    artifact_kind: str = Form(...),
    version: str = Form(...),
    server_version: str = Form(...),
    release_notes: str = Form(""),
    secret_key: str = Form(...),
    web_url: str = Form(""),
    file: UploadFile | None = File(default=None),
):
    if not UPLOAD_SECRET:
        raise HTTPException(status_code=503, detail="Upload is not configured (missing UPLOAD_SECRET)")
    if not secrets.compare_digest(secret_key, UPLOAD_SECRET):
        raise HTTPException(status_code=403, detail="Invalid secret key")

    platform = platform.strip().lower()
    build_type = build_type.strip().lower()
    artifact_kind = artifact_kind.strip().lower()
    version = version.strip()
    server_version = server_version.strip()
    web_url = (web_url or "").strip()

    if platform not in PLATFORMS:
        raise HTTPException(status_code=422, detail="Invalid platform")
    if platform == "apple":
        raise HTTPException(status_code=400, detail="Apple uploads are not supported")
    if build_type not in ("debug", "release", "profile"):
        raise HTTPException(status_code=422, detail="build_type must be debug, release, or profile")

    allowed_art = allowed_artifacts_for_platform(platform)
    if artifact_kind not in allowed_art:
        raise HTTPException(status_code=422, detail="Invalid artifact_kind for this platform")

    if not version or not server_version:
        raise HTTPException(status_code=422, detail="version and server_version are required")

    if not is_valid_semver(version):
        raise HTTPException(
            status_code=422,
            detail="version must be a valid PEP 440 / semantic version (e.g. 1.2.0)",
        )

    if duplicate_release(db, platform, version, build_type, server_version):
        raise HTTPException(
            status_code=409,
            detail="A release already exists for this platform, version, build type, and server version",
        )

    rel_name = ""
    dest: Path | None = None

    if platform == "web":
        if artifact_kind != "web":
            raise HTTPException(status_code=422, detail="Web releases must use artifact web")
        if not web_url:
            raise HTTPException(status_code=422, detail="web_url is required for web platform")
        parsed = urlparse(web_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise HTTPException(status_code=422, detail="web_url must be a valid http(s) URL")
        row = Release(
            version=version,
            build_type=build_type,
            server_version=server_version,
            release_notes=release_notes or "",
            file_path="",
            platform=platform,
            artifact_kind="web",
            web_url=web_url,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return JSONResponse(status_code=201, content={"id": row.id, "version": row.version})

    if file is None:
        raise HTTPException(status_code=422, detail="file is required for this platform")

    ext = artifact_extension(artifact_kind)
    if platform == "android" and artifact_kind == "apk":
        filename = (file.filename or "").lower()
        content_type = (file.content_type or "").lower()
        if not filename.endswith(".apk") and "android.package-archive" not in content_type:
            raise HTTPException(status_code=422, detail="File must be an APK")

    body = await file.read()
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large")

    rel_name = f"{uuid.uuid4().hex}{ext}"
    dest = uploads_dir() / rel_name
    try:
        dest.write_bytes(body)
    except OSError:
        raise HTTPException(status_code=500, detail="Could not save file")

    row = Release(
        version=version,
        build_type=build_type,
        server_version=server_version,
        release_notes=release_notes or "",
        file_path=rel_name,
        platform=platform,
        artifact_kind=artifact_kind,
        web_url=None,
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
    except Exception:
        db.rollback()
        if dest is not None:
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
        raise HTTPException(status_code=500, detail="Could not save metadata")

    return JSONResponse(
        status_code=201,
        content={"id": row.id, "version": row.version},
    )
