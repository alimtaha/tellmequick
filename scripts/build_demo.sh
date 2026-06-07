#!/usr/bin/env bash
# Build the investor-demo corpus from parsed filings.
#   default:  ingest/build_knowledge.py (filings_only) -> agent-py/corpus/knowledge.json
#             (LOCAL ONLY — does NOT touch Moss).
#   --push :  also run create_index.py to push the index to Moss (delete+recreate
#             'knowledge'; idempotent and respects the project index limit).
#
# Prereqs: data/parsed/ populated (run scripts/ingest_filings.py first).
# --push additionally needs MOSS_PROJECT_ID / MOSS_PROJECT_KEY in agent-py/.env.local.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-.venv/bin/python}"
PUSH="${1:-}"

echo "== building filings-only corpus (local) =="
MOSS_INDEX_LAYOUT=filings_only "$PY" -m ingest.build_knowledge

echo "== per-form chunk counts =="
"$PY" - <<'PY'
import json, collections, pathlib
c = collections.Counter()
for p in pathlib.Path("data/parsed").glob("*.json"):
    d = json.loads(p.read_text())
    c[d.get("form", p.stem)] += len(d.get("chunks", []))
for form, n in sorted(c.items()):
    print(f"  {form:10s} {n} chunks")
print(f"  TOTAL {sum(c.values())} chunks")
PY

echo "Corpus written to agent-py/corpus/knowledge.json"
if [ "$PUSH" = "--push" ]; then
  echo "== pushing to Moss (create_index) =="
  uv --directory agent-py run src/create_index.py
else
  echo "(local only — not pushed to Moss). To push: scripts/build_demo.sh --push"
  echo "Hand this file to whoever pushes the index: agent-py/corpus/knowledge.json"
fi
