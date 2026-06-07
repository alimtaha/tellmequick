import * as React from 'react';
import { AudioLines, BarChart3, FileText, Flag, type LucideIcon } from 'lucide-react';
import { cn } from '@/lib/shadcn/utils';
import { type CardKind, KIND_ACCENT, KIND_LABEL, timeAgo } from './card-types';

const KIND_ICON: Record<CardKind, LucideIcon> = {
  context: FileText,
  transcription: AudioLines,
  decision: Flag,
  viz: BarChart3,
};

interface CardShellProps {
  kind: CardKind;
  ts: number;
  now: number;
  /** Optional content on the right of the header (e.g. timing, topic). */
  headerRight?: React.ReactNode;
  children: React.ReactNode;
}

/**
 * Shared card frame: a colored left rail + a header (icon, type label, timestamp)
 * so every card's kind and recency are instantly legible. Accent comes from the
 * per-kind CSS var (the feed taxonomy).
 */
export function CardShell({ kind, ts, now, headerRight, children }: CardShellProps) {
  const Icon = KIND_ICON[kind];
  const accent = KIND_ACCENT[kind];
  return (
    <article
      className={cn(
        'border-border bg-card text-card-foreground relative overflow-hidden rounded-xl border',
        'border-l-2 pl-4 shadow-sm'
      )}
      style={{ borderLeftColor: accent }}
    >
      {/* faint accent wash */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.06]"
        style={{ background: `linear-gradient(90deg, ${accent}, transparent 40%)` }}
      />
      <div className="relative p-3">
        <header className="mb-2 flex items-center gap-2">
          <Icon className="size-3.5 shrink-0" style={{ color: accent }} aria-hidden />
          <span
            className="font-mono text-[11px] font-semibold tracking-wider uppercase"
            style={{ color: accent }}
          >
            {KIND_LABEL[kind]}
          </span>
          <span className="text-muted-foreground/60 grow" aria-hidden />
          {headerRight}
          <time
            className="text-muted-foreground font-mono text-[11px] tabular-nums"
            dateTime={new Date(ts || now).toISOString()}
            suppressHydrationWarning
          >
            {timeAgo(ts || now, now)}
          </time>
        </header>
        {children}
      </div>
    </article>
  );
}
