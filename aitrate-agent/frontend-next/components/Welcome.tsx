'use client';

interface WelcomeProps {
  onSuggestion: (text: string) => void;
}

const suggestions = [
  'What does the CVD filter do?',
  'Explain the RSI corridor filter',
  'What are the parameter classes A, B, C?',
  'How does the leverage framework work?',
];

export function Welcome({ onSuggestion }: WelcomeProps) {
  return (
    <div className="flex flex-col items-center justify-center flex-1 gap-4 text-text-secondary">
      <h2 className="text-xl font-medium text-text-primary">aiTrate Co-Pilot</h2>
      <p className="text-[13px] max-w-[400px] text-center">
        Domain-specialised AI agent for your trading strategies. Ask about
        filters, audit backtests, or get parameter recommendations.
      </p>
      <div className="flex flex-wrap gap-2 justify-center mt-2">
        {suggestions.map((s) => (
          <button
            key={s}
            onClick={() => onSuggestion(s)}
            className="text-xs px-3 py-1.5 border border-black/[0.18] rounded-md bg-surface-primary hover:bg-surface-secondary transition-colors cursor-pointer"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
