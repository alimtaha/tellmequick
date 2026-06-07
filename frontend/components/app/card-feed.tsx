'use client';

import * as React from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { cn } from '@/lib/shadcn/utils';
import { AgentCardView } from './cards/agent-card';
import type { AgentCard } from './cards/card-types';

interface CardFeedProps {
  cards: AgentCard[];
  className?: string;
}

/**
 * The hero surface: a live, scrollable feed of context cards, newest at top.
 * New cards animate in (respecting reduced-motion). Shows a quiet listening
 * state when empty.
 */
export function CardFeed({ cards, className }: CardFeedProps) {
  const reduce = useReducedMotion();
  // Tick a clock so relative timestamps stay fresh. Starts at 0 (stable for SSR)
  // and is set on mount to avoid a hydration mismatch from Date.now() at render.
  const [now, setNow] = React.useState(0);
  React.useEffect(() => {
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), 15_000);
    return () => clearInterval(t);
  }, []);

  if (cards.length === 0) {
    return (
      <div
        className={cn('flex h-full flex-col items-center justify-center text-center', className)}
      >
        <div className="relative mb-4 flex size-12 items-center justify-center">
          <span className="bg-context/15 absolute inline-flex size-12 animate-ping rounded-full" />
          <span className="bg-context/30 relative inline-flex size-3 rounded-full" />
        </div>
        <p className="text-foreground text-sm font-medium">Listening…</p>
        <p className="text-muted-foreground mt-1 max-w-xs text-xs">
          Relevant context, decisions, and charts will appear here as the meeting goes. Say
          <span className="text-foreground font-medium"> “tellmequick” </span>
          to ask directly.
        </p>
      </div>
    );
  }

  return (
    <div
      className={cn('flex flex-col gap-3 overflow-y-auto overscroll-contain', className)}
      role="log"
      aria-live="polite"
      aria-label="Meeting context feed"
    >
      <AnimatePresence initial={false}>
        {cards.map((card) => (
          <motion.div
            key={card.id}
            className="min-w-0"
            initial={reduce ? false : { opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduce ? undefined : { opacity: 0 }}
            transition={{ duration: 0.22, ease: 'easeOut' }}
          >
            <AgentCardView card={card} now={now} />
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
