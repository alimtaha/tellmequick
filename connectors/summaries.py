"""Summary connector: data/summaries/*.json -> one Doc per meeting summary.

These distilled "what was decided / who owns what" summaries are often the best single
hit for a 'what did we decide about X' question, and feed the ``summaries`` index.
"""

from __future__ import annotations

from .base import DATA_DIR, Doc, load_json


def load() -> list[Doc]:
    docs: list[Doc] = []
    for path in sorted((DATA_DIR / "summaries").glob("*.json")):
        s = load_json(path)
        parts = [f"{s['title']} ({s.get('date', '')}). {s['summary']}"]
        if s.get("decisions"):
            parts.append("Decisions: " + ", ".join(s["decisions"]) + ".")
        if s.get("commitments"):
            parts.append("Commitments: " + " ".join(s["commitments"]))
        docs.append(
            Doc(
                id=f"summary:{s['meeting_id']}",
                text=" ".join(parts),
                source="summary",
                group_id=s.get("group_id", ""),
                timestamp=s.get("date"),
                url=s["meeting_id"],
                meta={
                    "meeting_id": s["meeting_id"],
                    "title": s.get("title", ""),
                    "decisions": s.get("decisions", []),
                    "attendees": s.get("attendees", []),
                },
            )
        )
    return docs
