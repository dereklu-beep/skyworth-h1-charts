#!/usr/bin/env python3
"""Publish an HTML report to Feishu Drive or convert it to native docx blocks.

The module has no third-party import at import time.  Network operations import
``requests`` lazily; conversion, planning, and every ``--dry`` path use only the
Python standard library.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable


BASE = "https://open.feishu.cn/open-apis"
WRITE_DELAY = 0.35
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
SKIP_TAGS = {"script", "style", "template", "button", "canvas", "svg"}
SKIP_CLASSES = {
    "toolbar", "editbar", "chart-edit", "panel", "pact", "viewsw", "mini",
    "xdel", "toc",
}
TITLE_CLASSES = {"mtitle", "sub", "sub2"}
BADGES = {"事实", "计算", "推断"}
TEXT_KEYS = {
    2: "text",
    3: "heading1",
    4: "heading2",
    5: "heading3",
    12: "bullet",
    13: "ordered",
}
MAX_TABLE_CREATE_ROWS = 9
MAX_TABLE_COLUMNS = 9
MAX_BATCH_UPDATE_REQUESTS = 200


class Node:
    """Minimal DOM node used by the stdlib HTML parser."""

    def __init__(self, tag: str = "", attrs: Iterable[tuple[str, str | None]] = ()):
        self.tag = tag.lower()
        self.attrs = {key: value or "" for key, value in attrs}
        self.children: list[Node | str] = []
        self.parent: Node | None = None

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def elements(self) -> Iterable["Node"]:
        for child in self.children:
            if isinstance(child, Node):
                yield child


class DOMParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, attrs)
        node.parent = self.stack[-1]
        self.stack[-1].children.append(node)
        if tag.lower() not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, attrs)
        node.parent = self.stack[-1]
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def parse_dom(source: str) -> Node:
    parser = DOMParser()
    parser.feed(source)
    parser.close()
    return parser.root


def descendants(node: Node) -> Iterable[Node]:
    for child in node.elements():
        yield child
        yield from descendants(child)


def find_node(node: Node, *, node_id: str | None = None, tag: str | None = None) -> Node | None:
    for candidate in (node, *descendants(node)):
        if node_id is not None and candidate.attrs.get("id") != node_id:
            continue
        if tag is not None and candidate.tag != tag:
            continue
        return candidate
    return None


def clean_text(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value).strip()
    # Comparisons are made readable in Feishu and cannot be confused with markup.
    return (
        value.replace("≤", "不超过")
        .replace("≥", "不低于")
        .replace("<", "低于")
        .replace(">", "超过")
    )


def node_text(node: Node) -> str:
    parts: list[str] = []

    def visit(item: Node | str) -> None:
        if isinstance(item, str):
            parts.append(item)
            return
        if item.tag in SKIP_TAGS or item.classes & SKIP_CLASSES:
            return
        if item.tag == "br":
            parts.append(" ")
            return
        raw_badge = clean_text("".join(x for x in item.children if isinstance(x, str)))
        if "t" in item.classes and raw_badge in BADGES:
            parts.append(f"〔{raw_badge}〕")
            return
        for child in item.children:
            visit(child)

    visit(node)
    return clean_text("".join(parts))


def text_block(content: str, block_type: int = 2, *, bold: bool = False) -> dict[str, Any]:
    content = clean_text(content)
    text_run: dict[str, Any] = {"content": content}
    if bold:
        text_run["text_element_style"] = {"bold": True}
    return {
        "block_type": block_type,
        TEXT_KEYS[block_type]: {"elements": [{"text_run": text_run}]},
    }


def _table_rows(table: Node) -> list[list[Node]]:
    rows: list[list[Node]] = []
    for candidate in descendants(table):
        if candidate.tag != "tr":
            continue
        # Exclude rows belonging to a nested table.
        ancestor = candidate.parent
        while ancestor is not None and ancestor is not table:
            if ancestor.tag == "table":
                break
            ancestor = ancestor.parent
        if ancestor is not table:
            continue
        rows.append([child for child in candidate.elements() if child.tag in {"th", "td"}])
    return rows


def table_blocks(table: Node) -> list[dict[str, Any]]:
    source_rows = _table_rows(table)
    if not source_rows:
        return []
    occupied: dict[tuple[int, int], dict[str, Any]] = {}
    max_column = 0
    for row_index, source_cells in enumerate(source_rows):
        column = 0
        for cell in source_cells:
            while (row_index, column) in occupied:
                column += 1
            try:
                colspan = max(1, int(cell.attrs.get("colspan", "1")))
                rowspan = max(1, int(cell.attrs.get("rowspan", "1")))
            except ValueError:
                colspan = rowspan = 1
            ancestor = cell.parent
            in_thead = False
            while ancestor is not None and ancestor is not table:
                if ancestor.tag == "thead":
                    in_thead = True
                    break
                ancestor = ancestor.parent
            value = {"text": node_text(cell), "bold": cell.tag == "th" or in_thead}
            for dy in range(rowspan):
                for dx in range(colspan):
                    occupied[(row_index + dy, column + dx)] = (
                        value if dx == 0 and dy == 0 else {"text": "", "bold": False}
                    )
            column += colspan
            max_column = max(max_column, column)
    row_count = max((position[0] for position in occupied), default=-1) + 1
    has_thead = any(candidate.tag == "thead" for candidate in descendants(table))
    groups = (
        [list(range(max_column))]
        if max_column <= MAX_TABLE_COLUMNS
        else [
            [0, *range(start, min(start + MAX_TABLE_COLUMNS - 1, max_column))]
            for start in range(1, max_column, MAX_TABLE_COLUMNS - 1)
        ]
    )
    result: list[dict[str, Any]] = []
    for columns in groups:
        property_ = {"row_size": row_count, "column_size": len(columns)}
        if has_thead:
            property_["header_row"] = True
        cells = [
            occupied.get((row, column), {"text": "", "bold": False})
            for row in range(row_count)
            for column in columns
        ]
        result.append({
            "block_type": 31,
            "table": {"property": property_},
            "_cells": cells,
        })
    return result


def table_block(table: Node) -> dict[str, Any] | None:
    """Compatibility helper for tables that fit in one Feishu column group."""
    converted = table_blocks(table)
    if len(converted) > 1:
        raise ValueError("table has more than 9 columns; use table_blocks()")
    return converted[0] if converted else None


def _figure_title(node: Node) -> str:
    preferred = {"ft", "cap", "ex-title", "chart-title"}
    for child in descendants(node):
        if child.classes & preferred or child.tag == "figcaption":
            value = node_text(child)
            if value:
                return value
    return ""


def convert_source(source: str) -> dict[str, Any]:
    """Convert only rendered ``#sheet`` content into an intermediate docx plan."""
    dom = parse_dom(source)
    sheet = find_node(dom, node_id="sheet")
    if sheet is None:
        raise ValueError("rendered DOM must contain #sheet")

    blocks: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    page_title = ""

    def append_text(value: str, block_type: int = 2, *, bold: bool = False) -> bool:
        value = clean_text(value)
        if value:
            blocks.append(text_block(value, block_type, bold=bold))
            return True
        return False

    def walk(node: Node) -> bool:
        nonlocal page_title
        if node.tag in SKIP_TAGS:
            skipped[node.tag] += 1
            return False
        if node.classes & SKIP_CLASSES:
            skipped["controls"] += 1
            return False
        if node.tag == "h1":
            value = node_text(node)
            if value:
                page_title = page_title or value
            return append_text(value, 3)
        if node.tag == "h2":
            return append_text(node_text(node), 4)
        if node.classes & TITLE_CLASSES:
            return append_text(node_text(node), 5)
        if node.tag == "table" and "d" in node.classes:
            converted = table_blocks(node)
            if converted:
                blocks.extend(converted)
                return True
            return False
        if node.tag == "figure":
            title = _figure_title(node)
            if title:
                append_text(title)
            append_text("图表见 HTML 版")
            skipped["chart_visuals"] += 1
            for child in descendants(node):
                value = node_text(child)
                if value.startswith("来源："):
                    append_text(value)
                    break
            return True
        if node.tag == "li":
            parent_tag = node.parent.tag if node.parent is not None else ""
            list_type = 13 if parent_tag == "ol" else 12 if parent_tag == "ul" else 2
            return append_text(node_text(node), list_type)
        if node.tag == "p" or node.classes & {"src", "chg-src", "ex-src"}:
            return append_text(node_text(node))
        if node.tag in {"h3", "h4"}:
            return append_text(node_text(node), 5)
        if "mod" in node.classes and not any(
            child.classes & TITLE_CLASSES for child in node.elements()
        ):
            children = list(node.elements())
            title_child: Node | None = None
            for child in children:
                if child.tag in {"b", "strong"}:
                    title_child = child
                    break
                meaningful = [
                    item for item in child.children
                    if isinstance(item, Node)
                    or (isinstance(item, str) and item.strip())
                ]
                if (
                    len(meaningful) == 1
                    and isinstance(meaningful[0], Node)
                    and meaningful[0].tag in {"b", "strong"}
                ):
                    title_child = child
                    break
                if child.tag in {"table", "p", "ul", "ol"}:
                    break
            if title_child is not None:
                append_text(node_text(title_child), 5)
                for child in children:
                    if child is not title_child:
                        walk(child)
                return True
        produced = False
        for child in node.elements():
            produced = walk(child) or produced
        # The report also uses leaf divs and definition lists for compact KPI
        # prose. Preserve those as paragraphs when no semantic child emitted a
        # block, without serialising their HTML/CSS.
        if not produced and node.tag in {"div", "dt", "dd", "header", "footer", "aside"}:
            produced = append_text(node_text(node))
        return produced

    for child in sheet.elements():
        walk(child)
    if not blocks:
        raise ValueError(
            "#sheet has no publishable content; pass a rendered DOM snapshot "
            "(render_dom() can create one from raw HTML)"
        )
    if not page_title:
        title_node = find_node(dom, tag="title")
        page_title = node_text(title_node) if title_node else "财务报告"
    return {
        "title": page_title,
        "blocks": blocks,
        "skipped": dict(sorted(skipped.items())),
    }


def convert_html(path: str | os.PathLike[str]) -> dict[str, Any]:
    source = Path(path).read_text(encoding="utf-8")
    try:
        return convert_source(source)
    except ValueError:
        if 'id="report-tpl"' not in source:
            raise
    return convert_source(render_dom(path))


def render_dom(path: str | os.PathLike[str], output_path: str | os.PathLike[str] | None = None) -> str:
    """Render a raw local HTML file with headless Chrome and return its DOM snapshot."""
    chrome = next(
        (candidate for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
         if (candidate := shutil.which(name))),
        None,
    )
    if not chrome:
        raise RuntimeError("no Chrome/Chromium executable found")
    uri = Path(path).resolve().as_uri()
    # Chrome prints the DOM once virtual time expires but may never exit while
    # the page keeps timers or network requests alive, so stop it at </html>.
    with tempfile.TemporaryDirectory(prefix="publish-feishu-chrome-") as profile:
        proc = subprocess.Popen(
            [
                chrome, "--headless=new", "--no-sandbox", "--disable-gpu",
                f"--user-data-dir={profile}", "--no-first-run",
                "--dump-dom", "--virtual-time-budget=8000", uri,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        chunks: list[bytes] = []
        watchdog = threading.Timer(180, proc.kill)
        watchdog.start()
        try:
            while True:
                chunk = proc.stdout.read1(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"</html>" in b"".join(chunks[-2:]):
                    break
        finally:
            watchdog.cancel()
            proc.kill()
            proc.wait()
    dom = b"".join(chunks).decode("utf-8", errors="replace")
    if "</html>" not in dom:
        raise RuntimeError("headless Chrome did not produce a complete DOM snapshot")
    if output_path is not None:
        Path(output_path).write_text(dom, encoding="utf-8")
    return dom


def public_block(block: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in block.items() if not key.startswith("_")}


def chunk_children(children: list[dict[str, Any]], size: int = 50) -> list[list[dict[str, Any]]]:
    if size < 1 or size > 50:
        raise ValueError("Feishu children batches must contain between 1 and 50 blocks")
    return [children[index:index + size] for index in range(0, len(children), size)]


def _append_url(doc_id: str, parent_id: str | None = None) -> str:
    parent_id = parent_id or doc_id
    return (
        f"{BASE}/docx/v1/documents/{doc_id}/blocks/{parent_id}/children"
        "?document_revision_id=-1"
    )


def _block_url(doc_id: str, block_id: str) -> str:
    return f"{BASE}/docx/v1/documents/{doc_id}/blocks/{block_id}"


def _batch_update_url(doc_id: str) -> str:
    return (
        f"{BASE}/docx/v1/documents/{doc_id}/blocks/batch_update"
        "?document_revision_id=-1"
    )


def _table_create_block(block: dict[str, Any]) -> dict[str, Any]:
    rows, columns = _table_shape(block)
    if rows < 1:
        raise ValueError("cannot create an empty zero-row Feishu table")
    if not 1 <= columns <= MAX_TABLE_COLUMNS:
        raise ValueError(
            f"Feishu table column count must be 1..{MAX_TABLE_COLUMNS}; got {columns}"
        )
    result = public_block(block)
    result["table"] = {"property": dict(result["table"]["property"])}
    result["table"]["property"]["row_size"] = min(rows, MAX_TABLE_CREATE_ROWS)
    return result


def _text_elements(content: str, *, bold: bool = False) -> list[dict[str, Any]]:
    return text_block(content, bold=bold)["text"]["elements"]


def _batch_update_request(
    text_block_id: str, content: str, *, bold: bool = False,
) -> dict[str, Any]:
    return {
        "block_id": text_block_id,
        "update_text_elements": {
            "elements": _text_elements(content, bold=bold),
        },
    }


def _batch_update_operations(
    doc_id: str, requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "method": "PATCH",
            "url": _batch_update_url(doc_id),
            "json": {"requests": requests[index:index + MAX_BATCH_UPDATE_REQUESTS]},
        }
        for index in range(0, len(requests), MAX_BATCH_UPDATE_REQUESTS)
    ]


def content_operations(doc_id: str, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build deterministic dry operations with bindings for server-created IDs."""
    operations: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    cell_updates: list[dict[str, Any]] = []
    table_number = 0

    def flush() -> None:
        nonlocal pending
        for chunk in chunk_children(pending):
            operations.append({
                "method": "POST",
                "url": _append_url(doc_id),
                "json": {"children": chunk},
            })
        pending = []

    for block in blocks:
        if block["block_type"] != 31:
            pending.append(public_block(block))
            if len(pending) == 50:
                flush()
            continue
        flush()
        table_number += 1
        rows, columns = _table_shape(block)
        created_table = _table_create_block(block)
        operations.append({
            "method": "POST",
            "url": _append_url(doc_id),
            "json": {"children": [created_table]},
            "response_binding": f"table_{table_number}_block_id",
            "response_path": "data.children[0].block_id",
        })
        for _ in range(max(0, rows - MAX_TABLE_CREATE_ROWS)):
            operations.append({
                "method": "PATCH",
                "url": (
                    _block_url(doc_id, f"${{table_{table_number}_block_id}}")
                    + "?document_revision_id=-1"
                ),
                "json": {"insert_table_row": {"row_index": -1}},
            })
        operations.append({
            "method": "GET",
            "url": _block_url(doc_id, f"${{table_{table_number}_block_id}}"),
            "response_binding": f"table_{table_number}_cells",
            "response_path": "data.block.table.cells",
            "assert": {"cell_count": rows * columns},
        })
        for index, cell in enumerate(block["_cells"]):
            if not cell["text"]:
                continue
            cell_updates.append(_batch_update_request(
                f"${{text_block_by_cell[table_{table_number}_cells[{index}]]}}",
                cell["text"],
                bold=cell["bold"],
            ))
    flush()
    if cell_updates:
        operations.append({
            "method": "GET",
            "url": f"{BASE}/docx/v1/documents/{doc_id}/blocks",
            "query": {"page_size": 500, "page_token": "${next_page_token}"},
            "paginate": True,
            "response_binding": "text_block_by_cell",
            "response_transform": "map block_type=2 items by parent_id",
        })
        operations.extend(_batch_update_operations(doc_id, cell_updates))
    return operations


def new_doc_plan(report: dict[str, Any], title: str | None, folder_token: str | None) -> dict[str, Any]:
    chosen_title = title or report["title"]
    create_payload = {"title": chosen_title, "folder_token": folder_token or ""}
    operations = [{
        "method": "POST",
        "url": f"{BASE}/docx/v1/documents",
        "json": create_payload,
        "response_binding": "document_id",
    }]
    operations.extend(content_operations("${document_id}", report["blocks"]))
    return {
        "mode": "docx-create",
        "title": chosen_title,
        "content_blocks": report["blocks"],
        "skipped": report["skipped"],
        "operations": operations,
    }


def _items(existing: Any) -> list[dict[str, Any]]:
    if isinstance(existing, list):
        return existing
    if not isinstance(existing, dict):
        return []
    data = existing.get("data", existing)
    for key in ("items", "blocks"):
        if isinstance(data.get(key), list):
            return data[key]
    return []


def _block_id(block: dict[str, Any]) -> str:
    return str(block.get("block_id") or block.get("id") or "")


def _block_type(block: dict[str, Any]) -> int:
    try:
        return int(block.get("block_type"))
    except (TypeError, ValueError):
        return -1


def _existing_text(block: dict[str, Any]) -> str:
    key = TEXT_KEYS.get(_block_type(block))
    if not key:
        return ""
    elements = (block.get(key) or {}).get("elements") or []
    parts: list[str] = []
    for element in elements:
        run = element.get("text_run") or {}
        parts.append(str(run.get("content") or ""))
    return "".join(parts)


def _desired_text(block: dict[str, Any]) -> str:
    return _existing_text(block)


def _top_blocks(existing: Any, doc_id: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    items = _items(existing)
    by_id = {_block_id(item): item for item in items if _block_id(item)}
    root = by_id.get(doc_id)
    if root and isinstance(root.get("children"), list):
        return [by_id[child] for child in root["children"] if child in by_id], by_id
    direct = [item for item in items if str(item.get("parent_id") or "") == doc_id]
    if direct:
        return direct, by_id
    referenced = {
        str(child)
        for item in items
        for child in (item.get("children") or [])
        if isinstance(child, str)
    }
    candidates = [
        item for item in items
        if _block_type(item) not in {1, 32}
        and _block_id(item) not in referenced
        and not item.get("parent_id")
    ]
    if candidates:
        return candidates, by_id
    # Convenient offline fixture form: top-level blocks first, nested blocks carry parent_id.
    return [
        item for item in items
        if _block_type(item) not in {1, 32} and not item.get("parent_id")
    ], by_id


def _patch_operation(doc_id: str, block_id: str, content: str) -> dict[str, Any]:
    return {
        "method": "PATCH",
        "url": f"{BASE}/docx/v1/documents/{doc_id}/blocks/{block_id}",
        "json": {
            "update_text_elements": {
                "elements": [{"text_run": {"content": content}}]
            }
        },
    }


def _table_shape(block: dict[str, Any]) -> tuple[int, int]:
    prop = (block.get("table") or {}).get("property") or {}
    try:
        return int(prop.get("row_size", 0)), int(prop.get("column_size", 0))
    except (TypeError, ValueError):
        return 0, 0


def _table_cell_ids(block: dict[str, Any]) -> list[str]:
    table = block.get("table") or {}
    values = table.get("cells")
    if not isinstance(values, list):
        values = block.get("children") or []
    return [str(value) for value in values]


def _text_block_ids_for_cell(
    cell_id: str, by_id: dict[str, dict[str, Any]],
) -> list[str]:
    cell = by_id.get(cell_id, {})
    ids = [
        str(value) for value in (cell.get("children") or [])
        if str(value) in by_id and _block_type(by_id[str(value)]) == 2
    ]
    if ids:
        return ids
    return [
        block_id for block_id, item in by_id.items()
        if str(item.get("parent_id") or "") == cell_id and _block_type(item) == 2
    ]


def _existing_bold(block: dict[str, Any]) -> bool:
    elements = (block.get("text") or {}).get("elements") or []
    if not elements:
        return False
    run = elements[0].get("text_run") or {}
    return bool((run.get("text_element_style") or {}).get("bold"))


def plan_updates(
    doc_id: str,
    desired_blocks: list[dict[str, Any]],
    existing: Any,
    *,
    replace_all: bool = False,
) -> dict[str, Any]:
    """Align existing blocks by order/type and produce only changed-text PATCH calls."""
    top, by_id = _top_blocks(existing, doc_id)
    if replace_all:
        operations: list[dict[str, Any]] = []
        if top:
            operations.append({
                "method": "DELETE",
                "url": (
                    f"{BASE}/docx/v1/documents/{doc_id}/blocks/{doc_id}/children/batch_delete"
                    "?document_revision_id=-1"
                ),
                "json": {"start_index": 0, "end_index": len(top)},
            })
        operations.extend(content_operations(doc_id, desired_blocks))
        return {"ok": True, "replace_all": True, "diff": [], "operations": operations}

    differences: list[str] = []
    desired_types = [_block_type(block) for block in desired_blocks]
    existing_types = [_block_type(block) for block in top]
    if len(top) != len(desired_blocks):
        differences.append(
            f"top-level block count differs: existing={len(top)}, desired={len(desired_blocks)}"
        )
    for index, (wanted, found) in enumerate(zip(desired_types, existing_types)):
        if wanted != found:
            differences.append(f"block {index} type differs: existing={found}, desired={wanted}")
    if differences:
        return {"ok": False, "replace_all": False, "diff": differences, "operations": []}

    operations: list[dict[str, Any]] = []
    cell_patch_requests: list[dict[str, Any]] = []
    for index, (wanted, found) in enumerate(zip(desired_blocks, top)):
        block_type = _block_type(wanted)
        if block_type in TEXT_KEYS:
            wanted_text = _desired_text(wanted)
            if wanted_text != _existing_text(found):
                operations.append(_patch_operation(doc_id, _block_id(found), wanted_text))
            continue
        if block_type != 31:
            continue
        wanted_shape = _table_shape(wanted)
        found_shape = _table_shape(found)
        if wanted_shape != found_shape:
            differences.append(
                f"table at block {index} shape differs: existing={found_shape}, desired={wanted_shape}"
            )
            continue
        cell_ids = _table_cell_ids(found)
        wanted_cells = wanted.get("_cells") or []
        if len(cell_ids) != len(wanted_cells):
            differences.append(
                f"table at block {index} cell count differs: "
                f"existing={len(cell_ids)}, desired={len(wanted_cells)}"
            )
            continue
        for cell_index, (cell_id, wanted_cell) in enumerate(zip(cell_ids, wanted_cells)):
            text_ids = _text_block_ids_for_cell(cell_id, by_id)
            if not text_ids:
                differences.append(
                    f"table at block {index} cell {cell_index} has no text block"
                )
                continue
            text_id = text_ids[0]
            wanted_text = wanted_cell["text"]
            if (
                wanted_text != _existing_text(by_id[text_id])
                or bool(wanted_cell["bold"]) != _existing_bold(by_id[text_id])
            ):
                cell_patch_requests.append(_batch_update_request(
                    text_id, wanted_text, bold=bool(wanted_cell["bold"]),
                ))
    if differences:
        return {"ok": False, "replace_all": False, "diff": differences, "operations": []}
    operations.extend(_batch_update_operations(doc_id, cell_patch_requests))
    return {"ok": True, "replace_all": False, "diff": [], "operations": operations}


class FeishuClient:
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.last_write = 0.0

    def request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        write: bool = False,
        raw: bool = False,
    ) -> Any:
        import requests  # type: ignore  # Lazy by design; unavailable in offline tests.

        headers = {"Authorization": f"Bearer {self.access_token}"}
        for attempt in range(5):
            if write:
                remaining = WRITE_DELAY - (time.monotonic() - self.last_write)
                if remaining > 0:
                    time.sleep(remaining)
            response = requests.request(
                method, url, headers=headers, json=json_body, params=params,
                data=data, files=files, timeout=60,
            )
            if write:
                self.last_write = time.monotonic()
            if response.status_code != 429 and response.status_code < 500:
                response.raise_for_status()
                if raw:
                    return response.content
                payload = response.json()
                if payload.get("code", 0) != 0:
                    raise RuntimeError(f"Feishu API error: {payload}")
                return payload
            if attempt == 4:
                response.raise_for_status()
            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if retry_after else min(8.0, 0.5 * (2 ** attempt))
            time.sleep(delay)
        raise AssertionError("unreachable")


def _tenant_token() -> str:
    import requests  # type: ignore  # Lazy by design.

    payload = {
        "app_id": os.environ["FEISHU_APP_ID"],
        "app_secret": os.environ["FEISHU_APP_SECRET"],
    }
    for attempt in range(5):
        response = requests.post(
            f"{BASE}/auth/v3/tenant_access_token/internal", json=payload, timeout=30,
        )
        if response.status_code != 429 and response.status_code < 500:
            response.raise_for_status()
            body = response.json()
            if body.get("code", 0) != 0:
                raise RuntimeError(f"Feishu auth error: {body}")
            return body["tenant_access_token"]
        if attempt == 4:
            response.raise_for_status()
        retry_after = response.headers.get("Retry-After")
        time.sleep(float(retry_after) if retry_after else min(8.0, 0.5 * (2 ** attempt)))
    raise AssertionError("unreachable")


def drive_dry_plan(file_token: str, html_path: str | os.PathLike[str]) -> dict[str, Any]:
    path = Path(html_path)
    size = path.stat().st_size
    return {
        "mode": "drive-overwrite",
        "operations": [
            {
                "method": "POST",
                "url": f"{BASE}/auth/v3/tenant_access_token/internal",
                "json": {
                    "app_id": "${FEISHU_APP_ID}",
                    "app_secret": "${FEISHU_APP_SECRET}",
                },
                "response_binding": "tenant_access_token",
            },
            {
                "method": "POST",
                "url": f"{BASE}/drive/v1/metas/batch_query",
                "json": {
                    "request_docs": [{"doc_token": file_token, "doc_type": "file"}]
                },
                "response_binding": "metadata",
            },
            {
                "method": "POST",
                "url": f"{BASE}/drive/v1/files/upload_all",
                "multipart": {
                    "fields": {
                        "file_name": "${metadata.title}",
                        "parent_type": "explorer",
                        "size": str(size),
                        "file_token": file_token,
                    },
                    "files": {
                        "file": {
                            "path": str(path),
                            "content_type": mimetypes.guess_type(path.name)[0] or "text/html",
                            "size": size,
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        }
                    },
                },
                "assert": {"response.data.file_token": file_token},
            },
            {
                "method": "GET",
                "url": f"{BASE}/drive/v1/files/{file_token}/download",
                "assert": {
                    "bytes_equal": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                },
            },
        ],
    }


def _metadata_title(payload: dict[str, Any]) -> str:
    data = payload.get("data") or {}
    candidates = data.get("metas") or data.get("docs") or data.get("items") or []
    if candidates:
        item = candidates[0]
        title = item.get("name") or item.get("title")
        if title:
            return str(title)
    raise RuntimeError(f"metadata response did not contain an existing file title: {payload}")


def publish_drive(file_token: str, html_path: str | os.PathLike[str]) -> None:
    if not file_token:
        raise ValueError("--file-token is mandatory; creating Drive files is forbidden")
    path = Path(html_path)
    content = path.read_bytes()
    client = FeishuClient(_tenant_token())
    metadata = client.request(
        "POST",
        f"{BASE}/drive/v1/metas/batch_query",
        json_body={"request_docs": [{"doc_token": file_token, "doc_type": "file"}]},
    )
    title = _metadata_title(metadata)
    with path.open("rb") as handle:
        uploaded = client.request(
            "POST",
            f"{BASE}/drive/v1/files/upload_all",
            data={
                "file_name": title,
                "parent_type": "explorer",
                "size": str(len(content)),
                "file_token": file_token,
            },
            files={
                "file": (
                    path.name, handle,
                    mimetypes.guess_type(path.name)[0] or "text/html",
                )
            },
            write=True,
        )
    returned = str((uploaded.get("data") or {}).get("file_token") or "")
    if returned != file_token:
        raise RuntimeError(
            f"refuse overwrite result: response file_token {returned!r} != {file_token!r}"
        )
    downloaded = client.request(
        "GET", f"{BASE}/drive/v1/files/{file_token}/download", raw=True,
    )
    if downloaded != content:
        raise RuntimeError("download verification failed: bytes differ from uploaded HTML")


def _created_doc_id(payload: dict[str, Any]) -> str:
    data = payload.get("data") or {}
    document = data.get("document") or {}
    value = document.get("document_id") or data.get("document_id")
    if not value:
        raise RuntimeError(f"create response did not contain document_id: {payload}")
    return str(value)


def _created_children(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") or {}
    children = data.get("children") or []
    return children if isinstance(children, list) else []


def _response_block(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") or {}
    block = data.get("block") or {}
    return block if isinstance(block, dict) else {}


def append_content(client: FeishuClient, doc_id: str, blocks: list[dict[str, Any]]) -> None:
    pending: list[dict[str, Any]] = []
    created_tables: list[tuple[list[str], list[dict[str, Any]]]] = []

    def flush() -> None:
        nonlocal pending
        for chunk in chunk_children(pending):
            client.request(
                "POST", _append_url(doc_id),
                json_body={"children": chunk}, write=True,
            )
        pending = []

    for block in blocks:
        if _block_type(block) != 31:
            pending.append(public_block(block))
            if len(pending) == 50:
                flush()
            continue
        flush()
        rows, columns = _table_shape(block)
        response = client.request(
            "POST", _append_url(doc_id),
            json_body={"children": [_table_create_block(block)]}, write=True,
        )
        created = _created_children(response)
        table = created[0] if created else {}
        table_id = _block_id(table)
        if not table_id:
            raise RuntimeError(f"table create response has no block_id: {response}")
        for _ in range(max(0, rows - MAX_TABLE_CREATE_ROWS)):
            client.request(
                "PATCH",
                _block_url(doc_id, table_id) + "?document_revision_id=-1",
                json_body={"insert_table_row": {"row_index": -1}},
                write=True,
            )
        table_payload = client.request("GET", _block_url(doc_id, table_id))
        cell_ids = _table_cell_ids(_response_block(table_payload))
        if len(cell_ids) != len(block["_cells"]):
            raise RuntimeError(
                f"created {rows}x{columns} table returned {len(cell_ids)} cells; "
                f"expected {len(block['_cells'])}"
            )
        created_tables.append((cell_ids, block["_cells"]))
    flush()
    if not created_tables:
        return
    existing = fetch_existing(client, doc_id)
    by_id = {
        _block_id(item): item for item in _items(existing) if _block_id(item)
    }
    requests: list[dict[str, Any]] = []
    for cell_ids, wanted_cells in created_tables:
        for cell_id, cell in zip(cell_ids, wanted_cells):
            if not cell["text"]:
                continue
            text_ids = _text_block_ids_for_cell(cell_id, by_id)
            if not text_ids:
                raise RuntimeError(
                    f"created table cell {cell_id!r} has no existing text child"
                )
            requests.append(_batch_update_request(
                text_ids[0], cell["text"], bold=bool(cell["bold"]),
            ))
    for operation in _batch_update_operations(doc_id, requests):
        client.request(
            operation["method"], operation["url"],
            json_body=operation["json"], write=True,
        )


def fetch_existing(client: FeishuClient, doc_id: str) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    page_token = ""
    while True:
        params: dict[str, Any] = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        payload = client.request(
            "GET", f"{BASE}/docx/v1/documents/{doc_id}/blocks", params=params,
        )
        data = payload.get("data") or {}
        items.extend(data.get("items") or [])
        if not data.get("has_more"):
            break
        page_token = str(data.get("page_token") or "")
        if not page_token:
            raise RuntimeError("blocks response has_more=true without page_token")
    return {"data": {"items": items}}


def execute_operations(client: FeishuClient, operations: list[dict[str, Any]]) -> None:
    for operation in operations:
        client.request(
            operation["method"], operation["url"],
            json_body=operation.get("json"), write=operation["method"] != "GET",
        )


def publish_docx(args: argparse.Namespace, report: dict[str, Any]) -> dict[str, Any]:
    if not args.doc_id:
        if args.dry:
            return new_doc_plan(report, args.title, args.folder)
        client = FeishuClient(os.environ["FEISHU_USER_ACCESS_TOKEN"])
        created = client.request(
            "POST", f"{BASE}/docx/v1/documents",
            json_body={
                "title": args.title or report["title"],
                "folder_token": args.folder or "",
            },
            write=True,
        )
        doc_id = _created_doc_id(created)
        append_content(client, doc_id, report["blocks"])
        return {"mode": "docx-create", "document_id": doc_id}

    if args.dry and not args.existing_blocks:
        return {
            "mode": "docx-update",
            "document_id": args.doc_id,
            "status": "existing blocks required to plan PATCH operations offline",
            "content_blocks": report["blocks"],
            "skipped": report["skipped"],
            "operations": [{
                "method": "GET",
                "url": f"{BASE}/docx/v1/documents/{args.doc_id}/blocks",
                "query": {"page_size": 500, "page_token": "${next_page_token}"},
            }],
        }

    if args.existing_blocks:
        existing = json.loads(Path(args.existing_blocks).read_text(encoding="utf-8"))
    else:
        client = FeishuClient(os.environ["FEISHU_USER_ACCESS_TOKEN"])
        existing = fetch_existing(client, args.doc_id)
    plan = plan_updates(
        args.doc_id, report["blocks"], existing, replace_all=args.replace_all,
    )
    result = {
        "mode": "docx-update",
        "document_id": args.doc_id,
        "content_blocks": report["blocks"],
        "skipped": report["skipped"],
        **plan,
    }
    if args.dry or not plan["ok"]:
        return result
    client = FeishuClient(os.environ["FEISHU_USER_ACCESS_TOKEN"])
    if args.replace_all:
        # Execute deletion first, then append dynamically so table cell IDs are real.
        delete_ops = [op for op in plan["operations"] if op["method"] == "DELETE"]
        execute_operations(client, delete_ops)
        append_content(client, args.doc_id, report["blocks"])
    else:
        execute_operations(client, plan["operations"])
    return result


def block_counts(blocks: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(_block_type(block)) for block in blocks)
    return dict(sorted(counts.items(), key=lambda item: int(item[0])))


def operation_counts(operations: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for operation in operations:
        method = operation.get("method", "")
        url = operation.get("url", "")
        body = operation.get("json") or {}
        if method == "POST" and url == f"{BASE}/docx/v1/documents":
            name = "create_document"
        elif method == "POST" and "/children?" in url:
            name = "append_children"
        elif method == "PATCH" and "insert_table_row" in body:
            name = "insert_table_row"
        elif method == "PATCH" and "/blocks/batch_update?" in url:
            name = "batch_update"
        elif method == "GET" and url.endswith("/blocks"):
            name = "list_blocks_paginated"
        elif method == "GET" and "/blocks/" in url:
            name = "get_table"
        elif method == "PATCH":
            name = "patch_block"
        elif method == "DELETE":
            name = "delete_children"
        else:
            name = method.lower() or "unknown"
        counts[name] += 1
    result = dict(sorted(counts.items()))
    result["total"] = len(operations)
    return result


def estimated_http_calls(
    blocks: list[dict[str, Any]], operations: list[dict[str, Any]],
) -> dict[str, int]:
    """Expand the one logical paginated listing into expected HTTP requests."""
    logical = operation_counts(operations)
    listings = logical.get("list_blocks_paginated", 0)
    if not listings:
        return {"list_blocks_pages": 0, "total": logical["total"]}
    cell_count = sum(
        len(block.get("_cells") or [])
        for block in blocks if _block_type(block) == 31
    )
    # Root + top-level blocks + one cell block and one text child per cell.
    expected_items = 1 + len(blocks) + 2 * cell_count
    pages = max(1, (expected_items + 499) // 500)
    return {
        "list_blocks_pages": pages,
        "total": logical["total"] - listings + pages * listings,
    }


def _write_or_print(payload: dict[str, Any], output: str | None = None) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if output:
        Path(output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    drive = commands.add_parser("drive", help="overwrite one existing Drive file in place")
    drive.add_argument("--file-token", required=True)
    drive.add_argument("--html", required=True)
    drive.add_argument("--dry", action="store_true")

    docx = commands.add_parser("docx", help="convert a rendered DOM to native Feishu docx blocks")
    docx.add_argument("--html", required=True, help="rendered DOM snapshot containing #sheet")
    docx.add_argument("--doc-id")
    docx.add_argument("--title")
    docx.add_argument("--folder", dest="folder")
    docx.add_argument("--dry", action="store_true")
    docx.add_argument("--out")
    docx.add_argument("--replace-all", action="store_true")
    docx.add_argument(
        "--existing-blocks",
        help="offline JSON returned by GET document blocks (required to plan dry updates)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "drive":
        if args.dry:
            _write_or_print(drive_dry_plan(args.file_token, args.html))
        else:
            publish_drive(args.file_token, args.html)
            print("Drive overwrite and byte verification succeeded.")
        return 0

    report = convert_html(args.html)
    result = publish_docx(args, report)
    result["summary"] = {
        "block_counts_by_type": block_counts(report["blocks"]),
        "tables": sum(_block_type(block) == 31 for block in report["blocks"]),
        "skipped": report["skipped"],
        "operation_counts": operation_counts(result.get("operations", [])),
        "estimated_http_calls": estimated_http_calls(
            report["blocks"], result.get("operations", []),
        ),
    }
    _write_or_print(result, args.out if args.dry else None)
    if result.get("ok") is False:
        print("Structure differs; no writes were made. Re-run with --replace-all to rebuild.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
