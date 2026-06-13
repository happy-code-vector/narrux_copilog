'use client';

export function Sidebar() {
  return (
    <aside className="w-[220px] flex-shrink-0 bg-nav text-[#e8e6e0] py-[18px] h-screen overflow-y-auto">
      <div className="text-[16px] font-medium px-[18px] pb-4 border-b border-white/[0.08] tracking-wide">
        aiTRATE.
        <small className="block text-[11px] text-[#888780] font-normal mt-0.5">
          Co-Pilot v1.0
        </small>
      </div>
      <div className="pt-3 pb-1">
        <div className="text-[10px] text-[#888780] tracking-widest px-[18px] py-1">
          AI AGENT
        </div>
        <a
          href="#"
          className="flex items-center justify-between px-[18px] py-[7px] text-[13px] text-[#87b7eb] bg-accent/10 border-l-2 border-accent no-underline"
        >
          Co-Pilot Chat
        </a>
        <a
          href="#"
          className="flex items-center justify-between px-[18px] py-[7px] text-[13px] text-[#c8c6c0] border-l-2 border-transparent no-underline hover:bg-white/[0.04] hover:text-white transition-colors"
        >
          KB Stats
        </a>
        <a
          href="#"
          className="flex items-center justify-between px-[18px] py-[7px] text-[13px] text-[#c8c6c0] border-l-2 border-transparent no-underline hover:bg-white/[0.04] hover:text-white transition-colors"
        >
          Audit Log
        </a>
      </div>
    </aside>
  );
}
