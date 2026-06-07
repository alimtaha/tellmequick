"""Unit tests for the agent's Moss-backed tools and the post-meeting distillation.

Deterministic unit tests that exercise the tool methods and pure helpers directly.
They stub `MossClient` via monkeypatch so they run with no Moss credentials and no
network access — live behavior is validated separately.
"""

import json

import pytest

import agent as agent_module
from agent import (
    Assistant,
    Decision,
    build_meeting_docs,
    resolve_decisions,
)

GROUP_ID = "acme-finance"


class _FakeDoc:
    """Stand-in for a Moss query-result document (`.id/.text/.score/.metadata`)."""

    def __init__(self, text, doc_id=None, score=None, metadata=None) -> None:
        self.id = doc_id
        self.text = text
        self.score = score
        self.metadata = metadata


class _FakeSearchResult:
    """Stand-in for a Moss `SearchResult` (`.docs/.time_taken_ms`)."""

    def __init__(self, docs, time_taken_ms: float = 12.5) -> None:
        self.docs = docs
        self.time_taken_ms = time_taken_ms


class _FakeMossClient:
    """Records calls instead of contacting Moss. Substituted for `MossClient`."""

    def __init__(self, *args, **kwargs) -> None:
        self.load_indexes_calls: list = []
        self.load_index_calls: list[str] = []
        self.multi_query_calls: list[tuple] = []
        self.add_docs_calls: list[tuple] = []
        self.query_result = _FakeSearchResult([])

    async def load_indexes(self, names, *args, **kwargs):
        self.load_indexes_calls.append(names)

    async def load_index(self, name, *args, **kwargs):
        self.load_index_calls.append(name)

    async def query_multi_index(self, names, query, options=None):
        self.multi_query_calls.append((names, query, options))
        return self.query_result

    async def add_docs(self, index, docs, options=None):
        self.add_docs_calls.append((index, docs, options))
        return None


class _FakePublisher:
    def __init__(self) -> None:
        self.published: list[tuple] = []

    async def publish_data(self, payload, reliable=None):
        self.published.append((payload, reliable))


class _FakeRoom:
    def __init__(self) -> None:
        self.local_participant = _FakePublisher()


@pytest.fixture
def stub_moss(monkeypatch):
    """Replace the agent's `MossClient` with the recording fake."""
    monkeypatch.setattr(agent_module, "MossClient", _FakeMossClient)


def _decoded(published):
    """Decode the most recent published data-channel payload."""
    payload_bytes, _reliable = published[-1]
    return json.loads(payload_bytes.decode("utf-8"))


# ---- search_context -----------------------------------------------------------


async def test_search_context_queries_all_indexes_and_publishes(stub_moss) -> None:
    room = _FakeRoom()
    assistant = Assistant(room=room, group_id=GROUP_ID)
    assistant._moss.query_result = _FakeSearchResult(
        [
            _FakeDoc(
                "Events drove 40% of pipeline.",
                doc_id="slack:1",
                score=0.91,
                metadata={"source": "slack", "url": "https://s/1"},
            ),
            _FakeDoc("Hold events flat.", doc_id="meet:1", score=0.84),
        ],
        time_taken_ms=8.0,
    )

    result = await assistant.search_context(
        None, "what did we say about events budget?"
    )

    assert result == "Events drove 40% of pipeline.\n\nHold events flat."

    # One multi-index query across all three indexes, group_id-scoped.
    assert len(assistant._moss.multi_query_calls) == 1
    names, query, options = assistant._moss.multi_query_calls[0]
    assert names == [
        agent_module.KNOWLEDGE_INDEX,
        agent_module.SLACK_INDEX,
        agent_module.MEETINGS_INDEX,
    ]
    assert query == "what did we say about events budget?"
    assert options.top_k == 6
    assert options.filter == {"field": "group_id", "condition": {"$eq": GROUP_ID}}

    # Published a well-formed moss_context message.
    payload = _decoded(room.local_participant.published)
    assert payload["type"] == "moss_context"
    data = payload["data"]
    assert set(data) == {"query", "matches", "time_taken_ms", "timestamp"}
    assert data["time_taken_ms"] == 8.0
    assert isinstance(data["timestamp"], (int, float))
    assert data["matches"][0]["text"] == "Events drove 40% of pipeline."
    assert data["matches"][0]["score"] == 0.91
    assert data["matches"][0]["metadata"] == {"source": "slack", "url": "https://s/1"}


async def test_search_context_is_read_only(stub_moss) -> None:
    """The hot path never writes to Moss."""
    assistant = Assistant(room=_FakeRoom(), group_id=GROUP_ID)
    assistant._moss.query_result = _FakeSearchResult([_FakeDoc("x", doc_id="d1")])
    await assistant.search_context(None, "anything")
    assert assistant._moss.add_docs_calls == []


async def test_search_context_dedups_already_surfaced(stub_moss) -> None:
    """A doc surfaced once this meeting isn't surfaced again."""
    assistant = Assistant(room=_FakeRoom(), group_id=GROUP_ID)
    assistant._moss.query_result = _FakeSearchResult(
        [_FakeDoc("Hold events flat.", doc_id="meet:1")]
    )

    first = await assistant.search_context(None, "events budget?")
    assert first == "Hold events flat."

    second = await assistant.search_context(None, "events budget again?")
    assert second == "No relevant context found."


async def test_search_context_empty_returns_message(stub_moss) -> None:
    assistant = Assistant(room=_FakeRoom(), group_id=GROUP_ID)
    assistant._moss.query_result = _FakeSearchResult([])
    assert (
        await assistant.search_context(None, "nothing here")
        == "No relevant context found."
    )


# ---- mark_decision ------------------------------------------------------------


async def test_mark_decision_records_to_working_memory_no_moss_write(stub_moss) -> None:
    room = _FakeRoom()
    assistant = Assistant(room=room, group_id=GROUP_ID)

    msg = await assistant.mark_decision(
        None, "Cut the events budget 20%.", topic="events-budget", owner="dan"
    )
    assert isinstance(msg, str) and msg

    # Captured in working memory, not Moss.
    assert len(assistant._wm.pending_decisions) == 1
    d = assistant._wm.pending_decisions[0]
    assert d.text == "Cut the events budget 20%."
    assert d.topic == "events-budget"
    assert d.owner == "dan"
    assert assistant._moss.add_docs_calls == []

    # Published a decision_pending banner.
    payload = _decoded(room.local_participant.published)
    assert payload["type"] == "decision_pending"
    assert payload["data"]["text"] == "Cut the events budget 20%."


# ---- pure helpers -------------------------------------------------------------


def test_resolve_decisions_latest_wins_per_topic() -> None:
    pending = [
        Decision("Hold events flat.", topic="events-budget"),
        Decision("Hire two AEs.", topic="hiring"),
        Decision("Actually cut events 20%.", topic="events-budget"),  # reversal
    ]
    resolved = resolve_decisions(pending)
    texts = [d.text for d in resolved]
    assert "Actually cut events 20%." in texts
    assert "Hold events flat." not in texts  # superseded
    assert "Hire two AEs." in texts
    # One per topic.
    assert len(resolved) == 2


def test_resolve_decisions_keeps_topicless() -> None:
    pending = [Decision("note A"), Decision("note B")]
    assert len(resolve_decisions(pending)) == 2


def test_build_meeting_docs_emits_string_metadata() -> None:
    docs = build_meeting_docs(
        GROUP_ID,
        "conv-1",
        [
            Decision(
                "Cut events 20%.",
                topic="events-budget",
                owner="dan",
                ts="2026-06-06T00:00:00Z",
            )
        ],
    )
    assert len(docs) == 1
    doc = docs[0]
    assert doc.id == f"{GROUP_ID}:conv-1:decision:0"
    assert doc.text == "Cut events 20%."
    assert doc.metadata["is_decision"] == "true"
    assert doc.metadata["kind"] == "decision"
    assert doc.metadata["group_id"] == GROUP_ID
    assert doc.metadata["conversation_id"] == "conv-1"
    # All metadata values must be strings (Moss constraint).
    assert all(isinstance(v, str) for v in doc.metadata.values())


# ---- finalize_meeting (post-meeting distillation) -----------------------------


async def test_finalize_meeting_writes_resolved_decisions(stub_moss) -> None:
    assistant = Assistant(group_id=GROUP_ID, conversation_id="conv-42")
    assistant._wm.pending_decisions = [
        Decision("Hold events flat.", topic="events-budget", ts="t1"),
        Decision("Cut events 20%.", topic="events-budget", ts="t2"),  # latest wins
    ]

    await assistant.finalize_meeting()

    assert len(assistant._moss.add_docs_calls) == 1
    index, docs, _opts = assistant._moss.add_docs_calls[0]
    assert index == agent_module.MEETINGS_INDEX
    assert len(docs) == 1  # conflict resolved to one
    assert docs[0].text == "Cut events 20%."
    # Index reloaded so the new decision is queryable next meeting.
    assert agent_module.MEETINGS_INDEX in assistant._moss.load_index_calls


async def test_finalize_meeting_no_decisions_is_noop(stub_moss) -> None:
    assistant = Assistant(group_id=GROUP_ID, conversation_id="conv-empty")
    await assistant.finalize_meeting()
    assert assistant._moss.add_docs_calls == []
