"""
routers/docs.py — /api/docs/* REST endpoints.

Serves markdown documentation files from the docs/ directory for
the frontend Documentation page. Supports file listing and content retrieval.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/docs", tags=["docs"])

# Resolve docs root — on board: /opt/ortho-bender/docs, dev: project docs/
_DOCS_ROOT = Path(os.environ.get("OB_DOCS_DIR", "/opt/ortho-bender/docs"))


def _build_tree(root: Path, prefix: str = "") -> list[dict]:
    """Recursively build a file tree of .md files."""
    entries: list[dict] = []
    if not root.is_dir():
        return entries

    for item in sorted(root.iterdir()):
        rel = f"{prefix}/{item.name}" if prefix else item.name
        if item.name.startswith(".") or item.name == "superpowers":
            continue
        if item.is_dir():
            children = _build_tree(item, rel)
            if children:
                entries.append({
                    "type": "dir",
                    "name": item.name,
                    "path": rel,
                    "children": children,
                })
        elif item.suffix == ".md":
            entries.append({
                "type": "file",
                "name": item.name,
                "path": rel,
                "size": item.stat().st_size,
            })
    return entries


@router.get("/tree")
async def docs_tree():
    """Return the documentation file tree."""
    if not _DOCS_ROOT.is_dir():
        return {"success": True, "data": []}
    return {"success": True, "data": _build_tree(_DOCS_ROOT)}


@router.get("/file/{file_path:path}")
async def docs_file(file_path: str):
    """Return the content of a markdown file."""
    target = (_DOCS_ROOT / file_path).resolve()

    # Path traversal protection
    if not str(target).startswith(str(_DOCS_ROOT.resolve())):
        raise HTTPException(status_code=403, detail="Path traversal denied")

    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    content = target.read_text(encoding="utf-8", errors="replace")
    return {
        "success": True,
        "data": {
            "path": file_path,
            "content": content,
            "size": target.stat().st_size,
        },
    }


@router.get("/download/{file_path:path}")
async def docs_download(file_path: str):
    """Download a documentation file."""
    target = (_DOCS_ROOT / file_path).resolve()

    if not str(target).startswith(str(_DOCS_ROOT.resolve())):
        raise HTTPException(status_code=403, detail="Path traversal denied")

    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    return FileResponse(
        path=str(target),
        filename=target.name,
        media_type="text/markdown",
    )
