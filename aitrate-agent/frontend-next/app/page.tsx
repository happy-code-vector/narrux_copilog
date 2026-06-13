'use client';

import { useState, useCallback } from 'react';
import { Sidebar } from '@/components/Sidebar';
import { TopBar } from '@/components/TopBar';
import { ChatPanel } from '@/components/ChatPanel';
import { SidebarPanel } from '@/components/SidebarPanel';
import type { Message, CitationResponse } from '@/lib/types';

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [functionId, setFunctionId] = useState('F-01');
  const [latestCitations, setLatestCitations] = useState<CitationResponse[]>([]);

  const handleNewMessages = useCallback((newMessages: Message[]) => {
    setMessages((prev) => [...prev, ...newMessages]);
    const assistantMsg = newMessages.find((m) => m.role === 'assistant');
    if (assistantMsg?.citations?.length) {
      setLatestCitations(assistantMsg.citations);
    }
  }, []);

  const handleFunctionChange = useCallback((id: string) => {
    setFunctionId(id);
  }, []);

  return (
    <>
      <Sidebar />
      <main className="flex flex-1 flex-col min-w-0 h-screen">
        <TopBar />
        <div className="flex flex-1 overflow-hidden">
          <ChatPanel
            messages={messages}
            functionId={functionId}
            onFunctionChange={handleFunctionChange}
            onNewMessages={handleNewMessages}
          />
          <SidebarPanel
            functionId={functionId}
            messageCount={messages.length}
            citationCount={messages.reduce(
              (sum, m) => sum + (m.citations?.length ?? 0),
              0
            )}
            citations={latestCitations}
          />
        </div>
      </main>
    </>
  );
}
