"""Metric connector: data/metrics/kpis.json -> one Doc per KPI row.

``text`` is the row's human-readable ``summary`` (the retrievable sentence). Metrics
are company-wide reference facts, so they carry the GLOBAL_GROUP (empty group_id).
"""

from __future__ import annotations

from .base import DATA_DIR, GLOBAL_GROUP, Doc, load_json


def load() -> list[Doc]:
    rows = load_json(DATA_DIR / "metrics" / "kpis.json")
    docs: list[Doc] = []
    for r in rows:
        docs.append(
            Doc(
                id=f"metric:{r['id']}",
                text=r["summary"],
                source="metric",
                group_id=GLOBAL_GROUP,
                timestamp=r.get("period"),
                url=r.get("source"),
                meta={
                    "metric_id": r["id"],
                    "metric": r.get("metric", ""),
                    "kind": r.get("type", ""),  # public | synthetic
                },
            )
        )
    return docs
