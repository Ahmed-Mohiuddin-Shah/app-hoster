"""Render release notes as sanitized HTML (Markdown → safe subset)."""

from __future__ import annotations

import logging

import bleach
import markdown
from markupsafe import Markup, escape

logger = logging.getLogger(__name__)

_EXTENSIONS = ["fenced_code", "tables", "nl2br", "sane_lists"]

# Allow typical Markdown output; strip scripts/onclick etc. via bleach.
_ALLOWED_TAGS = frozenset(
    {
        "p",
        "br",
        "div",
        "span",
        "strong",
        "em",
        "b",
        "i",
        "strike",
        "s",
        "del",
        "code",
        "pre",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "ul",
        "ol",
        "li",
        "blockquote",
        "a",
        "hr",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "img",
    }
)

_ALLOWED_ATTRS = {
    "a": ["href", "title", "rel"],
    "img": ["src", "alt", "title", "width", "height", "class"],
    "code": ["class"],
    "pre": ["class"],
    "th": ["colspan", "rowspan", "align"],
    "td": ["colspan", "rowspan", "align"],
}


def release_notes_html(text: str | None) -> Markup:
    raw = (text or "").strip()
    if not raw:
        return Markup("")
    try:
        md = markdown.Markdown(extensions=_EXTENSIONS, output_format="html")
        html = md.convert(raw)
        clean = bleach.clean(
            html,
            tags=_ALLOWED_TAGS,
            attributes=_ALLOWED_ATTRS,
            protocols=["http", "https", "mailto"],
            strip=True,
        )
        return Markup(clean)
    except Exception:
        logger.exception("release notes markdown render failed")
        return Markup(f'<p class="whitespace-pre-wrap">{escape(raw)}</p>')
