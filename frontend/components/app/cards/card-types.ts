// Unified card model for the tellmequick meeting feed. The agent publishes
// data-channel messages (moss_context, decision_pending, agent_viz) which
// useAgentCards() normalizes into these cards. See hooks/useAgentCards.ts.

export type CardKind = 'context' | 'transcription' | 'decision' | 'viz';

export type CardSource = {
  text: string;
  source?: string; // e.g. "slack" | "filing" | "meeting"
  score?: number;
  url?: string;
};

export type ChartKind = 'line' | 'area' | 'bar';

export type ChartSeries = {
  key: string; // data key in each row
  label?: string; // legend label
  color?: string; // optional explicit color, else palette
};

export type ChartSpec = {
  chart: ChartKind;
  xKey: string;
  series: ChartSeries[];
  data: Array<Record<string, string | number>>;
  unit?: string;
  caption?: string;
};

type Base = { id: string; ts: number };

export type ContextCard = Base & {
  kind: 'context';
  answer: string; // synthesized/spoken line, grounded
  query?: string;
  sources: CardSource[];
  timeTakenMs?: number | null;
};

export type TranscriptionCard = Base & {
  kind: 'transcription';
  answer: string; // what the agent said (no sources attached)
  query?: string;
};

export type DecisionCard = Base & {
  kind: 'decision';
  text: string;
  topic?: string;
  owner?: string;
};

export type VizCard = Base & {
  kind: 'viz';
  title: string;
  spec: ChartSpec;
  sources?: CardSource[];
};

export type AgentCard = ContextCard | TranscriptionCard | DecisionCard | VizCard;

/** Accent color var (CSS) per card kind — drives the left rail + label + icon. */
export const KIND_ACCENT: Record<CardKind, string> = {
  context: 'var(--context)',
  transcription: 'var(--transcription)',
  decision: 'var(--decision)',
  viz: 'var(--viz)',
};

export const KIND_LABEL: Record<CardKind, string> = {
  context: 'Context',
  transcription: 'Said',
  decision: 'Decision',
  viz: 'Insight',
};

/** The agent's wake name (mirrors the backend AGENT_WAKE_NAMES). Typed questions
 *  are auto-prefixed with it so the agent always treats them as addressed. */
export const WAKE_NAME = 'tellmequick';

/** Strip a leading wake-name so a card's prompt shows the clean question. */
export function cleanPrompt(text?: string): string | undefined {
  if (!text) return undefined;
  const stripped = text
    .trim()
    .replace(/^(hey\s+|ok\s+|okay\s+)?(tell me quick|tellmequick)[\s,:.!?-]*/i, '')
    .trim();
  return stripped || text.trim();
}

/** Compact relative time, e.g. "now", "12s", "3m", "1h". */
export function timeAgo(ts: number, now: number): string {
  const s = Math.max(0, Math.round((now - ts) / 1000));
  if (s < 3) return 'now';
  if (s < 60) return `${s}s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.round(m / 60);
  return `${h}h`;
}

/** Demo cards so the feed (and every card type) is visible without a live meeting.
 *  Gated behind NEXT_PUBLIC_DEMO_FEED=1 — never shown in a real session. */
export const SAMPLE_CARDS: AgentCard[] = [
  {
    id: 'sample-context',
    ts: 0,
    kind: 'context',
    query: 'should we cut the events budget?',
    answer:
      'The team already decided in the May review to hold the events budget flat — events drove ~40% of Q2 pipeline, and the Vertex contract carries a 30% cancellation fee.',
    timeTakenMs: 8,
    sources: [
      {
        text: 'Decision (May 1 review): hold the Q3 events budget flat; revisit after the May pipeline review. Owner: Priya.',
        source: 'meeting',
        score: 0.52,
      },
      {
        text: 'Pushing back — events drove about 40% of Q2 pipeline. Cutting 20% risks H2 bookings.',
        source: 'slack',
        score: 0.47,
        url: 'https://acme.slack.com/archives/C0FIN/p1715772600',
      },
      {
        text: 'Vertex MSA: minimum annual spend $1.2M through Q4 2026; 30% cancellation fee on the remaining commitment.',
        source: 'filing',
        score: 0.45,
      },
    ],
  },
  {
    id: 'sample-viz',
    ts: 0,
    kind: 'viz',
    title: 'Pipeline sourced by events vs. other (last 4 quarters)',
    spec: {
      chart: 'bar',
      xKey: 'quarter',
      unit: '$M',
      caption: 'Events drove ~40% of pipeline in Q2.',
      series: [
        { key: 'events', label: 'Events' },
        { key: 'other', label: 'Other' },
      ],
      data: [
        { quarter: 'Q3 25', events: 4.1, other: 7.0 },
        { quarter: 'Q4 25', events: 5.2, other: 7.4 },
        { quarter: 'Q1 26', events: 4.8, other: 8.1 },
        { quarter: 'Q2 26', events: 6.3, other: 9.2 },
      ],
    },
    sources: [{ text: 'Q2 pipeline review deck', source: 'filing' }],
  },
  {
    id: 'sample-transcription',
    ts: 0,
    kind: 'transcription',
    query: 'tellmequick, anything on this?',
    answer:
      "I don't have prior context on the new vendor you just mentioned — nothing in the docs, Slack, or past decisions yet.",
  },
  {
    id: 'sample-decision',
    ts: 0,
    kind: 'decision',
    text: 'Hold the Q3 events budget flat; revisit after the May pipeline review.',
    topic: 'events-budget',
    owner: 'Priya',
  },
];
