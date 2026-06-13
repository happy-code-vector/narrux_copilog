'use client';

import type { CitationResponse } from '@/lib/types';

interface CitationsProps {
  citations: CitationResponse[];
}

export function Citations({ citations }: CitationsProps) {
  if (!citations.length) return null;

  return (
    <div className="flex flex-wrap gap-1.5 mt-2 p-2.5 bg-surface-info rounded-md text-[11px] text-text-info">
      <span className="font-medium mr-1">Citations:</span>
      {citations.map((c, i) => (
        <span
          key={i}
          className="bg-white text-text-info text-[10px] px-2.5 py-0.5 rounded-[10px]"
          title={c.doc_id}
        >
          {c.citation_handle}
        </span>
      ))}
    </div>
  );
}
