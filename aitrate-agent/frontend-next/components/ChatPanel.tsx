'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { MessageBubble } from './MessageBubble';
import { Welcome } from './Welcome';
import { sendChatMessage } from '@/lib/api';
import type { Message } from '@/lib/types';

interface ChatPanelProps {
  messages: Message[];
  functionId: string;
  onFunctionChange: (id: string) => void;
  onNewMessages: (messages: Message[]) => void;
}

const FUNCTIONS = [
  { value: 'F-01', label: 'F-01 Explain' },
  { value: 'F-02', label: 'F-02 Backtest' },
  { value: 'F-03', label: 'F-03 TSI Score' },
  { value: 'F-04', label: 'F-04 Recommend' },
  { value: 'F-05', label: 'F-05 Drift' },
];

function LoadingDots() {
  return (
    <div className="flex gap-2.5 items-center py-3">
      <div className="flex gap-2">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="w-2 h-2 rounded-full bg-accent"
            style={{
              animation: 'bounce 1.4s infinite ease-in-out both',
              animationDelay: `${-0.32 + i * 0.16}s`,
            }}
          />
        ))}
      </div>
    </div>
  );
}

export function ChatPanel({
  messages,
  functionId,
  onFunctionChange,
  onNewMessages,
}: ChatPanelProps) {
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading, scrollToBottom]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || isLoading) return;

    setInput('');
    setIsLoading(true);

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
      timestamp: new Date(),
    };
    onNewMessages([userMsg]);

    try {
      const data = await sendChatMessage(text, functionId);
      const assistantMsg: Message = {
        id: data.response_id,
        role: 'assistant',
        content: data.content,
        timestamp: new Date(),
        functionId: data.function_id,
        citations: data.citations,
        confidence: data.confidence,
      };
      onNewMessages([assistantMsg]);
    } catch (e) {
      const errorMsg: Message = {
        id: crypto.randomUUID(),
        role: 'error',
        content:
          e instanceof Error
            ? e.message
            : 'Cannot connect to API. Is the server running?',
        timestamp: new Date(),
      };
      onNewMessages([errorMsg]);
    } finally {
      setIsLoading(false);
      inputRef.current?.focus();
    }
  }, [input, functionId, isLoading, onNewMessages]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleSuggestion = (text: string) => {
    setInput(text);
    // Trigger send on next tick after state update
    setTimeout(() => {
      const userMsg: Message = {
        id: crypto.randomUUID(),
        role: 'user',
        content: text,
        timestamp: new Date(),
      };
      onNewMessages([userMsg]);
      setInput('');
      setIsLoading(true);

      sendChatMessage(text, functionId)
        .then((data) => {
          const assistantMsg: Message = {
            id: data.response_id,
            role: 'assistant',
            content: data.content,
            timestamp: new Date(),
            functionId: data.function_id,
            citations: data.citations,
            confidence: data.confidence,
          };
          onNewMessages([assistantMsg]);
        })
        .catch((e) => {
          const errorMsg: Message = {
            id: crypto.randomUUID(),
            role: 'error',
            content:
              e instanceof Error
                ? e.message
                : 'Cannot connect to API. Is the server running?',
            timestamp: new Date(),
          };
          onNewMessages([errorMsg]);
        })
        .finally(() => {
          setIsLoading(false);
          inputRef.current?.focus();
        });
    }, 0);
  };

  return (
    <div className="flex-1 flex flex-col min-w-0">
      {/* Chat header */}
      <div className="px-4 py-2.5 border-b border-black/10 flex items-center justify-between flex-shrink-0">
        <div className="text-[13px] font-medium text-text-primary">
          Conversation
        </div>
        <div className="text-[11px] text-text-secondary flex gap-2 items-center">
          <span>
            Session #{Math.floor(Math.random() * 9000 + 1000)}
          </span>
          <span>Analyst</span>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-4">
        {messages.length === 0 && <Welcome onSuggestion={handleSuggestion} />}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {isLoading && <LoadingDots />}

        <div ref={messagesEndRef} />
      </div>

      {/* Input bar */}
      <div className="px-4 py-2.5 border-t border-black/10 flex gap-1.5 items-center flex-shrink-0">
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about a strategy, filter, or parameter..."
          className="flex-1 h-9 border border-black/[0.18] rounded-md px-3 text-[13px] bg-white focus:outline-none focus:border-accent"
          disabled={isLoading}
        />
        <select
          value={functionId}
          onChange={(e) => onFunctionChange(e.target.value)}
          className="h-9 border border-black/[0.18] rounded-md px-2 text-xs bg-white"
        >
          {FUNCTIONS.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </select>
        <button
          onClick={handleSend}
          disabled={isLoading || !input.trim()}
          className="h-9 px-4 bg-accent text-white border-none rounded-md font-medium cursor-pointer hover:bg-[#1568b8] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          Send
        </button>
      </div>
    </div>
  );
}
