'use client';

import React from 'react';
import { PhoneOff } from 'lucide-react';
import { useAgent, useRoomContext, useSessionContext } from '@livekit/components-react';
import {
  AgentControlBar,
  type AgentControlBarControls,
} from '@/components/agents-ui/agent-control-bar';
import { AskInput } from '@/components/app/ask-input';
import { CardFeed } from '@/components/app/card-feed';
import { SAMPLE_CARDS } from '@/components/app/cards/card-types';
import { Button } from '@/components/ui/button';
import { useAgentCards } from '@/hooks/useAgentCards';
import { cn } from '@/lib/shadcn/utils';

const DEMO_FEED = process.env.NEXT_PUBLIC_DEMO_FEED === '1';

interface AgentStateLabel {
  label: string;
  color: string;
  pulse: boolean;
}

function stateLabel(state: string | undefined): AgentStateLabel {
  switch (state) {
    case 'speaking':
      return { label: 'Speaking', color: 'var(--transcription)', pulse: true };
    case 'thinking':
      return { label: 'Thinking', color: 'var(--viz)', pulse: true };
    case 'listening':
      return { label: 'Listening', color: 'var(--context)', pulse: true };
    case 'initializing':
      return { label: 'Connecting', color: 'var(--muted-foreground)', pulse: false };
    default:
      return { label: 'Idle', color: 'var(--muted-foreground)', pulse: false };
  }
}

export interface AgentSessionView_01Props {
  preConnectMessage?: string;
  supportsChatInput?: boolean;
  supportsVideoInput?: boolean;
  supportsScreenShare?: boolean;
  isPreConnectBufferEnabled?: boolean;
  className?: string;
}

/**
 * Feed-dominant "meeting HUD". Header shows agent state + an explicit End-meeting
 * button. The card feed is the hero. The footer is how you talk to the agent: a
 * persistent "Ask tellmequick…" text box plus the mic toggle. The agent surfaces
 * cards as the meeting runs and speaks only when it interjects or is addressed.
 */
export function AgentSessionView_01({
  supportsChatInput = true,
  ref,
  className,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  supportsVideoInput,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  supportsScreenShare,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  isPreConnectBufferEnabled,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  preConnectMessage,
  ...props
}: React.ComponentProps<'section'> & AgentSessionView_01Props) {
  const session = useSessionContext();
  const { state: agentState } = useAgent();
  const room = useRoomContext();

  // Enable the mic on join so the agent actually hears the meeting (it's a
  // listening copilot). Prompts for the browser mic grant on first join; the user
  // can mute anytime via the footer toggle. Runs once when the room is live.
  const micPrimed = React.useRef(false);
  React.useEffect(() => {
    if (!room || micPrimed.current) return;
    if (room.state !== 'connected') return;
    micPrimed.current = true;
    room.localParticipant
      .setMicrophoneEnabled(true)
      .catch((e) => console.warn('tellmequick: could not enable microphone on join', e));
  }, [room, room?.state]);

  const liveCards = useAgentCards();
  const cards = liveCards.length > 0 ? liveCards : DEMO_FEED ? SAMPLE_CARDS : [];

  // The footer mic toggle only — typing is the AskInput; ending is the header button.
  const micOnly: AgentControlBarControls = {
    leave: false,
    microphone: true,
    chat: false,
    camera: false,
    screenShare: false,
  };

  const status = stateLabel(agentState);

  return (
    <section
      ref={ref}
      className={cn('bg-background z-10 flex h-full w-full flex-col overflow-hidden', className)}
      {...props}
    >
      {/* Status header + end meeting */}
      <header className="border-border/60 flex items-center gap-3 border-b px-4 py-3 md:px-6">
        <span className="flex items-center gap-2">
          <span className="relative flex size-2.5 items-center justify-center">
            {status.pulse && (
              <span
                className="absolute inline-flex size-2.5 animate-ping rounded-full opacity-60"
                style={{ background: status.color }}
              />
            )}
            <span
              className="relative inline-flex size-2 rounded-full"
              style={{ background: status.color }}
            />
          </span>
          <span className="font-mono text-xs font-semibold tracking-wider uppercase">
            {status.label}
          </span>
        </span>
        <span className="grow" />
        <Button
          variant="outline"
          size="sm"
          onClick={() => session.end()}
          className="text-destructive hover:text-destructive gap-1.5"
        >
          <PhoneOff className="size-3.5" />
          End meeting
        </Button>
      </header>

      {/* Hero: the live card feed */}
      <div className="relative min-h-0 flex-1">
        <CardFeed cards={cards} className="mx-auto h-full w-full max-w-2xl px-4 py-4" />
      </div>

      {/* Footer: talk to the agent — type or use the mic */}
      <div className="border-border/60 border-t px-3 py-3 md:px-6">
        <div className="mx-auto flex max-w-2xl items-center gap-2">
          {supportsChatInput && <AskInput className="grow" />}
          <AgentControlBar
            variant="livekit"
            controls={micOnly}
            isChatOpen={false}
            isConnected={session.isConnected}
            onDisconnect={session.end}
            onIsChatOpenChange={() => {}}
            className="shrink-0"
          />
        </div>
        <p className="text-muted-foreground mx-auto mt-2 max-w-2xl text-center text-[11px]">
          Type above, or just say <span className="text-foreground font-medium">“tellmequick”</span>{' '}
          in the meeting to ask out loud.
        </p>
      </div>
    </section>
  );
}
