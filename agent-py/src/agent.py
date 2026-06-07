import asyncio
import contextlib
import json
import logging
import os
import random
import re
import textwrap
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    ChatContext,
    ChatMessage,
    JobContext,
    JobProcess,
    RunContext,
    StopResponse,
    cli,
    function_tool,
    inference,
    room_io,
)
from livekit.plugins import ai_coustics, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from moss import DocumentInfo, MossClient, QueryOptions

logger = logging.getLogger("agent")

load_dotenv(".env.local")

# Three Moss indexes (names overridable via env so create_index.py and the agent
# stay in sync). See agent-py/src/create_index.py and technical-architecture.md §5.
#   knowledge — filings / docs        (async ingest, read-only at runtime)
#   slack     — Slack messages        (async ingest, read-only at runtime)
#   meetings  — distilled decisions    (read-only in-meeting; written post-meeting)
KNOWLEDGE_INDEX = os.getenv("MOSS_KNOWLEDGE_INDEX", "knowledge")
SLACK_INDEX = os.getenv("MOSS_SLACK_INDEX", "slack")
MEETINGS_INDEX = os.getenv("MOSS_MEETINGS_INDEX", "meetings")
ALL_INDEXES = [KNOWLEDGE_INDEX, SLACK_INDEX, MEETINGS_INDEX]

# Single-group demo scope. The frontend can override via dispatch metadata.
DEFAULT_GROUP_ID = os.getenv("DEFAULT_GROUP_ID", "acme-finance")

# The one model — drives spoken replies AND proactive interjections.
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-5.2-chat-latest")

# --- Interaction model: a tactful "third participant" ------------------------
# The agent listens. One cheap Moss retrieval after each turn gates whether it has
# anything relevant. If so it does NOT jump in — it waits a short grace window for
# the humans to answer. If the room stays silent it fills the gap; if a human
# answers it stays quiet, UNLESS what they said contradicts the sources, in which
# case it corrects them. It answers immediately only when addressed by name.
WAKE_NAMES = [
    n.strip().lower()
    for n in os.getenv("AGENT_WAKE_NAMES", "tellmequick,tell me quick").split(",")
    if n.strip()
]
# Speaking interrupts humans, so this bar is higher than a glanceable card would
# warrant. Tune per corpus; every turn logs the top score. Below the bar = instant
# silence, no LLM call.
INTERJECT_THRESHOLD = float(os.getenv("INTERJECT_THRESHOLD", "0.4"))
# How long to wait for a human to answer before filling a silent gap. Cancelled the
# instant a human starts speaking, so the agent yields the floor.
INTERJECT_GRACE = float(os.getenv("INTERJECT_GRACE_S", "1.2"))
# How many recently-surfaced results to keep for "explain what's on screen".
RECENT_CONTEXT_MAX = 6

# Spoken immediately only when ADDRESSED by name — an explicit ask wants a fast ack.
FILLER_ADDRESSED = [
    "Let me check that.",
    "One second, pulling that up.",
    "Let me look that up for you.",
]

# Standalone-LLM prompts for out-of-turn speech. Each returns exactly "PASS" to
# stay silent, so a non-PASS reply is the signal to actually speak.
GAP_SYSTEM = textwrap.dedent(
    """\
    No one in the meeting answered the topic below. Using ONLY the grounded facts
    provided, state the answer in ONE short spoken sentence, mentioning the source in
    passing (e.g. "per the 10-K"). If the facts don't actually answer it, reply with
    exactly: PASS
    Plain text only.
    """
)
CORRECTION_SYSTEM = textwrap.dedent(
    """\
    Someone in the meeting just made the statement below. Compare it to the grounded
    facts. If the statement is factually wrong or contradicts the facts, reply with a
    ONE-sentence spoken correction beginning with "Actually," and citing the source in
    passing. If the statement is correct, consistent, or simply unrelated, reply with
    exactly: PASS
    Plain text only.
    """
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_epoch() -> float:
    # Epoch SECONDS — the frontend (useMossContextEvents.ts) multiplies by 1000.
    return datetime.now(timezone.utc).timestamp()


def is_addressed(text: str, wake_names: list[str] = WAKE_NAMES) -> bool:
    """True if the user explicitly called the agent by name in this turn.

    Punctuation-insensitive, case-insensitive substring match so "Tellmequick,"
    and "tell me quick" both trigger.
    """
    norm = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    return any(name and name in norm for name in wake_names)


def _chunk_text(chunk) -> str | None:
    """Extract the text delta from an llm_node chunk (a plain str or a ChatChunk
    with `.delta.content`). Returns None for tool-call / empty chunks."""
    if isinstance(chunk, str):
        return chunk or None
    delta = getattr(chunk, "delta", None)
    content = getattr(delta, "content", None) if delta is not None else None
    return content or None


@dataclass
class Decision:
    """A decision flagged live during a meeting, captured in working memory."""

    text: str
    topic: str | None = None
    owner: str | None = None
    ts: str = ""


@dataclass
class WorkingMemory:
    """In-process, ephemeral state for the active meeting. The ONLY store mutated
    during a meeting — Moss is read-only until the post-meeting distillation."""

    conversation_id: str
    group_id: str
    turns: list[tuple[str, str]] = field(default_factory=list)  # (role, text)
    surfaced_card_ids: set[str] = field(default_factory=set)
    recent_context: list[str] = field(default_factory=list)  # last surfaced snippets
    pending_decisions: list[Decision] = field(default_factory=list)
    # Per-turn buffer: sources + question paired with the spoken line into one card.
    pending_sources: list = field(default_factory=list)
    pending_query: str = ""
    # Stable id for the current turn's card, so streamed partials + the final
    # update the SAME card in the UI instead of stacking new ones.
    turn_seq: int = 0
    turn_card_id: str = ""


def resolve_decisions(pending: list[Decision]) -> list[Decision]:
    """Within-meeting conflict resolution: for decisions that share a ``topic``,
    keep the latest (last appended) — a reversal supersedes the earlier call.
    Decisions with no topic are all kept, in arrival order."""
    latest_by_topic: dict[str, Decision] = {}
    topicless: list[Decision] = []
    for d in pending:
        if d.topic:
            latest_by_topic[d.topic] = d  # later overwrites earlier
        else:
            topicless.append(d)
    return topicless + list(latest_by_topic.values())


def build_meeting_docs(
    group_id: str,
    conversation_id: str,
    decisions: list[Decision],
    summary_text: str | None = None,
) -> list[DocumentInfo]:
    """Build the Moss docs written to the ``meetings`` index at meeting end.

    Deterministic ids keyed on ``conversation_id`` make re-running the
    distillation idempotent (overwrites that meeting's docs in place). All
    metadata values are strings, per Moss's constraint.
    """
    docs: list[DocumentInfo] = []
    if summary_text:
        docs.append(
            DocumentInfo(
                id=f"{group_id}:{conversation_id}:note:0",
                text=summary_text,
                metadata={
                    "source": "meeting",
                    "kind": "note",
                    "group_id": group_id,
                    "conversation_id": conversation_id,
                    "timestamp": _now_iso(),
                },
            )
        )
    for i, d in enumerate(decisions):
        docs.append(
            DocumentInfo(
                id=f"{group_id}:{conversation_id}:decision:{i}",
                text=d.text,
                metadata={
                    "source": "meeting",
                    "kind": "decision",
                    "is_decision": "true",
                    "group_id": group_id,
                    "conversation_id": conversation_id,
                    "topic": d.topic or "",
                    "owner": d.owner or "",
                    "timestamp": d.ts or _now_iso(),
                },
            )
        )
    return docs


class Assistant(Agent):
    """tellmequick: a real-time context copilot that behaves like a third participant.

    It listens; one cheap retrieval after each turn gates whether it speaks. On a
    strong, fresh match it says a quick filler immediately (so it feels responsive)
    while its LLM produces the grounded reply, which streams right after. It also
    answers when addressed by name. Spoken lines are mirrored to display cards.
    Decisions are persisted post-meeting (no Moss writes mid-meeting).
    """

    def __init__(
        self,
        *,
        room=None,
        group_id: str = DEFAULT_GROUP_ID,
        conversation_id: str = "local",
    ) -> None:
        super().__init__(
            llm=inference.LLM(model=LLM_MODEL),
            instructions=textwrap.dedent(
                """\
                You are tellmequick, a context copilot sitting in a live meeting like
                a knowledgeable third participant. You can see the team's documents,
                Slack history, and decisions from past meetings.

                A short filler ("let me pull that up") is spoken for you the instant
                you're triggered — do NOT repeat it. Get straight to the substance.

                You produce a reply in two situations, signalled by an instruction
                injected as the latest assistant message:

                1) PROACTIVE — relevant prior context just came up. In ONE short
                   sentence, surface the most useful, non-obvious point from it for
                   what was just said. If what the team needs is genuinely ambiguous,
                   instead ask ONE short clarifying question.

                2) ADDRESSED — a participant called you by name. Answer their question.
                   Use search_context for anything not already provided to you. If the
                   ask is ambiguous, ask one short clarifying question.

                When the team concludes or agrees on something, call mark_decision with
                a one-sentence summary, a short topic key, and the owner if named. It's
                saved after the meeting; don't claim it's saved during the meeting.

                Output rules (you are spoken aloud via TTS):
                - Plain text only. No markdown, lists, tables, code, or emoji.
                - Be brief — one or two sentences. Mention the source in passing
                  ("from Slack in May", "the May review decision").
                - Don't read out URLs or internal IDs.
                - You surface evidence; you don't make the decision for the team.
                """
            ),
        )
        self._room = room
        self._group_id = group_id
        self._moss = MossClient(
            os.getenv("MOSS_PROJECT_ID"), os.getenv("MOSS_PROJECT_KEY")
        )
        self._wm = WorkingMemory(conversation_id=conversation_id, group_id=group_id)
        self._indexes_loaded = False
        # Deferred-interjection state: a held topic awaiting the grace window, the
        # timer task, a set of background tasks, and a standalone LLM for out-of-turn
        # gap-fills / corrections (off the voice pipeline).
        self._pending: dict | None = None
        self._grace_task: asyncio.Task | None = None
        self._tasks: set = set()
        self._aux_llm = inference.LLM(model=LLM_MODEL)

    async def on_enter(self) -> None:
        # Preload all three indexes so the first retrieval is fast. Guarded: log and
        # continue on failure so retrieval can retry the load on use. No spoken
        # greeting — the agent joins silently and only speaks when it has something.
        if not self._indexes_loaded:
            try:
                await self._moss.load_indexes(ALL_INDEXES)
                self._indexes_loaded = True
                logger.info("Loaded Moss indexes: %s", ", ".join(ALL_INDEXES))
            except Exception:
                logger.exception("Failed to preload Moss indexes; will retry on use")

    # ---- the interaction gate -------------------------------------------------

    async def on_user_turn_completed(
        self, turn_ctx: ChatContext, new_message: ChatMessage
    ) -> None:
        """Runs after every user turn. The agent doesn't jump in: addressed → answer;
        a strong fresh match → hold it and wait a beat (the grace timer), staying
        silent now; and if a held topic was just (mis)answered → judge + maybe correct."""
        text = new_message.text_content or ""
        self.record_turn("user", text)
        self._wm.turn_seq += 1
        self._wm.turn_card_id = f"{self._wm.conversation_id}:{self._wm.turn_seq}"

        # A new turn arrived: stop any in-flight gap-fill; remember what was pending.
        prev = self._pending
        self._pending = None
        self._cancel_grace()

        if is_addressed(text):
            # Explicit address → answer immediately. Quick filler, then the pipeline.
            self._wm.pending_sources = []
            self._wm.pending_query = text
            self._say_filler(FILLER_ADDRESSED)
            if self._wm.recent_context:
                turn_ctx.add_message(
                    role="assistant",
                    content=(
                        "Context already on screen (most recent first):\n- "
                        + "\n- ".join(reversed(self._wm.recent_context))
                    ),
                )
            turn_ctx.add_message(
                role="assistant",
                content=(
                    "[Addressed] A participant called you by name. Answer concisely; "
                    "use search_context for anything not already shown. If the ask is "
                    "ambiguous, ask one short clarifying question."
                ),
            )
            return  # answer immediately via the pipeline

        # If the agent was holding context and a human just spoke to it, check (in the
        # background) whether they got it wrong — and correct only if so.
        if prev is not None:
            self._spawn(self._maybe_correct(prev, text))

        # Gate this turn: is there strong, fresh context worth holding?
        try:
            result = await self._moss.query_multi_index(
                ALL_INDEXES, text, self._query_options(top_k=5)
            )
        except Exception:
            logger.exception("proactive query failed")
            raise StopResponse() from None
        docs = getattr(result, "docs", None) or []
        top = max((getattr(d, "score", None) or 0.0 for d in docs), default=0.0)
        relevant = [
            d for d in docs if (getattr(d, "score", None) or 0.0) >= INTERJECT_THRESHOLD
        ]
        logger.info(
            "proactive turn: top_score=%.3f threshold=%.3f relevant=%d",
            top,
            INTERJECT_THRESHOLD,
            len(relevant),
        )
        if relevant and not all(
            getattr(d, "id", None) in self._wm.surfaced_card_ids for d in relevant
        ):
            # Hold it — wait the grace window for the humans to answer first.
            self._pending = {
                "query": text,
                "sources": relevant,
                "seq": self._wm.turn_seq,
            }
            self._grace_task = self._spawn(
                self._grace_then_fill(self._pending, self._wm.turn_seq)
            )
        raise StopResponse()  # proactive never speaks immediately

    def _say_filler(self, fillers: list[str]) -> None:
        """Speak a quick filler immediately (non-blocking) so the agent feels
        responsive while the real reply generates. Best-effort — never let it break
        the turn, and don't add it to the chat context."""
        try:
            self.session.say(
                random.choice(fillers),
                allow_interruptions=True,
                add_to_chat_ctx=False,
            )
        except Exception:
            logger.debug("could not play filler (no active session?)")

    # ---- deferred interjection (grace window + correction) --------------------

    def _spawn(self, coro) -> asyncio.Task:
        """Run a coroutine in the background, keeping a strong ref so it isn't GC'd."""
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _cancel_grace(self) -> None:
        if self._grace_task is not None and not self._grace_task.done():
            self._grace_task.cancel()
        self._grace_task = None

    def on_user_started_speaking(self) -> None:
        """A human took the floor — hold any gap-fill (but keep the pending topic, so
        the completed turn can still be judged for a wrong answer)."""
        if self._grace_task is not None and not self._grace_task.done():
            logger.info("user speaking — holding gap-fill")
            self._cancel_grace()

    async def _grace_then_fill(self, pending: dict, seq: int) -> None:
        """After the grace window, if the room stayed silent, fill the gap out of turn."""
        try:
            await asyncio.sleep(INTERJECT_GRACE)
        except asyncio.CancelledError:
            return
        if self._wm.turn_seq != seq or self._pending is not pending:
            return  # a newer turn superseded this, or it was cancelled
        self._pending = None
        line = await self._generate_grounded(
            GAP_SYSTEM, pending["query"], "", pending["sources"]
        )
        if line:
            logger.info("gap-fill: room stayed silent, interjecting")
            self._speak_out_of_turn(pending["query"], pending["sources"], line)

    async def _maybe_correct(self, prev: dict, human_text: str) -> None:
        """Judge a human's turn against a held topic's sources; correct only if wrong."""
        line = await self._generate_grounded(
            CORRECTION_SYSTEM, prev["query"], human_text, prev["sources"]
        )
        if line:
            logger.info("correction: a stated fact contradicted the sources")
            self._speak_out_of_turn(prev["query"], prev["sources"], line)

    async def _generate_grounded(
        self, system: str, query: str, statement: str, sources: list
    ) -> str | None:
        """Standalone LLM call (off the voice pipeline) → a one-line spoken reply, or
        None if it returns the PASS sentinel."""
        src = "\n".join(
            f"- ({(getattr(d, 'metadata', {}) or {}).get('source', '?')}) "
            f"{(getattr(d, 'text', '') or '').strip()}"
            for d in sources
        )
        ctx = ChatContext()
        ctx.add_message(role="system", content=system)
        ctx.add_message(
            role="user",
            content=(
                f"Topic: {query}\n\n"
                f"What someone just said: {statement or '(no one answered)'}\n\n"
                f"Grounded facts:\n{src}"
            ),
        )
        try:
            resp = await self._aux_llm.chat(chat_ctx=ctx).collect()
            t = (resp.text or "").strip()
        except Exception:
            logger.exception("aux generation failed")
            return None
        return None if (not t or t.upper().startswith("PASS")) else t

    def _speak_out_of_turn(self, query: str, sources: list, line: str) -> None:
        """Speak a pre-generated line now (non-blocking). The display card is published
        by the conversation_item_added handler (say adds to the chat ctx by default)."""
        self._wm.pending_query = query
        self._wm.pending_sources = list(sources)
        try:
            self.session.say(line, allow_interruptions=True)
        except Exception:
            logger.exception("could not speak out of turn")

    async def llm_node(self, chat_ctx, tools, model_settings):
        """Stream the reply to the display card as it generates, so context shows up
        token-by-token instead of all at once when speech finishes. Yields chunks
        unchanged so STT→LLM→TTS is untouched; the final card is committed by the
        conversation_item_added handler (same turn_card_id, so it updates in place)."""
        acc = ""
        last = 0.0
        async for chunk in Agent.default.llm_node(
            self, chat_ctx, tools, model_settings
        ):
            delta = _chunk_text(chunk)
            if delta:
                acc += delta
                now = time.monotonic()
                # Throttle: ~7 updates/sec is plenty for a smoothly growing card.
                if now - last >= 0.15 and acc.strip():
                    last = now
                    with contextlib.suppress(Exception):
                        await self._publish_context(
                            self._wm.pending_query or "(interjection)",
                            self._wm.pending_sources,
                            None,
                            answer=acc.strip(),
                            card_id=self._wm.turn_card_id,
                            streaming=True,
                        )
            yield chunk

    # ---- retrieval helpers ----------------------------------------------------

    def _query_options(self, top_k: int) -> QueryOptions:
        return QueryOptions(
            top_k=top_k,
            filter={"field": "group_id", "condition": {"$eq": self._group_id}},
        )

    def _mark_surfaced(self, docs: list, recent_snippet: str | None) -> None:
        """Record surfaced doc ids (for dedup) and the snippet shown (so an addressed
        turn can explain what's on screen)."""
        for d in docs:
            doc_id = getattr(d, "id", None)
            if doc_id:
                self._wm.surfaced_card_ids.add(doc_id)
        if recent_snippet:
            self._wm.recent_context.append(recent_snippet)
            if len(self._wm.recent_context) > RECENT_CONTEXT_MAX:
                self._wm.recent_context = self._wm.recent_context[-RECENT_CONTEXT_MAX:]

    async def publish_reply_card(self, answer: str) -> None:
        """Mirror a spoken line (interjection or addressed answer) to a display card,
        paired with the sources for that turn. Clears the per-turn buffer."""
        answer = (answer or "").strip()
        sources = self._wm.pending_sources
        self._wm.pending_sources = []
        if not answer:
            return
        self._mark_surfaced(sources, answer)
        # Final update for this turn's card (same id as the streamed partials);
        # streaming=False clears the UI "typing" state.
        await self._publish_context(
            self._wm.pending_query or "(interjection)",
            sources,
            None,
            answer=answer,
            card_id=self._wm.turn_card_id,
        )

    # ---- working memory -------------------------------------------------------

    def record_turn(self, role: str, text: str) -> None:
        """Append a finalized turn to working memory (in-process; no Moss write)."""
        if text and text.strip():
            self._wm.turns.append((role, text.strip()))

    # ---- data-channel publishing ---------------------------------------------

    async def _publish(self, type_: str, data: dict) -> None:
        if self._room is None:
            return
        try:
            payload = {"type": type_, "data": data}
            encoded = json.dumps(payload, default=str).encode("utf-8")
            await self._room.local_participant.publish_data(
                payload=encoded, reliable=True
            )
        except Exception:
            logger.exception("Failed to publish %s data", type_)

    async def _publish_context(
        self,
        query: str,
        docs: list,
        time_taken_ms,
        answer: str | None = None,
        card_id: str | None = None,
        streaming: bool = False,
    ) -> None:
        """Publish a `moss_context` message for the frontend context panel.

        Payload shape is contractual — the frontend parser
        (frontend hooks/useMossContextEvents.ts) depends on these keys. `answer` is
        the spoken line shown as the card headline; `matches` are the supporting
        sources for citation. `id` lets the frontend update one card in place as the
        reply streams; `streaming` flags an in-progress (partial) update. `timestamp`
        is epoch SECONDS (frontend multiplies x1000).
        """
        matches: list[dict] = []
        for doc in docs:
            entry: dict = {"text": (getattr(doc, "text", "") or "").strip()}
            score = getattr(doc, "score", None)
            if score is not None:
                with contextlib.suppress(TypeError, ValueError):
                    entry["score"] = float(score)
            metadata = getattr(doc, "metadata", None)
            if metadata:
                entry["metadata"] = metadata
            matches.append(entry)
        data: dict = {
            "query": query,
            "matches": matches,
            "time_taken_ms": time_taken_ms,
            "timestamp": _now_epoch(),
        }
        if answer is not None:
            data["answer"] = answer
        if card_id:
            data["id"] = card_id
        if streaming:
            data["streaming"] = True
        await self._publish("moss_context", data)

    # ---- tools ----------------------------------------------------------------

    @function_tool()
    async def search_context(self, context: RunContext, query: str) -> str:
        """Search the team's shared context for information relevant to the discussion.

        Searches all sources at once — documents and filings, Slack messages, and
        decisions from past meetings. Use it to answer a question you were asked when
        the answer isn't already provided to you.

        Args:
            query: What to look up, in natural language.
        """
        try:
            result = await self._moss.query_multi_index(
                ALL_INDEXES, query, self._query_options(top_k=6)
            )
        except Exception:
            logger.exception("search_context query failed")
            return "I couldn't search the context store just now."

        docs = getattr(result, "docs", None) or []
        snippets = [(getattr(d, "text", "") or "").strip() for d in docs]
        snippets = [s for s in snippets if s]
        if not snippets:
            return "No relevant context found."
        # Buffer sources; the card is published with the spoken reply (publish_reply_card).
        self._wm.pending_sources.extend(docs)
        return "\n\n".join(snippets)

    @function_tool()
    async def mark_decision(
        self, context: RunContext, decision: str, topic: str = "", owner: str = ""
    ) -> str:
        """Record a decision the team makes during the meeting.

        Captured in working memory now and persisted to long-term memory after the
        meeting ends (not during). Use a stable `topic` so a later decision on the
        same topic supersedes this one.

        Args:
            decision: The decision, in one sentence.
            topic: Short topic key, e.g. "events-budget".
            owner: Who owns or made the decision, if stated.
        """
        self._wm.pending_decisions.append(
            Decision(
                text=decision,
                topic=topic or None,
                owner=owner or None,
                ts=_now_iso(),
            )
        )
        await self._publish(
            "decision_pending",
            {"text": decision, "topic": topic, "owner": owner},
        )
        return "Noted — I'll capture that decision for next time."

    # ---- post-meeting distillation -------------------------------------------

    async def finalize_meeting(self) -> None:
        """Post-meeting write (the ONLY Moss write). Resolve within-meeting conflicts,
        build decision docs, and append them to the `meetings` index. Called from the
        job's shutdown hook. Retries, then dumps to a crash file on persistent failure.
        """
        decisions = resolve_decisions(self._wm.pending_decisions)
        docs = build_meeting_docs(self._group_id, self._wm.conversation_id, decisions)
        if not docs:
            logger.info("No decisions to persist for %s", self._wm.conversation_id)
            return

        for attempt in range(3):
            try:
                await self._moss.add_docs(MEETINGS_INDEX, docs)
                await self._moss.load_index(MEETINGS_INDEX)
                logger.info(
                    "Persisted %d decision doc(s) to '%s' for %s",
                    len(docs),
                    MEETINGS_INDEX,
                    self._wm.conversation_id,
                )
                return
            except Exception:
                logger.exception(
                    "meetings flush failed (attempt %d/3) for %s",
                    attempt + 1,
                    self._wm.conversation_id,
                )

        self._dump_crash(docs)

    def _dump_crash(self, docs: list[DocumentInfo]) -> None:
        path = f"/tmp/lkdistill-{self._wm.conversation_id}.jsonl"
        try:
            with open(path, "w", encoding="utf-8") as handle:
                for doc in docs:
                    handle.write(
                        json.dumps(
                            {"id": doc.id, "text": doc.text, "metadata": doc.metadata}
                        )
                        + "\n"
                    )
            logger.error("meetings flush failed permanently; dumped to %s", path)
        except Exception:
            logger.exception("could not write distillation crash file")


server = AgentServer()


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


# Keep the registered dispatch name as "agent-py": the frontend sets
# AGENT_NAME=agent-py to dispatch explicitly to this worker. Do not rename.
@server.rtc_session(agent_name="agent-py")
async def my_agent(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    # Identify the group from dispatch metadata. The frontend packs
    # {"group_id": ...} into ctx.job.metadata; console mode has none, so fall back.
    group_id = DEFAULT_GROUP_ID
    if ctx.job.metadata:
        try:
            group_id = json.loads(ctx.job.metadata).get("group_id", DEFAULT_GROUP_ID)
        except json.JSONDecodeError:
            logger.warning(
                "ctx.job.metadata was not valid JSON; using default group_id"
            )

    assistant = Assistant(
        room=ctx.room, group_id=group_id, conversation_id=ctx.room.name
    )

    # Voice pipeline on LiveKit Inference + the LiveKit turn detector. The reply
    # streams (no buffering); a quick filler is spoken first to mask generation
    # latency. The agent speaks only when it interjects or is addressed.
    session = AgentSession(
        stt=inference.STT(model="deepgram/nova-3", language="multi"),
        tts=inference.TTS(
            model="cartesia/sonic-3", voice="9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

    # Mirror each spoken reply (interjection or addressed answer) to a display card,
    # paired with the sources it cited. Fillers use add_to_chat_ctx=False, so they
    # don't fire this event and don't produce cards.
    bg_tasks: set = set()

    @session.on("conversation_item_added")
    def _on_item(ev):
        item = ev.item
        if (
            isinstance(item, ChatMessage)
            and item.role == "assistant"
            and item.text_content
        ):
            task = asyncio.create_task(assistant.publish_reply_card(item.text_content))
            bg_tasks.add(task)
            task.add_done_callback(bg_tasks.discard)

    # When a human starts talking, hold any pending gap-fill — yield them the floor.
    @session.on("user_state_changed")
    def _on_user_state(ev):
        if getattr(ev, "new_state", None) == "speaking":
            assistant.on_user_started_speaking()

    # Persist decisions when the meeting ends (room empties). Shutdown hooks must
    # finish within ~10s (tunable via shutdown_process_timeout in server options).
    ctx.add_shutdown_callback(assistant.finalize_meeting)

    await session.start(
        agent=assistant,
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=ai_coustics.audio_enhancement(
                    model=ai_coustics.EnhancerModel.QUAIL_VF_S
                ),
            ),
        ),
    )

    # Join silently — speaks only when it has something to add or is addressed.
    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(server)
