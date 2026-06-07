'use client';

import * as React from 'react';
import { SendHorizontal } from 'lucide-react';
import { useChat } from '@livekit/components-react';
import { WAKE_NAME } from '@/components/app/cards/card-types';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/shadcn/utils';

/**
 * Persistent text box for typing to the agent. Sends via LiveKit chat; auto-prefixes
 * the wake name so a typed question is always treated as "addressed" (the agent
 * answers rather than possibly staying silent like a proactive turn).
 */
export function AskInput({ className }: { className?: string }) {
  const { send } = useChat();
  const [value, setValue] = React.useState('');
  const [sending, setSending] = React.useState(false);
  const disabled = sending || value.trim().length === 0;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = value.trim();
    if (!text) return;
    setSending(true);
    try {
      // Prefix the wake name only if the user didn't already address it.
      const addressed = /\btell\s*me\s*quick\b/i.test(text) ? text : `${WAKE_NAME} ${text}`;
      await send(addressed);
      setValue('');
    } finally {
      setSending(false);
    }
  };

  return (
    <form
      onSubmit={submit}
      className={cn(
        'border-input/60 bg-card focus-within:ring-ring/40 flex items-center gap-2 rounded-full border px-4 py-2 focus-within:ring-2',
        className
      )}
    >
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Ask tellmequick…"
        aria-label="Ask tellmequick a question"
        className="text-foreground placeholder:text-muted-foreground grow bg-transparent text-sm outline-none"
      />
      <Button
        type="submit"
        size="icon"
        disabled={disabled}
        aria-label="Send"
        className="size-8 shrink-0 rounded-full"
      >
        <SendHorizontal className="size-4" />
      </Button>
    </form>
  );
}
