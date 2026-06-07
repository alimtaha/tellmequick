"""Build the three Moss indexes used by tellmequick.

* ``knowledge`` — filings / documents (seed: ``knowledge.json``)
* ``slack``     — Slack messages       (seed: ``slack.json``)
* ``meetings``  — distilled notes + decisions from past meetings (seed: ``meetings.json``)

All three are read-only during a live meeting; ``meetings`` is additionally
written post-meeting by the agent's distillation pass (see ``agent.py``).

Run from the repo root via ``pnpm moss:index`` (which invokes
``uv --directory agent-py run src/create_index.py``) once Moss credentials are set.
Requires ``MOSS_PROJECT_ID`` / ``MOSS_PROJECT_KEY`` in ``agent-py/.env.local``.

Idempotent: an existing index of the same name is deleted and rebuilt, so
re-running with refreshed seed data is safe. The Moss tier caps this account at
three indexes, which is exactly what this script creates.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from moss import DocumentInfo, MossClient

# Resolve paths relative to this file: src/create_index.py -> parent.parent == agent-py/.
AGENT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = AGENT_DIR / ".env.local"
load_dotenv(ENV_PATH)

DEFAULT_MODEL_ID = "moss-minilm"
DEFAULT_GROUP_ID = os.getenv("DEFAULT_GROUP_ID", "acme-finance")

# (env var, default index name, seed filename, default source label)
INDEXES = [
    ("MOSS_KNOWLEDGE_INDEX", "knowledge", "knowledge.json", "doc"),
    ("MOSS_SLACK_INDEX", "slack", "slack.json", "slack"),
    ("MOSS_MEETINGS_INDEX", "meetings", "meetings.json", "meeting"),
]


def _coerce_docs(raw: list, default_source: str) -> list[DocumentInfo]:
    """Turn raw JSON entries into Moss DocumentInfo with string-only metadata.

    Every doc gets a ``source`` and a ``group_id`` (defaulted) so the agent's
    ``group_id`` retrieval filter matches uniformly across all sources.
    """
    docs: list[DocumentInfo] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        doc_id = entry.get("id")
        text = entry.get("text")
        if not doc_id or not text:
            continue
        metadata = entry.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        metadata.setdefault("source", default_source)
        metadata.setdefault("group_id", DEFAULT_GROUP_ID)
        # Moss metadata values must be strings.
        metadata = {str(k): str(v) for k, v in metadata.items()}
        docs.append(DocumentInfo(id=str(doc_id), text=str(text), metadata=metadata))
    return docs


def _load_seed(filename: str, default_source: str) -> list[DocumentInfo]:
    path = AGENT_DIR / filename
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, list):
        raise ValueError(f"{filename} must be a JSON list of document entries.")
    return _coerce_docs(raw, default_source)


def _placeholder(index_name: str) -> list[DocumentInfo]:
    """Moss needs >=1 doc to create an index. Seed an empty one that the agent's
    ``group_id`` filter excludes (it carries ``group_id="__seed__"``)."""
    return [
        DocumentInfo(
            id=f"__seed__:{index_name}",
            text=f"(seed) placeholder so the {index_name} index can be created before real data lands.",
            metadata={"source": "__seed__", "group_id": "__seed__"},
        )
    ]


async def build_indexes() -> None:
    project_id = os.getenv("MOSS_PROJECT_ID")
    project_key = os.getenv("MOSS_PROJECT_KEY")
    model_id = os.getenv("MOSS_MODEL_ID", DEFAULT_MODEL_ID)

    if not project_id or not project_key:
        raise OSError(
            "Missing MOSS_PROJECT_ID / MOSS_PROJECT_KEY. "
            f"Set them in {ENV_PATH} before running this script."
        )

    client = MossClient(project_id, project_key)

    for env_var, default_name, seed_file, source_label in INDEXES:
        name = os.getenv(env_var, default_name)
        docs = _load_seed(seed_file, source_label)
        if not docs:
            docs = _placeholder(name)
            print(f"[{name}] no docs in {seed_file}; creating with a placeholder.")

        # Idempotent rebuild: drop any existing index of the same name first.
        try:
            await client.delete_index(name)
            print(f"[{name}] deleted existing index.")
        except Exception:
            pass  # index didn't exist — fine.

        print(f"[{name}] creating with {len(docs)} doc(s) using model '{model_id}'...")
        result = await client.create_index(name, docs, model_id)
        print(f"[{name}] done (job: {result.job_id}, docs: {result.doc_count}).")

    print("All three Moss indexes built: knowledge, slack, meetings.")


if __name__ == "__main__":
    asyncio.run(build_indexes())
