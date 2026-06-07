"""Slack connector: data/slack/*.json (+ users.json) -> one Doc per message."""

from __future__ import annotations

from .base import DATA_DIR, GROUP_BY_SLACK_FILE, Doc, iso_from_slack_ts, load_json


def load() -> list[Doc]:
    slack_dir = DATA_DIR / "slack"
    users = load_json(slack_dir / "users.json")

    docs: list[Doc] = []
    for path in sorted(slack_dir.glob("*.json")):
        if path.name == "users.json":
            continue
        stem = path.stem
        group_id = GROUP_BY_SLACK_FILE.get(stem, "")
        for msg in load_json(path):
            if msg.get("type") != "message" or not msg.get("text"):
                continue
            uid = msg.get("user")
            handle = users.get(uid, {}).get("name", uid) if uid else None
            meta = {"channel": stem}
            if msg.get("thread_ts"):
                meta["thread_ts"] = msg["thread_ts"]
            docs.append(
                Doc(
                    id=f"slack:{stem}:{msg['ts']}",
                    text=msg["text"],
                    source="slack",
                    group_id=group_id,
                    user_id=handle,
                    timestamp=iso_from_slack_ts(msg["ts"]),
                    url=msg.get("permalink"),
                    meta=meta,
                )
            )
    return docs
