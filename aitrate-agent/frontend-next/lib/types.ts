export interface CitationResponse {
  doc_id: string;
  citation_handle: string;
  relevance_score: number;
}

export interface ChatResponse {
  response_id: string;
  function_id: string;
  content: string;
  citations: CitationResponse[];
  confidence: 'high' | 'medium' | 'low' | 'abstain';
  validator_results: Record<string, unknown>;
}

export interface KBStats {
  total_chunks: number;
  active_docs: number;
  deprecated_docs: number;
}

export interface HealthResponse {
  status: string;
  kb_stats?: KBStats;
  detail?: string;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'error';
  content: string;
  timestamp: Date;
  functionId?: string;
  citations?: CitationResponse[];
  confidence?: string;
}
