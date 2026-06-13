'use client';

export function TopBar() {
  return (
    <div className="bg-[rgba(250,250,247,0.92)] backdrop-blur-[10px] border-b border-black/10 px-6 py-3.5 flex items-center justify-between flex-shrink-0">
      <h1 className="text-sm font-medium text-text-primary">aiTrate Co-Pilot</h1>
      <div className="flex items-center gap-2 text-xs">
        <span className="text-[11px] px-2.5 py-0.5 rounded-[10px] bg-surface-warning text-text-warning font-medium">
          Shadow mode
        </span>
        <span className="text-[11px] px-2.5 py-0.5 rounded-[10px] bg-surface-success text-text-success">
          Connected
        </span>
      </div>
    </div>
  );
}
