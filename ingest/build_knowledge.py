"""Build per-index Moss corpus files from the connectors.

Flattens every connector Doc, routes it to a target index via ``SOURCE_TO_INDEX``, and
writes one ``agent-py/corpus/<index>.json`` per index as ``[{id, text, metadata}]`` (the
shape ``create_index.py`` ingests). Metadata values are stringified there via Doc.to_metadata.

Index layout is a single switch so the architecture swap is cheap (see
memory: moss-index-architecture). Default "single" ships everything into one ``knowledge``
index so the demo works today; "partitioned" is the 4-index target.

    python -m ingest.build_knowledge                 # single index
    MOSS_INDEX_LAYOUT=partitioned python -m ingest.build_knowledge
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from connectors import load_all
from connectors.base import REPO_ROOT

CORPUS_DIR = REPO_ROOT / "agent-py" / "corpus"

# Target index per source. Flip MOSS_INDEX_LAYOUT to switch; routing is the only change.
LAYOUTS = {
    "single": {
        "slack": "knowledge",
        "transcript": "knowledge",
        "decision": "knowledge",
        "metric": "knowledge",
        "summary": "knowledge",
        "doc": "knowledge",
        "filing": "knowledge",
    },
    "partitioned": {
        "filing": "knowledge",
        "doc": "knowledge",
        "metric": "knowledge",
        "slack": "slack",
        "transcript": "slack",
        "summary": "summaries",
        "decision": "summaries",
    },
    # Investor demo: only the public SEC filings go into the knowledge index.
    "filings_only": {
        "filing": "knowledge",
    },
}


def build() -> dict[str, int]:
    layout_name = os.getenv("MOSS_INDEX_LAYOUT", "single")
    source_to_index = LAYOUTS[layout_name]
    print(f"Building corpus with layout '{layout_name}'...")

    docs = load_all()
    by_index: dict[str, list[dict]] = {}
    for d in docs:
        index = source_to_index.get(d.source)
        if index is None:
            continue
        by_index.setdefault(index, []).append(
            {"id": d.id, "text": d.text, "metadata": d.to_metadata()}
        )

    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    # Clear stale corpus files from a previous layout so indexes don't drift.
    for stale in CORPUS_DIR.glob("*.json"):
        stale.unlink()

    counts: dict[str, int] = {}
    for index, entries in sorted(by_index.items()):
        out = CORPUS_DIR / f"{index}.json"
        out.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        counts[index] = len(entries)
        print(f"  wrote {out.relative_to(REPO_ROOT)} ({len(entries)} docs)")
    return counts


if __name__ == "__main__":
    build()
