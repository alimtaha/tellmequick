"""Source connectors -> the normalized Doc shape.

``load_all()`` returns every Doc across all sources; the ingest step routes them to Moss
indexes by ``source``. Adding a source = adding a connector module with a ``load()``.
"""

from __future__ import annotations

from . import decisions, docs, filings, metrics, slack, summaries, transcripts
from .base import Doc

# Order is stable so generated corpus files are diff-friendly.
_CONNECTORS = {
    "slack": slack.load,
    "transcript": transcripts.load,
    "decision": decisions.load,
    "metric": metrics.load,
    "summary": summaries.load,
    "doc": docs.load,
    "filing": filings.load,
}


def load_all(*, verbose: bool = True) -> list[Doc]:
    all_docs: list[Doc] = []
    for name, fn in _CONNECTORS.items():
        these = fn()
        all_docs.extend(these)
        if verbose:
            print(f"  {name:11s} -> {len(these):4d} doc(s)")
    if verbose:
        print(f"  {'TOTAL':11s} -> {len(all_docs):4d} doc(s)")
    return all_docs


__all__ = ["Doc", "load_all"]
