from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version
from sqlalchemy import DateTime, Integer, String, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


PLATFORMS = frozenset({"android", "apple", "windows", "linux", "web"})
BUILD_TYPES = frozenset({"debug", "release", "profile"})

ARTIFACT_ANDROID = frozenset({"apk"})
ARTIFACT_LINUX = frozenset({"deb", "rpm", "tar_gz"})
ARTIFACT_WINDOWS = frozenset({"exe", "msi", "zip"})
ARTIFACT_WEB = frozenset({"web"})

BUILD_TYPE_COLORS = {
    "debug": "#ef4444",
    "release": "#22c55e",
    "profile": "#f97316",
}


class Release(Base):
    __tablename__ = "releases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    build_type: Mapped[str] = mapped_column(String(32), nullable=False)
    server_version: Mapped[str] = mapped_column(String(64), nullable=False)
    release_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    file_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="android")
    artifact_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="apk")
    web_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


def is_valid_semver(v: str) -> bool:
    try:
        Version(v)
        return True
    except InvalidVersion:
        return False


def database_url() -> str:
    return os.environ.get("DATABASE_URL", "sqlite:///./releases.db")


def make_engine():
    url = database_url()
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(url, connect_args=connect_args)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _existing_columns(conn) -> set[str]:
    rows = conn.execute(text("PRAGMA table_info(releases)")).fetchall()
    return {r[1] for r in rows}


def migrate_db() -> None:
    """SQLite ALTER TABLE for existing installs."""
    with engine.begin() as conn:
        if not conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='releases'")).fetchone():
            return
        cols = _existing_columns(conn)
        if "platform" not in cols:
            conn.execute(text("ALTER TABLE releases ADD COLUMN platform VARCHAR(32) NOT NULL DEFAULT 'android'"))
        if "artifact_kind" not in cols:
            conn.execute(text("ALTER TABLE releases ADD COLUMN artifact_kind VARCHAR(32) NOT NULL DEFAULT 'apk'"))
        if "web_url" not in cols:
            conn.execute(text("ALTER TABLE releases ADD COLUMN web_url TEXT"))
        conn.execute(
            text(
                "UPDATE releases SET platform = 'android' WHERE platform IS NULL OR platform = ''"
            )
        )
        conn.execute(
            text(
                "UPDATE releases SET artifact_kind = 'apk' WHERE artifact_kind IS NULL OR artifact_kind = ''"
            )
        )


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    migrate_db()


def uploads_dir() -> Path:
    root = Path(__file__).resolve().parent
    d = root / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sort_releases_desc(releases: list[Release]) -> list[Release]:
    def key(r: Release) -> tuple[Version, datetime]:
        return (Version(r.version), r.created_at)

    return sorted(releases, key=key, reverse=True)


def filter_by_platform(releases: list[Release], platform: str) -> list[Release]:
    return [r for r in releases if r.platform == platform]


def latest_for_platform(releases: list[Release], platform: str) -> Release | None:
    rows = filter_by_platform(releases, platform)
    return sort_releases_desc(rows)[0] if rows else None


def latest_release_for_platform(releases: list[Release], platform: str) -> Release | None:
    """Newest semver among release builds only (excludes profile/debug). Used for header version labels."""
    rows = [r for r in filter_by_platform(releases, platform) if r.build_type == "release"]
    return sort_releases_desc(rows)[0] if rows else None


def latest_by_platform(releases: list[Release]) -> dict[str, Release | None]:
    """Per platform: latest *release* build (app + server version for UI chrome)."""
    out: dict[str, Release | None] = {}
    for p in sorted(PLATFORMS):
        out[p] = latest_release_for_platform(releases, p)
    return out


def _artifact_sort_key(ak: str) -> tuple[int, str]:
    order = {"deb": 0, "rpm": 1, "tar_gz": 2, "apk": 0, "exe": 0, "msi": 1, "zip": 2, "web": 0}
    return (order.get(ak, 99), ak)


def build_timeline_tree(platform: str, releases: list[Release]) -> list[dict[str, Any]]:
    """
    Tree: version -> build_type -> (optional artifact tier) -> leaves (Release rows).
    Artifact tier appears when more than one distinct artifact_kind exists under (version, build_type).
    """
    rels = filter_by_platform(releases, platform)
    by_version: dict[str, list[Release]] = defaultdict(list)
    for r in rels:
        by_version[r.version].append(r)

    tree: list[dict[str, Any]] = []
    for ver in sorted(by_version.keys(), key=lambda v: Version(v), reverse=True):
        vrows = by_version[ver]
        by_bt: dict[str, list[Release]] = defaultdict(list)
        for r in vrows:
            by_bt[r.build_type].append(r)

        build_nodes: list[dict[str, Any]] = []
        def _bt_order(b: str) -> int:
            return {"release": 0, "profile": 1, "debug": 2}.get(b, 9)

        for bt in sorted(by_bt.keys(), key=_bt_order):
            items = sorted(by_bt[bt], key=lambda r: r.created_at, reverse=True)
            color = BUILD_TYPE_COLORS.get(bt, "#39FF14")
            by_art: dict[str, list[Release]] = defaultdict(list)
            for r in items:
                by_art[r.artifact_kind].append(r)

            use_artifact_tier = len(by_art) > 1
            if use_artifact_tier:
                art_nodes = []
                for ak in sorted(by_art.keys(), key=_artifact_sort_key):
                    leaves = sorted(by_art[ak], key=lambda r: r.created_at, reverse=True)
                    art_nodes.append({"artifact_kind": ak, "leaves": leaves})
                build_nodes.append(
                    {
                        "build_type": bt,
                        "color": color,
                        "artifact_nodes": art_nodes,
                        "leaves": None,
                    }
                )
            else:
                build_nodes.append(
                    {
                        "build_type": bt,
                        "color": color,
                        "artifact_nodes": None,
                        "leaves": items,
                    }
                )

        all_flat: list[Release] = []
        for bn in build_nodes:
            if bn["artifact_nodes"]:
                for an in bn["artifact_nodes"]:
                    all_flat.extend(an["leaves"])
            elif bn["leaves"]:
                all_flat.extend(bn["leaves"])
        all_flat.sort(key=lambda r: r.created_at, reverse=True)

        if len(all_flat) <= 1:
            tree.append(
                {
                    "version": ver,
                    "build_nodes": build_nodes,
                    "leaf_count": len(all_flat),
                    "all_leaves": all_flat,
                    "simple": True,
                }
            )
        else:
            vnode: dict[str, Any] = {"version": ver, "build_nodes": build_nodes, "simple": False}
            _annotate_timeline_layout(vnode)
            tree.append(vnode)
    return tree


def _bezier_branch(x1: float, y1: float, x2: float, y2: float) -> str:
    """
    Smooth cubic from (x1,y1) to (x2,y2).

    Near-horizontal runs use control points on the same y as the endpoints so tangents stay
    horizontal — avoids the old “dip / S” in the middle. Near-vertical runs keep vertical tangents.
    """
    if abs(x2 - x1) < 0.5 and abs(y2 - y1) < 0.5:
        return f"M {x1} {y1} L {x2} {y2}"
    dx, dy = x2 - x1, y2 - y1

    # Nearly horizontal: cubic with horizontal tangents at both ends (no vertical bulge).
    if abs(dy) <= max(1.0, abs(dx) * 0.07):
        dx_abs = abs(dx)
        pull = min(dx_abs * 0.42, 16.0)
        pull = max(pull, 3.0)
        if 2 * pull > dx_abs * 0.92:
            pull = max(dx_abs * 0.38, 1.0)
        sx = 1.0 if dx >= 0 else -1.0
        return f"M {x1} {y1} C {x1 + sx * pull} {y1}, {x2 - sx * pull} {y2}, {x2} {y2}"

    # Nearly vertical: cubic with vertical tangents at both ends (no sideways bulge).
    if abs(dx) <= max(1.0, abs(dy) * 0.07):
        dy_abs = abs(dy)
        pull = min(dy_abs * 0.42, 16.0)
        pull = max(pull, 3.0)
        if 2 * pull > dy_abs * 0.92:
            pull = max(dy_abs * 0.38, 1.0)
        sy = 1.0 if dy >= 0 else -1.0
        return f"M {x1} {y1} C {x1} {y1 + sy * pull}, {x2} {y2 - sy * pull}, {x2} {y2}"

    # General diagonal: single gentle bend, controls biased along the chord.
    return (
        f"M {x1} {y1} C "
        f"{x1 + dx * 0.48} {y1 + dy * 0.08}, "
        f"{x1 + dx * 0.52} {y1 + dy * 0.92}, "
        f"{x2} {y2}"
    )


def _curve_along_y(x: float, y1: float, y2: float) -> str:
    """Straight vertical segment at x (same-x bus). Curved S was visually wobbly."""
    return f"M {x} {y1} L {x} {y2}"


def _annotate_timeline_layout(vnode: dict[str, Any]) -> None:
    """
    Rows with depth-based indent + SVG: zinc junction dot on MAIN_X where each branch leaves the timeline,
    colored smooth branches per build / artifact / leaf; sibling leaves share a straight vertical bus.
    """
    # Align with timeline.html: SVG is shifted -ml-10 so MAIN_X sits on the main dot column.
    MAIN_X = 8.0
    X_BUILD = 36.0
    X_ART = 64.0
    X_LEAF = 92.0
    row_leaf_h = 108
    hdr_bt = 34
    hdr_art = 30
    top_pad = 20.0
    bottom_pad = 18.0
    graph_w = 108.0

    y = top_pad
    rows: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    colored_paths: list[dict[str, Any]] = []

    def add_node(cx: float, cy: float, fill: str, kind: str, *, r: float = 5.0) -> None:
        nodes.append({"cx": cx, "cy": cy, "fill": fill, "kind": kind, "r": r})

    def add_path(d: str, stroke: str, sw: float = 2.5) -> None:
        colored_paths.append({"d": d, "stroke": stroke, "sw": sw})

    for bn in vnode["build_nodes"]:
        col = bn["color"]
        cy_build = y + hdr_bt / 2
        rows.append(
            {
                "kind": "h_build",
                "text": f"{vnode['version']} – {bn['build_type']}",
                "color": col,
                "y0": y,
                "h": hdr_bt,
                "depth": 1,
                "cy": cy_build,
            }
        )
        add_node(MAIN_X, cy_build, "#a1a1aa", "rail_junction", r=6.0)
        add_node(X_BUILD, cy_build, col, "build")
        add_path(_bezier_branch(MAIN_X, cy_build, X_BUILD, cy_build), col, 2.5)
        y += hdr_bt

        if bn["artifact_nodes"]:
            bus_y_build = cy_build
            for an in bn["artifact_nodes"]:
                cy_art = y + hdr_art / 2
                if cy_art > bus_y_build + 1:
                    add_path(_curve_along_y(X_BUILD, bus_y_build, cy_art), col, 2.0)
                bus_y_build = cy_art
                rows.append(
                    {
                        "kind": "h_art",
                        "text": f"{vnode['version']} – {bn['build_type']} – {an['artifact_kind']}",
                        "color": col,
                        "y0": y,
                        "h": hdr_art,
                        "depth": 2,
                        "cy": cy_art,
                    }
                )
                add_node(X_ART, cy_art, col, "artifact")
                add_path(_bezier_branch(X_BUILD, cy_art, X_ART, cy_art), col, 2.5)
                y += hdr_art
                px_bus = X_ART
                py_art = cy_art
                leaves = an["leaves"]
                prev_leaf_cy: float | None = None
                for li, r in enumerate(leaves):
                    cy_leaf = y + row_leaf_h / 2
                    rows.append(
                        {
                            "kind": "leaf",
                            "release": r,
                            "color": col,
                            "y0": y,
                            "h": row_leaf_h,
                            "depth": 3,
                            "cy": cy_leaf,
                        }
                    )
                    add_node(X_LEAF, cy_leaf, col, "leaf")
                    if li == 0:
                        if cy_leaf > py_art + 1:
                            add_path(_curve_along_y(px_bus, py_art, cy_leaf), col, 2.0)
                        add_path(_bezier_branch(px_bus, cy_leaf, X_LEAF, cy_leaf), col, 2.5)
                    else:
                        if prev_leaf_cy is not None and cy_leaf > prev_leaf_cy + 1:
                            add_path(_curve_along_y(px_bus, prev_leaf_cy, cy_leaf), col, 2.0)
                        add_path(_bezier_branch(px_bus, cy_leaf, X_LEAF, cy_leaf), col, 2.5)
                    prev_leaf_cy = cy_leaf
                    y += row_leaf_h
                bus_y_build = prev_leaf_cy if prev_leaf_cy is not None else cy_art
        else:
            leaves = bn["leaves"] or []
            px_bus = X_BUILD
            py_b = cy_build
            prev_leaf_cy: float | None = None
            for li, r in enumerate(leaves):
                cy_leaf = y + row_leaf_h / 2
                rows.append(
                    {
                        "kind": "leaf",
                        "release": r,
                        "color": col,
                        "y0": y,
                        "h": row_leaf_h,
                        "depth": 2,
                        "cy": cy_leaf,
                    }
                )
                add_node(X_LEAF, cy_leaf, col, "leaf")
                if li == 0:
                    if cy_leaf > py_b + 1:
                        add_path(_curve_along_y(px_bus, py_b, cy_leaf), col, 2.0)
                    add_path(_bezier_branch(px_bus, cy_leaf, X_LEAF, cy_leaf), col, 2.5)
                else:
                    if prev_leaf_cy is not None and cy_leaf > prev_leaf_cy + 1:
                        add_path(_curve_along_y(px_bus, prev_leaf_cy, cy_leaf), col, 2.0)
                    add_path(_bezier_branch(px_bus, cy_leaf, X_LEAF, cy_leaf), col, 2.5)
                prev_leaf_cy = cy_leaf
                y += row_leaf_h

    gh = y + bottom_pad

    vnode["display_rows"] = rows
    vnode["graph_height"] = gh
    vnode["graph_width"] = graph_w
    vnode["graph_paths"] = colored_paths
    vnode["graph_nodes"] = nodes
    vnode["graph_main_x"] = MAIN_X
    vnode["stem_above"] = int(top_pad)

    leaf_rows = [r for r in rows if r["kind"] == "leaf"]
    vnode["leaf_count"] = len(leaf_rows)

    all_leaves: list[Release] = []
    for b in vnode["build_nodes"]:
        if b["artifact_nodes"]:
            for an in b["artifact_nodes"]:
                all_leaves.extend(an["leaves"])
        elif b["leaves"]:
            all_leaves.extend(b["leaves"])
    all_leaves.sort(key=lambda r: r.created_at, reverse=True)
    vnode["all_leaves"] = all_leaves


def artifact_extension(kind: str) -> str:
    return {
        "apk": ".apk",
        "deb": ".deb",
        "rpm": ".rpm",
        "tar_gz": ".tar.gz",
        "exe": ".exe",
        "msi": ".msi",
        "zip": ".zip",
        "web": "",
    }.get(kind, ".bin")


def allowed_artifacts_for_platform(platform: str) -> frozenset[str]:
    if platform == "android":
        return ARTIFACT_ANDROID
    if platform == "linux":
        return ARTIFACT_LINUX
    if platform == "windows":
        return ARTIFACT_WINDOWS
    if platform == "web":
        return ARTIFACT_WEB
    return frozenset()


def media_type_for_artifact(kind: str) -> str:
    return {
        "apk": "application/vnd.android.package-archive",
        "deb": "application/vnd.debian.binary-package",
        "rpm": "application/x-rpm",
        "tar_gz": "application/gzip",
        "exe": "application/vnd.microsoft.portable-executable",
        "msi": "application/x-msdownload",
        "zip": "application/zip",
        "web": "text/plain",
    }.get(kind, "application/octet-stream")
