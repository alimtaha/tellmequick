"""Filings connector: Unsiloed-parsed filings -> Docs.

Reads the parse cache in ``data/parsed/`` (populated by ``scripts/ingest_filings.py``,
which calls Unsiloed) and emits one ``Doc`` per chunk. No network here — the build is
deterministic/offline once the cache exists.

Accepted cache shapes per ``data/parsed/*.json`` (format-flexible):
  - {"form","label","url","file_name","chunks": ["md", ...]}            (our writer)
  - {"chunks": [{"embed": "md"}|{"text": "md"}, ...]}                    (Unsiloed raw)
  - [ {"type","text","metadata":{page_number}}, ... ]                   (unstructured.io)
  - [ "md", ... ]                                                        (bare list)
``form``/``label`` fall back to the filename (``‹form›__‹label›.json``).
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import DATA_DIR, GLOBAL_GROUP, Doc

PARSED_DIR = DATA_DIR / "parsed"


def _chunk_texts(payload) -> list[str]:
    """Pull a list of markdown/text chunk strings out of any accepted shape."""
    if isinstance(payload, dict):
        items = payload.get("chunks", payload.get("elements", []))
    elif isinstance(payload, list):
        items = payload
    else:
        return []
    out: list[str] = []
    for it in items:
        if isinstance(it, str):
            t = it
        elif isinstance(it, dict):
            t = it.get("embed") or it.get("text") or it.get("markdown") or ""
        else:
            t = ""
        if t and t.strip():
            out.append(t.strip())
    return out


def _form_label(payload, path: Path) -> tuple[str, str]:
    form = label = None
    if isinstance(payload, dict):
        form = payload.get("form")
        label = payload.get("label")
    if not form or not label:
        # filename convention: ‹form›__‹label›.json (form may contain spaces->kept)
        stem = path.stem
        if "__" in stem:
            f, l = stem.split("__", 1)
            form = form or f
            label = label or l
        else:
            form = form or stem
            label = label or stem
    return form, label


def load() -> list[Doc]:
    if not PARSED_DIR.exists():
        print("filings.py: no data/parsed/ cache yet — run scripts/ingest_filings.py "
              "(uses Unsiloed) to populate it. Emitting 0 filing docs.")
        return []
    docs: list[Doc] = []
    for path in sorted(PARSED_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        form, label = _form_label(payload, path)
        url = payload.get("url") if isinstance(payload, dict) else None
        file_name = payload.get("file_name") if isinstance(payload, dict) else None
        chunks = _chunk_texts(payload)
        filing_id = f"{form}-{label}"
        for i, chunk in enumerate(chunks):
            docs.append(
                Doc(
                    id=f"filing:{filing_id}:c{i}",
                    text=chunk,
                    source="filing",
                    group_id=GLOBAL_GROUP,
                    url=url,
                    meta={
                        "form": form,
                        "label": label,
                        "filing_id": filing_id,
                        "chunk": str(i),
                        **({"file_name": file_name} if file_name else {}),
                    },
                )
            )
    if not docs:
        print("filings.py: data/parsed/ present but no chunks found — 0 filing docs.")
    return docs
