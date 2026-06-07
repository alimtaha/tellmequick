'use client';

import React, { useState } from 'react';
import { AnimatePresence, type MotionProps, motion } from 'motion/react';
import { useAgent, useSessionContext, useSessionMessages } from '@livekit/components-react';
import { AgentChatTranscript } from '@/components/agents-ui/agent-chat-transcript';
import {
  AgentControlBar,
  type AgentControlBarControls,
} from '@/components/agents-ui/agent-control-bar';
import { CardFeed } from '@/components/app/card-feed';
import { SAMPLE_CARDS } from '@/components/app/cards/card-types';
import { useAgentCards } from '@/hooks/useAgentCards';
import { cn } from '@/lib/shadcn/utils';

const DEMO_FEED = process.env.NEXT_PUBLIC_DEMO_FEED === '1';

const CHAT_MOTION_PROPS: MotionProps = {
  variants: {
    hidden: { opacity: 0, transition: { ease: 'easeOut', duration: 0.3 } },
    visible: { opacity: 1, transition: { delay: 0.2, ease: 'easeOut', duration: 0.3 } },
  },
  initial: 'hidden',
  animate: 'visible',
  exit: 'hidden',
};

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
 * Feed-dominant "meeting HUD": a slim status header, the live card feed as the
 * hero surface, and a slim control bar. The agent surfaces context cards here
 * while the meeting runs; it speaks only when it interjects or is addressed.
 */
export function AgentSessionView_01({
  supportsChatInput = true,
  supportsVideoInput = true,
  supportsScreenShare = true,
  ref,
  className,
  ...props
}: React.ComponentProps<'section'> & AgentSessionView_01Props) {
  const session = useSessionContext();
  const { messages } = useSessionMessages(session);
  const { state: agentState } = useAgent();
  const [chatOpen, setChatOpen] = useState(false);

  const liveCards = useAgentCards();
  const cards = liveCards.length > 0 ? liveCards : DEMO_FEED ? SAMPLE_CARDS : [];

  const controls: AgentControlBarControls = {
    leave: true,
    microphone: true,
    chat: supportsChatInput,
    camera: supportsVideoInput,
    screenShare: supportsScreenShare,
  };

  const status = stateLabel(agentState);

  return (
    <section
      ref={ref}
      className={cn('bg-background z-10 flex h-full w-full flex-col overflow-hidden', className)}
      {...props}
    >
      {/* Status header */}
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
        <span className="text-muted-foreground hidden text-xs sm:inline">
          Say <span className="text-foreground font-medium">“tellmequick”</span> to ask
        </span>
      </header>

      {/* Hero: the live card feed */}
      <div className="relative min-h-0 flex-1">
        <CardFeed cards={cards} className="mx-auto h-full w-full max-w-2xl px-4 py-4" />

        {/* Optional chat transcript overlay */}
        <AnimatePresence>
          {chatOpen && (
            <motion.div
              {...CHAT_MOTION_PROPS}
              className="bg-background/95 absolute inset-0 z-20 flex flex-col backdrop-blur"
            >
              <AgentChatTranscript
                agentState={agentState}
                messages={messages}
                className="mx-auto w-full max-w-2xl [&_.is-user>div]:rounded-[22px] [&>div>div]:px-4 [&>div>div]:py-4 md:[&>div>div]:px-6"
              />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Control bar */}
      <div className="border-border/60 border-t px-3 py-3 md:px-12">
        <div className="mx-auto max-w-2xl">
          <AgentControlBar
            variant="livekit"
            controls={controls}
            isChatOpen={chatOpen}
            isConnected={session.isConnected}
            onDisconnect={session.end}
            onIsChatOpenChange={setChatOpen}
          />
        </div>
      </div>
    </section>
  );
}
