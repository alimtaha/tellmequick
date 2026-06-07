import * as React from 'react';
import type { MossContextEvent } from '@/hooks/useMossContextEvents';
import { cn } from '@/lib/shadcn/utils';

interface MossResultsPanelProps extends React.HTMLAttributes<HTMLDivElement> {
  events: MossContextEvent[];
  hidden?: boolean;
}

export function MossResultsPanel({
  events,
  hidden = false,
  className,
  ...props
}: MossResultsPanelProps) {
  if (hidden || events.length === 0) {
    return null;
  }

  return (
    <div className={cn('space-y-3', className)} {...props}>
      <h3 className="text-muted-foreground text-sm font-medium tracking-wide uppercase">
        Meeting Context
      </h3>
      <div className="space-y-2">
        {events.map(({ id, query, answer, matches, timeTakenMs }) => (
          <div
            key={id}
            className="border-border bg-card text-card-foreground space-y-2 rounded-lg border p-3 shadow-sm"
          >
            {/* The synthesized result is the headline; the query is a subtle label. */}
            {answer ? (
              <p className="text-sm leading-snug font-medium">{answer}</p>
            ) : (
              <p className="text-sm leading-snug font-medium">{query}</p>
            )}

            <details className="group">
              <summary className="text-muted-foreground cursor-pointer text-xs">
                {answer ? `Sources (${matches.length})` : 'Matches'}
                {typeof timeTakenMs === 'number' && (
                  <span className="ml-2">{timeTakenMs.toFixed(0)} ms</span>
                )}
              </summary>
              <ol className="text-muted-foreground mt-2 space-y-2 text-sm">
                {matches.length === 0 ? (
                  <li className="italic">No matching context found.</li>
                ) : (
                  matches.map((match, index) => {
                    const source =
                      match.metadata && typeof match.metadata === 'object'
                        ? (match.metadata as Record<string, unknown>).source
                        : undefined;
                    return (
                      <li key={`${id}-${index}`} className="space-y-1">
                        <p className="leading-snug">
                          {typeof source === 'string' && (
                            <span className="text-foreground mr-1 font-medium">
                              [{source}]
                            </span>
                          )}
                          {match.text}
                        </p>
                        {typeof match.score === 'number' && (
                          <p className="text-muted-foreground text-xs">
                            Relevance: {match.score.toFixed(2)}
                          </p>
                        )}
                      </li>
                    );
                  })
                )}
              </ol>
            </details>
          </div>
        ))}
      </div>
    </div>
  );
}
