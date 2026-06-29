'use client';

import { useState, useEffect } from 'react';
import { fetchKBStats } from '@/lib/api';
import type { CitationResponse, KBStats } from '@/lib/types';

interface SidebarPanelProps {
  functionId: string;
  messageCount: number;
  citationCount: number;
  citations: CitationResponse[];
}

export function SidebarPanel({
  functionId,
  messageCount,
  citationCount,
  citations,
}: SidebarPanelProps) {
  const [kbStats, setKbStats] = useState<KBStats | null>(null);

  useEffect(() => {
    fetchKBStats().then(setKbStats);
  }, []);

  return (
    <div className="w-[320px] flex-shrink-0 border-l border-black/10 overflow-y-auto p-3 flex flex-col gap-3 bg-white">
      {/* Session Info */}
      <Card title="Session Info">
        <Row label="Function" value={functionId} mono />
        <Row label="Messages" value={String(messageCount)} mono />
        <Row label="Citations" value={String(citationCount)} mono />
      </Card>

      {/* Retrieved Sources */}
      {citations.length > 0 && (
        <Card title="Retrieved Sources">
          <div className="text-xs">
            {citations.map((c, i) => (
              <div
                key={i}
                className="py-1 border-b border-black/10 last:border-0"
              >
                <div className="font-medium">{c.citation_handle}</div>
                <div className="text-text-secondary text-[11px]">
                  {c.doc_id} · score: {c.relevance_score?.toFixed(3) ?? '—'}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Knowledge Base */}
      <Card title="Knowledge Base">
        <Row
          label="Documents"
          value={String(kbStats?.active_docs ?? '—')}
          mono
        />
        <Row
          label="Chunks"
          value={kbStats?.total_chunks?.toLocaleString() ?? '—'}
          mono
        />
        <Row label="Vector DB" value="Qdrant" mono />
        <Row label="Embeddings" value="Voyage" mono />
      </Card>

      {/* Governance */}
      <Card title="Governance">
        <div className="text-[11px] text-text-secondary leading-relaxed">
          <b>Citations or silence.</b> Class A never on single backtest. Class B
          requires ≥3 backtests. Class C requires regime label.
        </div>
      </Card>
    </div>
  );
}

function Card({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-white border border-black/10 rounded-lg p-3">
      <div className="text-[13px] font-medium mb-2 text-text-primary">
        {title}
      </div>
      {children}
    </div>
  );
}

function Row({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex justify-between text-xs py-0.5">
      <span className="text-text-secondary">{label}</span>
      <span className={mono ? 'font-mono text-[11px]' : ''}>{value}</span>
    </div>
  );
}
