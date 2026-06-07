import { useEffect, useMemo, useState } from 'react';
import { RoomEvent } from 'livekit-client';
import { useRoomContext } from '@livekit/components-react';
import type { AgentCard, CardSource, ChartSpec } from '@/components/app/cards/card-types';

const decoder = new TextDecoder();
const MAX_CARDS = 50;

function sourcesFromMatches(matches: unknown): CardSource[] {
  if (!Array.isArray(matches)) return [];
  return matches
    .filter((m) => m && typeof m === 'object')
    .map((m) => {
      const match = m as Record<string, unknown>;
      const meta = (
        match.metadata && typeof match.metadata === 'object'
          ? (match.metadata as Record<string, unknown>)
          : {}
      ) as Record<string, unknown>;
      return {
        text: typeof match.text === 'string' ? match.text : '',
        score: typeof match.score === 'number' ? match.score : undefined,
        source: typeof meta.source === 'string' ? meta.source : undefined,
        url: typeof meta.url === 'string' ? meta.url : undefined,
      };
    })
    .filter((s) => s.text);
}

/** Parse one data-channel payload into a card (or null to ignore). */
function parse(payload: Uint8Array): AgentCard | null {
  let message: { type?: string; data?: Record<string, unknown> };
  try {
    message = JSON.parse(decoder.decode(payload));
  } catch {
    return null;
  }
  if (!message || typeof message.data !== 'object' || !message.data) return null;
  const data = message.data;
  const tsRaw = typeof data.timestamp === 'number' ? data.timestamp : Date.now() / 1000;
  const ts = tsRaw * 1000;
  const id = `${ts}-${Math.random().toString(36).slice(2, 8)}`;

  switch (message.type) {
    case 'moss_context': {
      const answer = typeof data.answer === 'string' ? data.answer : '';
      const query = typeof data.query === 'string' ? data.query : undefined;
      const sources = sourcesFromMatches(data.matches);
      // Grounded reply with citations → context card; bare spoken line → transcription.
      if (sources.length > 0) {
        return {
          id,
          ts,
          kind: 'context',
          answer: answer || query || 'Relevant context',
          query,
          sources,
          timeTakenMs: typeof data.time_taken_ms === 'number' ? data.time_taken_ms : null,
        };
      }
      if (!answer) return null;
      return { id, ts, kind: 'transcription', answer, query };
    }
    case 'decision_pending': {
      const text = typeof data.text === 'string' ? data.text : '';
      if (!text) return null;
      return {
        id,
        ts,
        kind: 'decision',
        text,
        topic: typeof data.topic === 'string' && data.topic ? data.topic : undefined,
        owner: typeof data.owner === 'string' && data.owner ? data.owner : undefined,
      };
    }
    case 'agent_viz': {
      const spec = data.spec as ChartSpec | undefined;
      if (!spec || !Array.isArray(spec.data) || !Array.isArray(spec.series)) return null;
      return {
        id,
        ts,
        kind: 'viz',
        title: typeof data.title === 'string' ? data.title : 'Insight',
        spec,
        sources: sourcesFromMatches(data.matches),
      };
    }
    default:
      return null;
  }
}

/**
 * Subscribes to the agent's data-channel messages and returns the live feed of
 * cards, newest first. Must be used within a RoomContext.
 */
export function useAgentCards(): AgentCard[] {
  const room = useRoomContext();
  const [cards, setCards] = useState<AgentCard[]>([]);

  useEffect(() => {
    if (!room) return;
    const onData = (payload: Uint8Array) => {
      const card = parse(payload);
      if (!card) return;
      setCards((prev) => [card, ...prev].slice(0, MAX_CARDS));
    };
    room.on(RoomEvent.DataReceived, onData);
    return () => {
      room.off(RoomEvent.DataReceived, onData);
    };
  }, [room]);

  return useMemo(() => cards, [cards]);
}
