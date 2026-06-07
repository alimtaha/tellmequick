"""Shared types + helpers for the source connectors.

Every connector emits the same normalized ``Doc`` shape (the PRD's "one normalized
document" abstraction). The ingest step (``ingest/build_knowledge.py``) flattens all
connector output and routes each Doc to a Moss index by its ``source`` field.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Repo root is the parent of the connectors/ package.
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

# Slack export file (stem) -> group thread. Keeps group scoping out of the raw
# Slack JSON so the export shape stays faithful to a real Slack export.
GROUP_BY_SLACK_FILE = {
    "finance-strategy": "coinbase-finance-weekly",
    "product-strategy": "coinbase-product-weekly",
    "analytics": "coinbase-analytics",
}

# Metrics and reference docs are company-wide, not scoped to one meeting thread.
GLOBAL_GROUP = ""


@dataclass
class Doc:
    """The normalized document shape shared by every source."""

    id: str
    text: str
    source: str  # slack | transcript | decision | metric | summary | doc | filing
    group_id: str = ""
    user_id: str | None = None
    timestamp: str | None = None
    url: str | None = None
    is_decision: bool = False
    meta: dict = field(default_factory=dict)

    def to_metadata(self) -> dict[str, str]:
        """Flatten to Moss metadata (all values must be strings).

        ``text`` and ``id`` are kept separate (they map to DocumentInfo.text/id);
        everything else — including the source-specific ``meta`` — lands here so it
        is available for filtering and citation.
        """
        md: dict[str, str] = {
            "source": self.source,
            "group_id": self.group_id or "",
            "is_decision": "true" if self.is_decision else "false",
        }
        if self.user_id is not None:
            md["user_id"] = self.user_id
        if self.timestamp is not None:
            md["timestamp"] = self.timestamp
        if self.url is not None:
            md["url"] = self.url
        for k, v in self.meta.items():
            md[str(k)] = v if isinstance(v, str) else json.dumps(v)
        return md


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def iso_from_slack_ts(ts: str) -> str:
    """Slack ts ('1729080000.000200') -> ISO-8601 UTC timestamp."""
    seconds = float(ts)
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
