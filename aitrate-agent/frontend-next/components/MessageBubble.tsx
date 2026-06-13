'use client';

import { MarkdownRenderer } from './MarkdownRenderer';
import { Citations } from './Citations';
import type { Message } from '@/lib/types';

interface MessageBubbleProps {
  message: Message;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const time = message.timestamp.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
  });

  if (message.role === 'user') {
    return (
      <div className="flex gap-2.5">
        <div className="w-7 h-7 rounded-full bg-surface-secondary text-text-secondary flex items-center justify-center text-xs font-medium flex-shrink-0">
          U
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-xs text-text-secondary mb-1">
            You · {time}
          </div>
          <div className="text-[13px] leading-relaxed whitespace-pre-wrap">
            {message.content}
          </div>
        </div>
      </div>
    );
  }

  if (message.role === 'error') {
    return (
      <div className="flex gap-2.5">
        <div className="w-7 h-7 rounded-full bg-surface-danger text-text-danger flex items-center justify-center text-xs font-medium flex-shrink-0">
          !
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-xs text-text-secondary mb-1">System · {time}</div>
          <div className="text-[13px] leading-relaxed text-text-danger">
            {message.content}
          </div>
        </div>
      </div>
    );
  }

  // Assistant message
  const confClass =
    message.confidence === 'high'
      ? 'bg-surface-success text-text-success'
      : 'bg-surface-warning text-text-warning';
  const confLabel =
    message.confidence === 'high' ? '✓ grounded' : '⚠ abstained';

  return (
    <div className="flex gap-2.5">
      <div className="w-7 h-7 rounded-full bg-accent text-white flex items-center justify-center text-xs font-medium flex-shrink-0">
        ●
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-xs text-text-secondary mb-1 flex items-center gap-2">
          <span>Co-Pilot · {time}</span>
          {message.functionId && (
            <span className="font-mono text-[11px]">{message.functionId}</span>
          )}
          {message.confidence && (
            <span
              className={`text-[11px] px-2 py-0.5 rounded-[10px] ${confClass}`}
            >
              {confLabel}
            </span>
          )}
        </div>
        <MarkdownRenderer content={message.content} />
        {message.citations && <Citations citations={message.citations} />}
      </div>
    </div>
  );
}
