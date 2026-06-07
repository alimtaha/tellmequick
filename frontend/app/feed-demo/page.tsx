'use client';

import { useEffect, useState } from 'react';
import { CardFeed } from '@/components/app/card-feed';
import { type AgentCard, SAMPLE_CARDS } from '@/components/app/cards/card-types';

/**
 * Dev-only design playground for the meeting card feed. Renders the HUD shell with
 * sample cards (one of each type) so the card designs can be reviewed without a
 * live LiveKit session. Reachable at /feed-demo.
 */
export default function FeedDemoPage() {
  // Populate on mount (client-only) so Date.now() doesn't cause a hydration mismatch.
  const [cards, setCards] = useState<AgentCard[]>([]);
  useEffect(() => {
    setCards(SAMPLE_CARDS.map((c, i) => ({ ...c, ts: Date.now() - i * 45_000 })));
  }, []);

  return (
    <div className="bg-background text-foreground fixed inset-0 z-[100] flex flex-col">
      <header className="border-border/60 flex items-center gap-3 border-b px-6 py-3">
        <span className="flex items-center gap-2">
          <span className="relative flex size-2.5 items-center justify-center">
            <span
              className="absolute inline-flex size-2.5 animate-ping rounded-full opacity-60"
              style={{ background: 'var(--context)' }}
            />
            <span
              className="relative inline-flex size-2 rounded-full"
              style={{ background: 'var(--context)' }}
            />
          </span>
          <span className="font-mono text-xs font-semibold tracking-wider uppercase">
            Listening
          </span>
        </span>
        <span className="grow" />
        <span className="text-muted-foreground text-xs">
          demo feed · say <span className="text-foreground font-medium">“tellmequick”</span> to ask
        </span>
      </header>

      <div className="min-h-0 flex-1">
        <CardFeed cards={cards} className="mx-auto h-full w-full max-w-2xl px-4 py-4" />
      </div>

      <div className="border-border/60 text-muted-foreground border-t px-6 py-4 text-center font-mono text-xs tracking-wider uppercase">
        mic · chat · leave
      </div>
    </div>
  );
}
