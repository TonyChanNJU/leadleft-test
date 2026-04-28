import React from "react";
import { Eye } from "lucide-react";
import type { Citation } from "../lib/api";

interface CitationCardProps {
  citation: Citation;
  index: number;
  onViewClick?: (doc_id: string, page_num: number) => void;
}

export const CitationCard: React.FC<CitationCardProps> = ({ citation, index, onViewClick }) => {
  return (
    <div
      className="group relative flex cursor-pointer flex-col overflow-hidden rounded-lg border border-slate-200/80 bg-[#F4F6F8] px-3.5 py-3 text-[12px] shadow-[0_2px_8px_rgba(0,0,0,0.06)] ring-1 ring-slate-900/4 transition-all hover:border-slate-300/90 hover:shadow-[0_4px_14px_rgba(0,0,0,0.08)] hover:ring-slate-900/6 dark:border-slate-600/60 dark:bg-[#32353A] dark:ring-white/6 dark:hover:border-slate-500/70 dark:hover:shadow-[0_4px_16px_rgba(0,0,0,0.45)]"
      onClick={() => onViewClick && onViewClick(citation.doc_id, citation.page_num)}
    >
      <div
        className="absolute left-0 top-2 bottom-2 w-[3px] rounded-full opacity-90"
        style={{ background: "var(--brand-gradient)" }}
        aria-hidden="true"
      />
      <div className="mt-0.5 flex items-start justify-between gap-3 pl-2.5">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="shrink-0 text-[10px] font-semibold uppercase tracking-widest text-slate-600 dark:text-slate-300">
            Source {index}
          </span>
          <span className="shrink-0 rounded-full border border-slate-300/70 bg-white px-2.5 py-0.5 text-xs font-semibold text-slate-700 shadow-sm dark:border-slate-500/60 dark:bg-slate-800/80 dark:text-slate-100">
            P.{citation.page_num}
          </span>
        </div>
        <button
          type="button"
          className="shrink-0 rounded-md p-1 text-slate-500 transition-colors hover:bg-white/80 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-slate-700/60 dark:hover:text-slate-100"
          title="View source"
          onClick={(e) => {
            e.stopPropagation();
            onViewClick?.(citation.doc_id, citation.page_num);
          }}
        >
          <Eye className="h-4 w-4" />
        </button>
      </div>
      <div className="mt-2 line-clamp-3 pl-2.5 leading-relaxed text-[#3C4043] dark:text-slate-200">
        {citation.text}
      </div>
      <div className="mt-2 truncate pl-2.5 text-[10px] font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {citation.filename}
      </div>
    </div>
  );
};
