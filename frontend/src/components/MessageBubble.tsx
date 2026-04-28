import React, { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ChevronDown, User } from "lucide-react";
import { CitationCard } from "./CitationCard";
import type { Citation } from "../lib/api";

interface Message {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  isLoading?: boolean;
}

interface MessageBubbleProps {
  message: Message;
  onViewCitation?: (doc_id: string, page_num: number) => void;
}

const bubbleClass =
  "bg-[#E9EEF6] text-[#3C4043] shadow-(--shadow-soft) dark:bg-[#2D3036] dark:text-[#E8EAED] dark:shadow-(--shadow-soft)";

const proseClass =
  "prose prose-sm max-w-none prose-p:text-[#3C4043] prose-headings:font-semibold prose-headings:text-[#3C4043] prose-a:text-blue-700 prose-code:text-[#3C4043] dark:prose-invert dark:prose-p:text-[#E8EAED] dark:prose-headings:text-[#E8EAED] dark:prose-a:text-blue-300 dark:prose-code:text-[#E8EAED]";

export const MessageBubble: React.FC<MessageBubbleProps> = ({ message, onViewCitation }) => {
  const isUser = message.role === "user";
  const [sourcesOpen, setSourcesOpen] = useState(true);

  return (
    <div className={`flex w-full mb-6 ${isUser ? "justify-end" : "justify-start"} animate-slide-up`}>
      <div className={`flex max-w-[85%] ${isUser ? "flex-row-reverse" : "flex-row"}`}>
        {/* Avatar — same chrome for Pilot & Lumina */}
        <div className="shrink-0 mt-1">
          <div
            className={`flex items-center justify-center w-8 h-8 rounded-full bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200 shadow-sm ${
              isUser ? "ml-3" : "mr-3"
            }`}
          >
            {isUser ? (
              <User className="w-4 h-4" />
            ) : (
              <div
                className="h-3.5 w-3.5 rounded-full"
                style={{ background: "var(--brand-gradient)" }}
                aria-hidden="true"
              />
            )}
          </div>
        </div>

        {/* Message Content */}
        <div className={`flex flex-col ${isUser ? "items-end" : "items-start"} max-w-full overflow-hidden`}>
          <div className="mb-1 flex items-center space-x-2">
            <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
              {isUser ? "Pilot" : "Lumina"}
            </span>
          </div>

          <div className={`relative rounded-2xl px-5 py-4 leading-relaxed wrap-break-word ${bubbleClass}`}>
            {message.isLoading ? (
              <div className="flex h-6 items-center gap-3 px-1">
                <div
                  className="h-3.5 w-3.5 rounded-full animate-[lumina-breathe_2.2s_ease-in-out_infinite]"
                  style={{ background: "var(--brand-gradient)" }}
                  aria-hidden="true"
                />
                <span className="text-xs font-semibold tracking-wide text-slate-500 dark:text-slate-400">
                  Thinking...
                </span>
              </div>
            ) : (
              <div className={proseClass}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
              </div>
            )}
          </div>

          {/* Citations — grouped card, items more prominent */}
          {!isUser && message.citations && message.citations.length > 0 && (
            <div className="mt-3 w-full rounded-xl border border-slate-200/70 bg-white/70 p-3 shadow-(--shadow-soft) backdrop-blur-md dark:border-slate-600/50 dark:bg-[#25282C]/90">
              <div className="mb-2 flex items-center justify-between gap-2 border-b border-slate-200/60 pb-2 dark:border-slate-600/40">
                <button
                  type="button"
                  onClick={() => setSourcesOpen((v) => !v)}
                  className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-widest text-slate-800 hover:text-slate-900 dark:text-slate-200 dark:hover:text-white"
                  aria-expanded={sourcesOpen}
                >
                  <span>Sources</span>
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                    {message.citations.length}
                  </span>
                  <ChevronDown
                    className={`h-4 w-4 text-slate-500 transition-transform dark:text-slate-400 ${
                      sourcesOpen ? "rotate-180" : "rotate-0"
                    }`}
                    aria-hidden="true"
                  />
                </button>
                <span className="text-[10px] font-medium text-slate-500 dark:text-slate-400">
                  {sourcesOpen ? "Hide" : "Show"}
                </span>
              </div>
              {sourcesOpen && (
                <div className="space-y-1">
                  {message.citations.map((citation, idx) => (
                    <CitationCard key={idx} index={idx + 1} citation={citation} onViewClick={onViewCitation} />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
