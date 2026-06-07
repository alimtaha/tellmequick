import contextlib
import json
import logging
import os
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    cli,
    function_tool,
    inference,
    room_io,
)
from livekit.agents.llm import ChatMessage
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_epoch() -> float:
    # Epoch SECONDS — the frontend (useMossContextEvents.ts) multiplies by 1000.
    return datetime.now(timezone.utc).timestamp()


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
    """tellmequick: a real-time decision & context copilot.

    Listens to the meeting, retrieves relevant prior context across three Moss
    indexes (read-only), and surfaces it as cards while speaking briefly. Decisions
    flagged in the room are persisted post-meeting (no Moss writes mid-meeting).
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
            # AgentSession. https://docs.livekit.io/agents/models/
            llm=inference.LLM(model="openai/gpt-5.2-chat-latest"),
            instructions=textwrap.dedent(
                """\
                You are tellmequick, a real-time context copilot in a live meeting.
                Your job is to surface relevant prior context — documents, Slack
                discussions, and decisions from past meetings — exactly when it's
                useful, and to remember decisions the team makes.

                # Retrieval (very important)

                - Call `search_context` BEFORE you answer ANY time someone refers to
                  prior discussion, a specific document or filing, a past decision, a
                  number, or asks "what did we say / decide / agree". When in doubt,
                  search. Ground your reply in what it returns.
                - If `search_context` returns nothing relevant, say so plainly. Never
                  invent prior context, decisions, figures, or sources.
                - Do not call `search_context` for pure small talk or logistics
                  ("can you hear me", "let's start") — only for real context needs.

                # Decisions

                - When the team concludes or agrees on something, call `mark_decision`
                  with a one-sentence summary, a short `topic` key, and the `owner` if
                  named. This is captured now and saved after the meeting ends.
                - You do not save anything to long-term memory during the meeting; do
                  not claim that you have. Decisions are persisted when the meeting ends.

                # Output rules (you are speaking via TTS)

                - Plain text only. No markdown, lists, tables, code, or emojis.
                - Be brief: one to three sentences. When you surface context, say where
                  it came from in passing ("from a Slack thread in May", "decided in the
                  May review") — the full citation appears on screen.
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
        # continue on failure so tools can retry the load on use. Greeting is
        # triggered from the entrypoint (after connect), per the LiveKit pattern.
        if not self._indexes_loaded:
            try:
                await self._moss.load_indexes(ALL_INDEXES)
                self._indexes_loaded = True
                logger.info("Loaded Moss indexes: %s", ", ".join(ALL_INDEXES))
            except Exception:
                logger.exception("Failed to preload Moss indexes; will retry on use")

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

    # ---- tools ----------------------------------------------------------------

    @function_tool()
    async def search_context(self, context: RunContext, query: str) -> str:
        """Search the team's shared context for information relevant to the discussion.

        Searches all sources at once — documents and filings, Slack messages, and
        decisions from past meetings. Call this before answering anything that refers
        to prior discussion, a document, a past decision, or a specific figure.

        Args:
            query: What to look up, in natural language.
        """
        try:
            result = await self._moss.query_multi_index(
                ALL_INDEXES,
                query,
                QueryOptions(
                    top_k=6,
                    filter={
                        "field": "group_id",
                        "condition": {"$eq": self._group_id},
                    },
                ),
            )
        except Exception:
            logger.exception("search_context query failed")
            return "I couldn't search the context store just now."

        all_docs = getattr(result, "docs", None) or []
        # Dedup: drop anything already surfaced this meeting (don't re-flash a card).
        fresh = [
            d
            for d in all_docs
            if getattr(d, "id", None) not in self._wm.surfaced_card_ids
        ]
        for d in fresh:
            doc_id = getattr(d, "id", None)
            if doc_id:
                self._wm.surfaced_card_ids.add(doc_id)

        await self._publish_context(
            query, fresh, getattr(result, "time_taken_ms", None)
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

    # Voice pipeline on LiveKit Inference + the LiveKit turn detector.
    session = AgentSession(
        stt=inference.STT(model="deepgram/nova-3", language="multi"),
        tts=inference.TTS(
            model="cartesia/sonic-3", voice="9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

    # Capture finalized turns into working memory (in-process; feeds nothing on the
    # hot path — used only by the post-meeting distillation and dedup).
    @session.on("conversation_item_added")
    def _on_item(ev):
        item = ev.item
        if isinstance(item, ChatMessage):
            assistant.record_turn(item.role, item.text_content or "")

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

    await ctx.connect()

    await session.generate_reply(
        instructions=(
            "Greet the room warmly in one sentence, introduce yourself as their "
            "context copilot, and say you'll surface relevant prior context as the "
            "discussion goes. Do not ask a question."
        )
    )


if __name__ == "__main__":
    cli.run_app(server)
