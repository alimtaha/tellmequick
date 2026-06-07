import contextlib
import json
import logging
import os
import re
import textwrap
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

# --- Interaction model: display-first, voice-on-address ----------------------
# The agent listens quietly and surfaces context CARDS on the display without
# speaking (ambient). It only SPEAKS when addressed by name. See README/PRD.
#
# Wake names that switch the agent from ambient (display-only) to addressed
# (spoken reply). STT usually renders "tellmequick" as "tell me quick".
WAKE_NAMES = [
    n.strip().lower()
    for n in os.getenv("AGENT_WAKE_NAMES", "tellmequick,tell me quick").split(",")
    if n.strip()
]
# Ambient cards only surface when a hit scores at/above this. Tune per corpus —
# too low floods the display, too high never surfaces. Logged on each turn.
AMBIENT_SCORE_THRESHOLD = float(os.getenv("AMBIENT_SCORE_THRESHOLD", "0.3"))
# How many recently-surfaced snippets to keep for "explain what's on screen".
RECENT_CONTEXT_MAX = 6


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
    """tellmequick: a display-first, real-time decision & context copilot.

    Listens quietly. On each turn it retrieves relevant prior context across three
    Moss indexes (read-only) and surfaces it as cards on the display WITHOUT
    speaking — so it never interrupts the meeting. It only speaks when addressed by
    name, at which point it explains what's on screen and answers. Decisions flagged
    while addressed are persisted post-meeting (no Moss writes mid-meeting).
    """

    def __init__(
        self,
        *,
        room=None,
        group_id: str = DEFAULT_GROUP_ID,
        conversation_id: str = "local",
    ) -> None:
        super().__init__(
            # LLM runs on LiveKit Inference (no provider key). STT/TTS are on the
            # AgentSession. The LLM only runs when the agent is addressed by name.
            llm=inference.LLM(model="openai/gpt-5.2-chat-latest"),
            instructions=textwrap.dedent(
                """\
                You are tellmequick, a real-time context copilot in a live meeting.
                You are DISPLAY-FIRST: most of the time you stay silent and surface
                context cards on screen. You only speak when a participant calls you
                by name — which has just happened now.

                Because you were addressed, give a brief spoken reply:

                - If context is already shown on screen (it will be provided to you as
                  an assistant message), explain those results concisely and answer
                  what was asked.
                - For anything not already on screen, call `search_context` to look it
                  up, then answer grounded in what it returns. Never invent context,
                  decisions, figures, or sources — if nothing relevant is found, say so.
                - When the team concludes or agrees on something, call `mark_decision`
                  with a one-sentence summary, a short `topic` key, and the `owner` if
                  named. It is captured now and saved after the meeting ends; do not
                  claim anything is saved to long-term memory during the meeting.

                # Output rules (you are speaking via TTS)

                - Plain text only. No markdown, lists, tables, code, or emojis.
                - Be brief: one to three sentences. Mention the source in passing
                  ("from a Slack thread in May", "decided in the May review") — the full
                  citation is already on screen.
                - Don't read out URLs or internal IDs.

                # Guardrails

                - Stay within safe, lawful, appropriate use; decline harmful requests.
                - You surface evidence; you do not make the decision for the team.
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

    async def on_enter(self) -> None:
        # Preload all three indexes so the first retrieval is fast. Guarded: log and
        # continue on failure so retrieval can retry the load on use. No spoken
        # greeting — the agent joins silently (display-first).
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
        """Runs after every user turn, before any reply. This is the display-first
        switch: ambient turns surface a card and abort the spoken reply; addressed
        turns inject what's on screen and let the LLM speak."""
        text = new_message.text_content or ""
        self.record_turn("user", text)

        if is_addressed(text):
            # Addressed by name → speak. Give the LLM whatever is already on screen
            # so it can "explain the results it displayed", then let the reply run.
            if self._wm.recent_context:
                turn_ctx.add_message(
                    role="assistant",
                    content=(
                        "Context already shown on screen (most recent first):\n- "
                        + "\n- ".join(reversed(self._wm.recent_context))
                    ),
                )
            return  # do not StopResponse → the LLM generates a spoken reply

        # Ambient → surface a card if something is relevant, but stay silent.
        await self._ambient_surface(text)
        raise StopResponse()

    # ---- retrieval & surfacing ------------------------------------------------

    async def _ambient_surface(self, text: str) -> None:
        """Quietly surface a card if this turn strongly matches stored context.
        Score-gated and deduped so the display doesn't flash on every sentence."""
        if not text.strip():
            return
        try:
            result = await self._moss.query_multi_index(
                ALL_INDEXES, text, self._query_options(top_k=3)
            )
        except Exception:
            logger.exception("ambient query failed")
            return
        docs = getattr(result, "docs", None) or []
        top = max((getattr(d, "score", None) or 0.0 for d in docs), default=0.0)
        relevant = [
            d
            for d in docs
            if (getattr(d, "score", None) or 0.0) >= AMBIENT_SCORE_THRESHOLD
        ]
        logger.info(
            "ambient turn: top_score=%.3f threshold=%.3f surfacing=%d",
            top,
            AMBIENT_SCORE_THRESHOLD,
            len(relevant),
        )
        if relevant:
            await self._surface(
                text, relevant, getattr(result, "time_taken_ms", None), dedup=True
            )

    def _query_options(self, top_k: int) -> QueryOptions:
        return QueryOptions(
            top_k=top_k,
            filter={"field": "group_id", "condition": {"$eq": self._group_id}},
        )

    async def _surface(
        self, query: str, docs: list, time_taken_ms, *, dedup: bool
    ) -> list:
        """Record + publish a set of result docs as a card. With dedup=True, drop
        docs already surfaced this meeting (ambient); with dedup=False, surface all
        (an explicit search_context call the user asked for)."""
        if dedup:
            fresh = [
                d
                for d in docs
                if getattr(d, "id", None) not in self._wm.surfaced_card_ids
            ]
        else:
            fresh = list(docs)
        if not fresh:
            return []
        for d in fresh:
            doc_id = getattr(d, "id", None)
            if doc_id:
                self._wm.surfaced_card_ids.add(doc_id)
            snippet = (getattr(d, "text", "") or "").strip()
            if snippet:
                self._wm.recent_context.append(snippet)
        # cap recent context
        if len(self._wm.recent_context) > RECENT_CONTEXT_MAX:
            self._wm.recent_context = self._wm.recent_context[-RECENT_CONTEXT_MAX:]
        await self._publish_context(query, fresh, time_taken_ms)
        return fresh

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

    async def _publish_context(self, query: str, docs: list, time_taken_ms) -> None:
        """Publish a `moss_context` message for the frontend context panel.

        Payload shape is contractual — the frontend parser
        (frontend hooks/useMossContextEvents.ts) depends on these exact keys.
        `timestamp` is epoch SECONDS (the frontend multiplies by 1000).
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
        await self._publish(
            "moss_context",
            {
                "query": query,
                "matches": matches,
                "time_taken_ms": time_taken_ms,
                "timestamp": _now_epoch(),
            },
        )

    # ---- tools (only reachable when addressed) --------------------------------

    @function_tool()
    async def search_context(self, context: RunContext, query: str) -> str:
        """Search the team's shared context for information relevant to the discussion.

        Searches all sources at once — documents and filings, Slack messages, and
        decisions from past meetings. Use it to answer the question you were just
        asked when the answer isn't already on screen.

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
        # Explicit ask → surface all (no dedup); the user wants these results now.
        fresh = await self._surface(
            query, docs, getattr(result, "time_taken_ms", None), dedup=False
        )
        snippets = [(getattr(d, "text", "") or "").strip() for d in fresh]
        snippets = [s for s in snippets if s]
        if not snippets:
            return "No relevant context found."
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

    # Voice pipeline on LiveKit Inference + the LiveKit turn detector. TTS is wired,
    # but the agent only actually speaks when addressed by name (see
    # Assistant.on_user_turn_completed); ambient turns abort the reply.
    session = AgentSession(
        stt=inference.STT(model="deepgram/nova-3", language="multi"),
        tts=inference.TTS(
            model="cartesia/sonic-3", voice="9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

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

    # Join silently — display-first, no spoken greeting that would interrupt.
    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(server)
