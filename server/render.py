"""Markdown → HTML for the preview pane.

Raw HTML in notes is escaped (html=False), frontmatter is hidden, `- [ ]`
items become real checkboxes, and every block carries data-line so the
preview can scroll with the editor and toggle checkboxes in the source.
"""
import posixpath
import re
from urllib.parse import quote

from markdown_it import MarkdownIt
from markdown_it.token import Token

from server.vault import split_frontmatter

_md = MarkdownIt("commonmark", {"html": False, "breaks": True}).enable(["table", "strikethrough"])
_TASK_RE = re.compile(r"^\[([ xX])\][ \t]+")
_EXTERNAL_RE = re.compile(r"^([a-z][a-z0-9+.-]*:|/|#)", re.I)


def _strip_leading(children: list[Token], count: int) -> None:
    for child in children:
        if count <= 0:
            return
        if child.type not in ("text", "text_special"):
            return
        take = min(count, len(child.content))
        child.content = child.content[take:]
        count -= take


def _asset_url(src: str, note_rel: str | None) -> str:
    if not src or _EXTERNAL_RE.match(src) or note_rel is None:
        return src
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(note_rel), src))
    if joined.startswith(".."):
        return src
    return "/vault-file/" + quote(joined)


def render(content: str, note_rel: str | None = None) -> dict:
    meta, body, offset = split_frontmatter(content)
    tokens = _md.parse(body)

    for i, token in enumerate(tokens):
        if token.map and token.nesting == 1:
            token.attrSet("data-line", str(token.map[0] + offset))
        if token.type != "inline" or not token.children:
            continue

        if i >= 2 and tokens[i - 1].type == "paragraph_open" and tokens[i - 2].type == "list_item_open":
            match = _TASK_RE.match(token.content)
            if match:
                checked = match.group(1) != " "
                _strip_leading(token.children, match.end())
                item = tokens[i - 2]
                line = (item.map[0] + offset) if item.map else -1
                box = Token("html_inline", "", 0)
                box.content = (f'<input type="checkbox" class="task-cb" data-line="{line}"'
                               f'{" checked" if checked else ""}>')
                token.children.insert(0, box)
                item.attrJoin("class", "task-item done" if checked else "task-item")

        for child in token.children:
            if child.type == "image":
                child.attrSet("src", _asset_url(child.attrGet("src") or "", note_rel))

    return {"html": _md.renderer.render(tokens, _md.options, {}), "meta": meta}
