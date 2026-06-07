import * as React from 'react';
import { cn } from '@/lib/shadcn/utils';
import { CardShell } from './card-shell';
import { type AgentCard, type CardSource, cleanPrompt } from './card-types';
import { VizChart } from './viz-card';

function SourceList({ sources }: { sources: CardSource[] }) {
  if (sources.length === 0) return null;
  return (
    <details className="group mt-2">
      <summary className="text-muted-foreground hover:text-foreground cursor-pointer text-xs transition-colors">
        {sources.length} source{sources.length > 1 ? 's' : ''}
      </summary>
      <ul className="mt-2 space-y-2">
        {sources.map((s, i) => (
          <li key={i} className="border-border/60 border-l pl-2.5 text-sm">
            <p className="text-muted-foreground leading-snug">
              {s.source && (
                <span className="text-foreground mr-1.5 font-mono text-[10px] tracking-wide uppercase">
                  {s.source}
                </span>
              )}
              {s.text}
            </p>
            {typeof s.score === 'number' && (
              <span className="text-muted-foreground/70 font-mono text-[10px] tabular-nums">
                {s.score.toFixed(2)}
              </span>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}

function Chip({ label, value }: { label: string; value: string }) {
  return (
    <span className="bg-muted/60 text-muted-foreground inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px]">
      <span className="opacity-60">{label}</span>
      <span className="text-foreground font-medium">{value}</span>
    </span>
  );
}

/** Renders a single feed card according to its kind. */
export function AgentCardView({ card, now }: { card: AgentCard; now: number }) {
  switch (card.kind) {
    case 'context':
      return (
        <CardShell
          kind="context"
          ts={card.ts}
          now={now}
          prompt={cleanPrompt(card.query)}
          headerRight={
            typeof card.timeTakenMs === 'number' ? (
              <span className="text-muted-foreground/70 font-mono text-[11px] tabular-nums">
                {card.timeTakenMs.toFixed(0)}ms
              </span>
            ) : undefined
          }
        >
          <p className="text-[15px] leading-snug font-medium">{card.answer}</p>
          <SourceList sources={card.sources} />
        </CardShell>
      );

    case 'transcription':
      return (
        <CardShell kind="transcription" ts={card.ts} now={now} prompt={cleanPrompt(card.query)}>
          <p className={cn('text-[15px] leading-snug')}>{card.answer}</p>
        </CardShell>
      );

    case 'decision':
      return (
        <CardShell kind="decision" ts={card.ts} now={now}>
          <p className="text-[15px] leading-snug font-medium">{card.text}</p>
          {(card.topic || card.owner) && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {card.owner && <Chip label="owner" value={card.owner} />}
              {card.topic && <Chip label="topic" value={card.topic} />}
            </div>
          )}
        </CardShell>
      );

    case 'viz':
      return (
        <CardShell kind="viz" ts={card.ts} now={now}>
          <p className="mb-2 text-sm leading-snug font-medium">{card.title}</p>
          <VizChart spec={card.spec} />
          {card.spec.caption && (
            <p className="text-muted-foreground mt-1.5 text-xs">{card.spec.caption}</p>
          )}
          {card.sources && <SourceList sources={card.sources} />}
        </CardShell>
      );
  }
}
