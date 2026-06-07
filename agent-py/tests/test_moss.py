"""Unit tests for the agent's interjection gate, Moss-backed tools, and distillation.

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
THRESHOLD = agent_module.INTERJECT_THRESHOLD


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


def _decoded(published):
    payload_bytes, _reliable = published[-1]
    return json.loads(payload_bytes.decode("utf-8"))


def _joined_injections(turn_ctx):
    return " ".join(m["content"] for m in turn_ctx.added)


# ---- is_addressed (wake-name detection) ---------------------------------------


def test_is_addressed_matches_name_variants() -> None:
    assert is_addressed("Tellmequick, what did we decide?")
    assert is_addressed("hey tell me quick, pull up the contract")
    assert is_addressed("TELLMEQUICK")


def test_is_addressed_false_for_normal_talk() -> None:
    assert not is_addressed("Let's cut the events budget by twenty percent.")
    assert not is_addressed("")


# ---- on_user_turn_completed: the interjection gate ----------------------------


async def test_proactive_strong_match_commits(stub_moss) -> None:
    """A strong, fresh match does NOT abort the reply — it injects the context and
    lets the pipeline LLM generate the grounded reply. Sources are buffered."""
    assistant = Assistant(room=_FakeRoom(), group_id=GROUP_ID)
    assistant._moss.query_result = _FakeSearchResult(
        [
            _FakeDoc(
                "Hold events flat.",
                doc_id="meet:1",
                score=THRESHOLD + 0.2,
                metadata={"source": "meeting"},
            )
        ]
    )

    turn_ctx = _FakeTurnCtx()
    # Must not raise StopResponse — the agent commits to speaking.
    await assistant.on_user_turn_completed(
        turn_ctx, _FakeMessage("what about the events budget")
    )

    assert len(assistant._wm.pending_sources) == 1
    injected = _joined_injections(turn_ctx)
    assert "Hold events flat." in injected
    assert "Proactive" in injected


async def test_proactive_weak_match_stays_silent(stub_moss) -> None:
    """Below the interjection threshold → stay quiet, no LLM, nothing buffered."""
    assistant = Assistant(room=_FakeRoom(), group_id=GROUP_ID)
    assistant._moss.query_result = _FakeSearchResult(
        [_FakeDoc("loosely related", doc_id="x", score=max(THRESHOLD - 0.2, 0.0))]
    )

    turn_ctx = _FakeTurnCtx()
    with pytest.raises(StopResponse):
        await assistant.on_user_turn_completed(turn_ctx, _FakeMessage("small talk"))

    assert turn_ctx.added == []
    assert assistant._wm.pending_sources == []


async def test_proactive_already_surfaced_stays_silent(stub_moss) -> None:
    """Don't re-interject on context already surfaced this meeting."""
    assistant = Assistant(room=_FakeRoom(), group_id=GROUP_ID)
    assistant._wm.surfaced_card_ids.add("meet:1")
    assistant._moss.query_result = _FakeSearchResult(
        [_FakeDoc("Hold events flat.", doc_id="meet:1", score=THRESHOLD + 0.2)]
    )

    with pytest.raises(StopResponse):
        await assistant.on_user_turn_completed(
            _FakeTurnCtx(), _FakeMessage("events budget again")
        )


async def test_addressed_turn_answers_and_injects_screen_context(stub_moss) -> None:
    """An addressed turn does NOT abort the reply and injects what's on screen."""
    assistant = Assistant(room=_FakeRoom(), group_id=GROUP_ID)
    assistant._wm.recent_context = ["Hold events flat (decided in May review)."]

    turn_ctx = _FakeTurnCtx()
    await assistant.on_user_turn_completed(
        turn_ctx, _FakeMessage("tellmequick, can you explain that?")
    )

    assert assistant._wm.pending_query.lower().startswith("tellmequick")
    injected = _joined_injections(turn_ctx)
    assert "Hold events flat" in injected
    assert "Addressed" in injected


# ---- search_context -----------------------------------------------------------


async def test_search_context_queries_and_buffers_sources(stub_moss) -> None:
    room = _FakeRoom()
    assistant = Assistant(room=room, group_id=GROUP_ID)
    assistant._moss.query_result = _FakeSearchResult(
        [
            _FakeDoc(
                "Events drove 40% of pipeline.",
                doc_id="slack:1",
                score=0.91,
                metadata={"source": "slack"},
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

    # Sources buffered for the reply card; nothing published yet.
    assert len(assistant._wm.pending_sources) == 2
    assert room.local_participant.published == []


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


# ---- publish_reply_card -------------------------------------------------------


async def test_publish_reply_card_mirrors_spoken_answer_with_sources(stub_moss) -> None:
    room = _FakeRoom()
    assistant = Assistant(room=room, group_id=GROUP_ID)
    assistant._wm.pending_query = "what did we decide about events?"
    assistant._wm.pending_sources = [
        _FakeDoc("Hold events flat.", doc_id="meet:1", metadata={"source": "meeting"})
    ]

    await assistant.publish_reply_card("We decided to hold the events budget flat.")

    payload = _decoded(room.local_participant.published)
    assert payload["type"] == "moss_context"
    assert payload["data"]["answer"] == "We decided to hold the events budget flat."
    assert payload["data"]["matches"][0]["text"] == "Hold events flat."
    assert assistant._wm.pending_sources == []


async def test_publish_reply_card_skips_empty(stub_moss) -> None:
    """An empty reply produces no card and clears the buffer."""
    room = _FakeRoom()
    assistant = Assistant(room=room, group_id=GROUP_ID)
    assistant._wm.pending_sources = [_FakeDoc("x", doc_id="x")]

    await assistant.publish_reply_card("   ")

    assert room.local_participant.published == []
    assert assistant._wm.pending_sources == []


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
    assert len(docs) == 1
    assert docs[0].text == "Cut events 20%."
    assert agent_module.MEETINGS_INDEX in assistant._moss.load_index_calls


async def test_finalize_meeting_no_decisions_is_noop(stub_moss) -> None:
    assistant = Assistant(group_id=GROUP_ID, conversation_id="conv-empty")
    await assistant.finalize_meeting()
    assert assistant._moss.add_docs_calls == []
