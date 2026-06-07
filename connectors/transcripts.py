"""Transcript connector: data/transcripts/*.json -> one Doc per turn."""

from __future__ import annotations

from .base import DATA_DIR, Doc, load_json


def load() -> list[Doc]:
    docs: list[Doc] = []
    for path in sorted((DATA_DIR / "transcripts").glob("*.json")):
        mtg = load_json(path)
        meeting_id = mtg["meeting_id"]
        group_id = mtg.get("group_id", "")
        date = mtg.get("date")
        title = mtg.get("title", "")
        for i, turn in enumerate(mtg.get("turns", [])):
            speaker = turn.get("speaker")
            text = turn.get("text", "")
            if not text:
                continue
            docs.append(
                Doc(
                    id=f"transcript:{meeting_id}:t{i}",
                    # Prefix the speaker so attribution survives into the embedded text.
                    text=f"{speaker}: {text}" if speaker else text,
                    source="transcript",
                    group_id=group_id,
                    user_id=speaker,
                    timestamp=date,
                    url=meeting_id,
                    meta={"meeting_id": meeting_id, "title": title, "turn": str(i)},
                )
            )
    return docs
