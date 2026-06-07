"""Docs connector: data/docs/*.md -> one Doc per markdown section.

These are born-as-text internal docs (policies, briefs, a contract extract), so they're
chunked locally by ``##`` heading — Unsiloed is reserved for messy PDFs (see filings.py).
The CloudVendor contract is *also* run through Unsiloed Extract in the build's verify step
to demo confidence-scored field extraction (connectors/filings.py::extract_contract_terms).
"""

from __future__ import annotations

from pathlib import Path

from .base import DATA_DIR, GLOBAL_GROUP, Doc


def _chunk_markdown(text: str) -> list[str]:
    """Split on level-2 (``## ``) headings; keep each heading with its body."""
    chunks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("## ") and current:
            chunks.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        chunks.append("\n".join(current).strip())
    return [c for c in chunks if c]


def load() -> list[Doc]:
    docs: list[Doc] = []
    for path in sorted((DATA_DIR / "docs").glob("*.md")):
        stem = path.stem
        text = path.read_text(encoding="utf-8")
        for i, chunk in enumerate(_chunk_markdown(text)):
            docs.append(
                Doc(
                    id=f"doc:{stem}:s{i}",
                    text=chunk,
                    source="doc",
                    group_id=GLOBAL_GROUP,
                    url=f"data/docs/{path.name}",
                    meta={"doc": stem, "section": str(i)},
                )
            )
    return docs


def _self_check() -> None:
    assert _chunk_markdown("# T\nintro\n## A\na1\n## B\nb1") == [
        "# T\nintro",
        "## A\na1",
        "## B\nb1",
    ], "markdown chunker regressed"
    print(f"docs.py: {len(load())} chunk(s) — chunker self-check OK")


if __name__ == "__main__":
    _self_check()
