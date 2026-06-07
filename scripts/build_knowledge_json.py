#!/usr/bin/env python3
"""Generate agent-py/knowledge.json (the `knowledge` index seed) from parsed filings.

Reads data/parsed/ via the filings connector and writes the [{id,text,metadata}] shape
that agent-py/src/create_index.py ingests. Stamps group_id so the agent's group filter
(``group_id == DEFAULT_GROUP_ID``) matches — Coinbase filings live in the demo group.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from connectors import filings  # noqa: E402

GROUP_ID = os.getenv("DEFAULT_GROUP_ID", "acme-finance")
OUT = REPO / "agent-py" / "knowledge.json"


def main() -> None:
    docs = filings.load()
    entries = []
    for d in docs:
        md = d.to_metadata()
        md["group_id"] = GROUP_ID  # ensure the agent's group filter matches
        entries.append({"id": d.id, "text": d.text, "metadata": md})
    OUT.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    import collections
    by_form = collections.Counter(e["metadata"].get("form", "?") for e in entries)
    print(f"wrote {OUT.relative_to(REPO)} — {len(entries)} docs (group_id={GROUP_ID})")
    for form, n in sorted(by_form.items()):
        print(f"  {form:10s} {n} chunks")


if __name__ == "__main__":
    main()
