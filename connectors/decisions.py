"""Decision connector: data/decisions/decision_log.json -> one Doc per decision."""

from __future__ import annotations

from .base import DATA_DIR, Doc, load_json


def load() -> list[Doc]:
    log = load_json(DATA_DIR / "decisions" / "decision_log.json")
    docs: list[Doc] = []
    for d in log:
        text = (
            f"Decision {d['id']}: {d['decision']} "
            f"(owner: {d['owner']}; {d.get('date', '')}). "
            f"Rationale: {d.get('rationale', '')}"
        )
        docs.append(
            Doc(
                id=f"decision:{d['id']}",
                text=text,
                source="decision",
                group_id=d.get("group_id", ""),
                user_id=d.get("owner"),
                timestamp=d.get("date"),
                url=d["id"],
                is_decision=True,
                meta={
                    "decision_id": d["id"],
                    "source_refs": d.get("source_refs", []),
                },
            )
        )
    return docs
