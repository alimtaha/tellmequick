"""Unit tests for the agent's interaction gate, Moss-backed tools, and distillation.

Deterministic unit tests that exercise the methods and pure helpers directly. They
stub `MossClient` via monkeypatch so they run with no Moss credentials and no
network access — live behavior is validated separately.
"""

import json

import pytest
from livekit.agents import StopResponse

import agent as agent_module
from agent import (
    Assistant,
    Decision,
    build_meeting_docs,
    is_addressed,
    resolve_decisions,
)

GROUP_ID = "acme-finance"
THRESHOLD = agent_module.AMBIENT_SCORE_THRESHOLD


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


class _FakeMessage:
    """Stand-in for a ChatMessage with `.text_content`."""

    def __init__(self, text: str) -> None:
        self.text_content = text


class _FakeTurnCtx:
    """Stand-in for ChatContext; records add_message calls."""

    def __init__(self) -> None:
        self.added: list[dict] = []

    def add_message(self, role, content):
        self.added.append({"role": role, "content": content})


@pytest.fixture
def stub_moss(monkeypatch):
    """Replace the agent's `MossClient` with the recording fake."""
    monkeypatch.setattr(agent_module, "MossClient", _FakeMossClient)


def _published_types(room):
    return [
        json.loads(p.decode("utf-8"))["type"]
        for p, _ in room.local_participant.published
    ]


def _decoded(published):
    payload_bytes, _reliable = published[-1]
    return json.loads(payload_bytes.decode("utf-8"))


# ---- is_addressed (wake-name detection) ---------------------------------------


def test_is_addressed_matches_name_variants() -> None:
    assert is_addressed("Tellmequick, what did we decide?")
    assert is_addressed("hey tell me quick, pull up the contract")
    assert is_addressed("TELLMEQUICK")


def test_is_addressed_false_for_normal_talk() -> None:
    assert not is_addressed("Let's cut the events budget by twenty percent.")
    assert not is_addressed("")


# ---- on_user_turn_completed: the display-first gate ----------------------------


async def test_ambient_turn_surfaces_synthesized_card_and_stops(stub_moss) -> None:
    """A non-addressed strong match surfaces a SYNTHESIZED card (the LLM result, not
    the raw chunks) and aborts the spoken reply."""
    room = _FakeRoom()
    assistant = Assistant(room=room, group_id=GROUP_ID)
    assistant._moss.query_result = _FakeSearchResult(
        [_FakeDoc("Hold events flat.", doc_id="meet:1", score=THRESHOLD + 0.5)]
    )

    async def _fake_synth(utterance, docs):
        return "The team decided to hold the events budget flat (May review)."

    assistant._synthesize = _fake_synth

    with pytest.raises(StopResponse):
        await assistant.on_user_turn_completed(
            _FakeTurnCtx(), _FakeMessage("what about the events budget")
        )

    payload = _decoded(room.local_participant.published)
    assert payload["type"] == "moss_context"
    # The headline is the synthesized result; raw docs ride along as citations.
    assert payload["data"]["answer"].startswith("The team decided")
    assert payload["data"]["matches"][0]["text"] == "Hold events flat."
    assert assistant._moss.add_docs_calls == []


async def test_ambient_synthesis_none_suppresses_card(stub_moss) -> None:
    """Even on a high-score match, if synthesis judges nothing relevant (NONE),
    no card is shown — a second precision gate beyond the score threshold."""
    room = _FakeRoom()
    assistant = Assistant(room=room, group_id=GROUP_ID)
    assistant._moss.query_result = _FakeSearchResult(
        [_FakeDoc("tangential", doc_id="x", score=THRESHOLD + 0.5)]
    )

    async def _none(utterance, docs):
        return "NONE"

    assistant._synthesize = _none

    with pytest.raises(StopResponse):
        await assistant.on_user_turn_completed(_FakeTurnCtx(), _FakeMessage("hmm"))

    assert room.local_participant.published == []


async def test_ambient_turn_below_threshold_no_card(stub_moss) -> None:
    """A weak match surfaces nothing — display stays quiet."""
    room = _FakeRoom()
    assistant = Assistant(room=room, group_id=GROUP_ID)
    assistant._moss.query_result = _FakeSearchResult(
        [_FakeDoc("loosely related", doc_id="x", score=max(THRESHOLD - 0.2, 0.0))]
    )

    with pytest.raises(StopResponse):
        await assistant.on_user_turn_completed(
            _FakeTurnCtx(), _FakeMessage("small talk")
        )

    assert room.local_participant.published == []


async def test_addressed_turn_speaks_and_injects_screen_context(stub_moss) -> None:
    """An addressed turn does NOT abort the reply, and injects what's on screen."""
    assistant = Assistant(room=_FakeRoom(), group_id=GROUP_ID)
    assistant._wm.recent_context = ["Hold events flat (decided in May review)."]

    turn_ctx = _FakeTurnCtx()
    # Should NOT raise StopResponse.
    await assistant.on_user_turn_completed(
        turn_ctx, _FakeMessage("tellmequick, can you explain that?")
    )

    assert len(turn_ctx.added) == 1
    assert "Hold events flat" in turn_ctx.added[0]["content"]


# ---- search_context (only reachable when addressed) ---------------------------


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

    names, _query, options = assistant._moss.multi_query_calls[0]
    assert names == [
        agent_module.KNOWLEDGE_INDEX,
        agent_module.SLACK_INDEX,
        agent_module.MEETINGS_INDEX,
    ]
    assert options.top_k == 6
    assert options.filter == {"field": "group_id", "condition": {"$eq": GROUP_ID}}

    payload = _decoded(room.local_participant.published)
    assert payload["type"] == "moss_context"
    assert set(payload["data"]) == {"query", "matches", "time_taken_ms", "timestamp"}
    assert payload["data"]["matches"][0]["score"] == 0.91


async def test_search_context_is_read_only(stub_moss) -> None:
    assistant = Assistant(room=_FakeRoom(), group_id=GROUP_ID)
    assistant._moss.query_result = _FakeSearchResult([_FakeDoc("x", doc_id="d1")])
    await assistant.search_context(None, "anything")
    assert assistant._moss.add_docs_calls == []


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

    assert len(assistant._wm.pending_decisions) == 1
    d = assistant._wm.pending_decisions[0]
    assert d.text == "Cut the events budget 20%."
    assert d.topic == "events-budget"
    assert assistant._moss.add_docs_calls == []

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
    assert len(resolved) == 2


def test_resolve_decisions_keeps_topicless() -> None:
    assert len(resolve_decisions([Decision("note A"), Decision("note B")])) == 2


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
    assert agent_module.MEETINGS_INDEX in assistant._moss.load_index_calls


async def test_finalize_meeting_no_decisions_is_noop(stub_moss) -> None:
    assistant = Assistant(group_id=GROUP_ID, conversation_id="conv-empty")
    await assistant.finalize_meeting()
    assert assistant._moss.add_docs_calls == []
