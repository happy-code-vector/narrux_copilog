'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { MessageBubble } from './MessageBubble';
import { Welcome } from './Welcome';
import { sendChatMessage, uploadBacktest, interpretBacktest } from '@/lib/api';
import type { Message, BacktestResult } from '@/lib/types';

function randomId(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

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

function formatBacktestResult(result: BacktestResult): string {
  const { summary, tsi, robustness, drift, trades_parsed } = result;
  const gradeEmoji: Record<string, string> = {
    S: '🟢', A: '🔵', B: '🟡', C: '🟠', D: '🔴',
  };

  let md = `## ${gradeEmoji[tsi.grade] ?? '⚪'} TSI Grade: ${tsi.grade} (${tsi.final_tsi.toFixed(2)})\n\n`;
  md += `**Trades parsed:** ${trades_parsed}\n\n`;

  // ── Headline: Trustworthy / Flagged ──
  const headline = robustness?.overall_robust ? '✅ **Trustworthy**' : '⚠️ **Flagged**';
  md += `### ${headline}\n\n`;

  // ── Summary ──
  md += `### Summary\n\n`;
  md += `| Metric | Value |\n|---|---|\n`;
  md += `| Total Trades | ${summary.total_trades} |\n`;
  md += `| Win Rate | ${(summary.win_rate * 100).toFixed(2)}% |\n`;
  md += `| Profit Factor | ${summary.profit_factor.toFixed(3)} |\n`;
  md += `| Net P&L | ${summary.net_pnl_pct.toFixed(2)}% (${summary.net_pnl.toFixed(2)} USDT) |\n`;
  md += `| Max Drawdown | ${summary.max_drawdown_pct.toFixed(2)}% |\n`;
  md += `| Sharpe Ratio | ${summary.sharpe_ratio.toFixed(3)} |\n`;
  md += `| Capital Basis | ${summary.capital_basis.toLocaleString()} USDT |\n`;
  md += `| Stop-Loss Count | ${summary.stop_loss_count} (${(summary.stop_loss_ratio * 100).toFixed(2)}%) |\n`;
  md += `| Execution Mode | ${summary.execution_mode} |\n`;

  // ── Execution Flags ──
  const execFlags: string[] = [];
  if (summary.calc_on_order_fills) {
    execFlags.push('⚠️ `calc_on_order_fills` is TRUE (must be false for live parity)');
  }
  if (summary.process_orders_on_close) {
    execFlags.push('⚠️ `process_orders_on_close` is TRUE (confirm close-action live parity)');
  }
  if (execFlags.length > 0) {
    md += `\n### ⚠️ Execution Flags\n\n`;
    execFlags.forEach((f) => {
      md += `- ${f}\n`;
    });
  }

  // ── TSI Details ──
  md += `\n### TSI Details\n\n`;
  md += `| Metric | Value |\n|---|---|\n`;
  md += `| Stability | ${tsi.stability.toFixed(3)} |\n`;
  md += `| Leverage Cap | ${tsi.leverage_cap.toFixed(1)}x |\n`;
  md += `| Catastrophic Floor | ${tsi.catastrophic_floor ? 'Yes ⚠️' : 'No'} |\n`;

  // ── DQ Triggers ──
  if (tsi.dq_triggers.length > 0) {
    md += `\n### ⚠️ DQ Triggers\n\n`;
    tsi.dq_triggers.forEach((t) => {
      md += `- ${t}\n`;
    });
  }

  // ── Period Metrics ──
  if (tsi.period_metrics.length > 0) {
    md += `\n### Period Metrics\n\n`;
    md += `| Period | Trades | WR% | PF | MDD% | Composite | Flag |\n|---|---|---|---|---|---|---|\n`;
    tsi.period_metrics.forEach((pm) => {
      const flag = pm.insufficient_sample ? '⚠️ low n' : '';
      md += `| ${pm.period} | ${pm.n} | ${(pm.win_rate * 100).toFixed(2)}% | ${pm.profit_factor.toFixed(3)} | ${pm.mdd_pct.toFixed(2)} | ${pm.composite.toFixed(2)} | ${flag} |\n`;
    });
  }

  // ── Robustness (§5) ──
  if (robustness) {
    md += `\n### Robustness\n\n`;

    // DSR
    md += `**Deflated Sharpe Ratio (DSR)**\n\n`;
    md += `| Metric | Value |\n|---|---|\n`;
    md += `| Raw Sharpe | ${robustness.raw_sharpe.toFixed(3)} |\n`;
    md += `| DSR | ${robustness.dsr.toFixed(3)} |\n`;
    md += `| Inflation | ${robustness.dsr_inflation_pct.toFixed(2)}% |\n`;
    if (robustness.dsr_inflation_pct > 50) {
      md += `\n> ⚠️ High multiple-testing inflation — raw Sharpe is unreliable.\n`;
    }

    // Worst window
    const ww = robustness.worst_window;
    md += `\n**Worst-Window Analysis**\n\n`;
    md += `| Metric | Value |\n|---|---|\n`;
    md += `| Window Size | ${ww.window_size} trades |\n`;
    md += `| Worst Composite | ${ww.worst_composite.toFixed(2)} |\n`;
    md += `| Full-Sample Composite | ${ww.full_sample_composite.toFixed(2)} |\n`;
    md += `| Drop | ${ww.drop_points.toFixed(2)} points |\n`;
    md += `| Windows Tested | ${ww.n_windows_tested} |\n`;
    if (ww.drop_points > 20) {
      md += `\n> ⚠️ Severe worst-window drop — strategy edge may be fragile.\n`;
    }

    // Fragile trade
    const fragileItems = robustness.fragile_trade.filter((f) => f.fragile);
    if (fragileItems.length > 0) {
      md += `\n**⚠️ Fragile Trade Dependency**\n\n`;
      fragileItems.forEach((f) => {
        md += `- Removing top ${f.k} trades drops TSI by **${f.tsi_drop.toFixed(2)}** points (${f.tsi_full.toFixed(2)} → ${f.tsi_without.toFixed(2)})\n`;
      });
    }

    // TSI vs P&L cross-check
    const cc = robustness.tsi_pnl_crosscheck;
    md += `\n**TSI vs P&L Cross-Check**\n\n`;
    md += `- TSI trend: **${cc.tsi_trend}** | P&L trend: **${cc.pnl_trend}**\n`;
    if (cc.artifact_flag) {
      md += `- ⚠️ **Re-adjustment artifact detected** — ${cc.note}\n`;
    } else {
      md += `- ✅ ${cc.note}\n`;
    }
  }

  // ── Exit Quality / Drift (§3.3) ──
  if (drift) {
    md += `\n### Exit Quality\n\n`;
    md += `| Metric | Value |\n|---|---|\n`;
    md += `| Avg MFE Capture | ${drift.avg_exit_quality.toFixed(2)}% |\n`;
    md += `| Exits Flagged | ${drift.exits_flagged} / ${drift.total_exits} |\n`;
    md += `| Drift Estimate | ${(drift.drift_estimate_pct * 100).toFixed(2)}% |\n`;
    md += `| Bar Magnifier Baseline | ${(drift.baseline_pct * 100).toFixed(2)}% |\n`;
    if (drift.above_baseline) {
      md += `\n> ⚠️ Estimated drift exceeds Bar Magnifier baseline.\n`;
    }

    if (drift.worst_exits.length > 0) {
      md += `\n**Worst Exits**\n\n`;
      md += `| # | Date | Side | P&L | MFE | Capture% | Issue |\n|---|---|---|---|---|---|---|\n`;
      drift.worst_exits.forEach((we) => {
        const date = new Date(we.close_time).toLocaleDateString();
        md += `| ${we.trade_index} | ${date} | ${we.side} | ${we.net_pnl.toFixed(2)} | ${we.mfe.toFixed(2)} | ${we.mfe_capture_pct.toFixed(0)}% | ${we.issue} |\n`;
      });
    }
  }

  // ── SL ratio warning ──
  if (summary.stop_loss_ratio > 0.4) {
    md += `\n> ⚠️ **Stop-loss ratio > 40%** — review stop placement.\n`;
  }

  return md;
}

/**
 * Parse strategy ID and version from backtest filename.
 *
 * Expected patterns:
 *   NARRUX_Alpha_Unified_v15.9_WH_BYBIT_...xlsx → { strategy: "alpha", version: "v15.9" }
 *   alpha_v15_8_backtest.xlsx                     → { strategy: "alpha", version: "v15.8" }
 *   master_v14_3.xlsx                             → { strategy: "master", version: "v14.3" }
 *   nrx_v1.xlsx                                   → { strategy: "nrx", version: "v1" }
 *   alpha_backtest.xlsx                           → { strategy: "alpha", version: null }
 *   random.xlsx                                   → { strategy: "unknown", version: null }
 */
function parseStrategyFromFilename(filename: string): {
  strategy: string;
  version: string | null;
} {
  const name = filename
    .replace('.xlsx', '')
    .replace('_backtest', '');

  // Known strategy names (order matters — check longer names first)
  const KNOWN_STRATEGIES = ['sentinel', 'master', 'alpha', 'nrx'];

  // Try to find a known strategy name anywhere in the filename
  // This handles "NARRUX_Alpha_...", "alpha_...", "Master_...", etc.
  const nameLower = name.toLowerCase();
  let strategy: string | null = null;
  for (const s of KNOWN_STRATEGIES) {
    // Check if the strategy name appears as a word boundary in the filename
    const idx = nameLower.indexOf(s);
    if (idx !== -1) {
      // Verify it's at a word boundary (start of string or after _/-)
      if (idx === 0 || nameLower[idx - 1] === '_' || nameLower[idx - 1] === '-') {
        strategy = s;
        break;
      }
    }
  }

  // Extract version: look for v{digits} pattern anywhere in the name
  // Matches: v15, v15.8, v15.9.1, v15_8, v15_9_1
  const versionMatch = name.match(/v(\d+(?:[._]\d+){0,3})/i);
  let version: string | null = null;
  if (versionMatch) {
    version = 'v' + versionMatch[1].replace(/_/g, '.');
  }

  if (strategy) {
    return { strategy, version };
  }

  // Fallback: extract first word as strategy
  const fallback = name.match(/^([a-zA-Z]+)/);
  return {
    strategy: fallback ? fallback[1].toLowerCase() : 'unknown',
    version,
  };
}

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
  const [sessionId, setSessionId] = useState('------');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setSessionId(String(Math.floor(Math.random() * 9000 + 1000)));
  }, []);

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
      id: randomId(),
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
        id: randomId(),
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

  const handleFileUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file || isLoading) return;

      // Reset the input so the same file can be re-selected
      e.target.value = '';

      setIsLoading(true);

      const userMsg: Message = {
        id: randomId(),
        role: 'user',
        content: `📊 Backtest upload: **${file.name}**`,
        timestamp: new Date(),
        functionId: 'F-02',
      };
      onNewMessages([userMsg]);

      try {
        // Step 1: Run deterministic tools (fast)
        const result = await uploadBacktest(file);

        // Show data tables immediately
        const dataMsg: Message = {
          id: randomId(),
          role: 'assistant',
          content: formatBacktestResult(result),
          timestamp: new Date(),
          functionId: 'F-02',
          confidence: 'high',
        };
        onNewMessages([dataMsg]);

        // Step 2: Run LLM interpretation (slower, adds narrative + suggestions)
        try {
          const { strategy, version } = parseStrategyFromFilename(file.name);
          const interp = await interpretBacktest(result, strategy, version);

          const interpretMsg: Message = {
            id: randomId(),
            role: 'assistant',
            content: `## 🧠 AI Interpretation\n\n${interp.interpretation}`,
            timestamp: new Date(),
            functionId: 'F-02',
            confidence: 'high',
          };
          onNewMessages([interpretMsg]);
        } catch (interpErr) {
          // Interpretation failure is non-fatal — data tables already shown
          console.warn('LLM interpretation failed:', interpErr);
        }
      } catch (err) {
        const errorMsg: Message = {
          id: randomId(),
          role: 'error',
          content:
            err instanceof Error
              ? err.message
              : 'Failed to upload backtest file.',
          timestamp: new Date(),
        };
        onNewMessages([errorMsg]);
      } finally {
        setIsLoading(false);
      }
    },
    [isLoading, onNewMessages],
  );

  const handleSuggestion = (text: string) => {
    setInput(text);
    // Trigger send on next tick after state update
    setTimeout(() => {
      const userMsg: Message = {
        id: randomId(),
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
            id: randomId(),
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
            Session #{sessionId}
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
        {functionId === 'F-02' && (
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx"
              onChange={handleFileUpload}
              className="hidden"
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={isLoading}
              title="Upload backtest xlsx"
              className="h-9 px-3 border border-black/[0.18] rounded-md text-[13px] bg-white cursor-pointer hover:bg-surface-secondary disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5"
            >
              <span>📎</span>
              <span className="hidden sm:inline">Upload</span>
            </button>
          </>
        )}
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
