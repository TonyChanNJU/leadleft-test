"use client";

import React, { useState, useEffect, useRef } from "react";
import { Send, FileText, Trash2, AlertCircle, CheckCircle2, Moon, Sun } from "lucide-react";
import { FileUpload } from "@/components/FileUpload";
import { MessageBubble } from "@/components/MessageBubble";
import { ModelSelector } from "@/components/ModelSelector";
import { uploadPdf, getDocuments, deleteDocument, clearAllDocuments, chat, getAvailableModels, DocumentMeta, Citation, AppModel } from "@/lib/api";

interface Message {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  isLoading?: boolean;
}

interface ToastData {
  msg: string;
  type: "error" | "success";
}

export default function Home() {
  const [documents, setDocuments] = useState<DocumentMeta[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [toast, setToast] = useState<ToastData | null>(null);
  const [confirmClearAllOpen, setConfirmClearAllOpen] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{ docId: string; filename: string } | null>(null);
  
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content: "Lumina is ready. Upload PDFs to begin.",
    }
  ]);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  
  const [availableModels, setAvailableModels] = useState<AppModel[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  
  const [activePdf, setActivePdf] = useState<{ doc_id: string; page_num: number } | null>(null);
  const [darkMode, setDarkMode] = useState(false);

  const backendBaseUrl =
    typeof window === "undefined"
      ? "http://localhost:8000"
      : `http://${window.location.hostname}:8000`;

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const showToast = (msg: string, type: "error" | "success") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  };

  const fetchDocuments = async () => {
    const docs = await getDocuments();
    setDocuments(docs);
  };

  const fetchStartupData = async () => {
    try {
      const [docs, models] = await Promise.all([
        getDocuments(),
        getAvailableModels()
      ]);
      setDocuments(docs);
      setAvailableModels(models);
      if (models.length > 0) {
        setSelectedModel(models[0].model_id);
      }
    } catch (err) {
      console.error("Failed to load startup data", err);
    }
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchStartupData();
  }, []);

  useEffect(() => {
    const stored = localStorage.getItem("lumina-theme");
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const isDark = stored === "dark" || (stored !== "light" && prefersDark);
    document.documentElement.classList.toggle("dark", isDark);
    queueMicrotask(() => {
      setDarkMode(isDark);
    });
  }, []);

  const toggleDarkMode = () => {
    const next = !document.documentElement.classList.contains("dark");
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("lumina-theme", next ? "dark" : "light");
    setDarkMode(next);
  };

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleUpload = async (file: File) => {
    setIsUploading(true);
    try {
      const uploadRes = await uploadPdf(file);
      await fetchDocuments();
      setMessages(prev => [...prev, {
        role: "assistant",
        content: `Document payload [${file.name}] ingested successfully. Indexing in progress...`,
      }]);

      showToast("Upload complete. Indexing...", "success");

      // Poll until indexed (background indexing).
      const startedAt = Date.now();
      const timeoutMs = 10 * 60 * 1000; // 10 minutes
      const intervalMs = 1500;
      const poll = async () => {
        while (Date.now() - startedAt < timeoutMs) {
          const docs = await getDocuments();
          setDocuments(docs);
          const doc = docs.find((d) => d.doc_id === uploadRes.doc_id);
          if (doc?.indexed) return true;
          await new Promise((r) => setTimeout(r, intervalMs));
        }
        return false;
      };
      void poll().then((ok) => {
        if (ok) {
          setMessages(prev => [...prev, {
            role: "assistant",
            content: `Indexing completed for [${file.name}]. Ready for queries.`,
          }]);
          showToast("Document indexed", "success");
        } else {
          showToast("Indexing still running. Please wait.", "error");
        }
      });
    } catch (err: unknown) {
      console.error("Upload failed", err);
      const axiosErr = err as { response?: { status?: number } } | undefined;
      if (axiosErr?.response?.status === 409) {
        showToast("Conflict: Document already exists", "error");
      } else {
        showToast("Backend connection failed during upload", "error");
      }
    } finally {
      setIsUploading(false);
    }
  };

  const handleDelete = async (docId: string) => {
    try {
      await deleteDocument(docId);
      await fetchDocuments();
      showToast("Document purged", "success");
    } catch (err) {
      showToast("Purge failed", "error");
      console.error("Delete failed", err);
    }
  };

  const handleClearAll = async () => {
    try {
      await clearAllDocuments();
      await fetchDocuments();
      showToast("Data registry completely wiped", "success");
      setMessages([{
        role: "assistant",
        content: "All documents cleared. Upload PDFs to begin.",
      }]);
    } catch (err) {
      showToast("Global purge failed", "error");
      console.error("Clear all failed", err);
    }
  };

  const handleViewCitation = (doc_id: string, page_num: number) => {
    setActivePdf({ doc_id, page_num });
  };

  const handleSend = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!input.trim() || isTyping) return;

    if (documents.length === 0) {
      showToast("No documents found in registry. Upload first.", "error");
      return;
    }

    const question = input.trim();
    setInput("");
    
    const newMessages: Message[] = [...messages, { role: "user", content: question }];
    setMessages(newMessages);
    setIsTyping(true);
    setMessages([...newMessages, { role: "assistant", content: "Processing...", isLoading: true }]);

    try {
      const docIds = documents.map(d => d.doc_id);
      const res = await chat(question, docIds, selectedModel);
      setMessages([...newMessages, {
        role: "assistant",
        content: res.answer,
        citations: res.citations,
      }]);
    } catch (err: unknown) {
      console.error("Chat failed", err);
      const axiosErr = err as {
        isAxiosError?: boolean;
        message?: string;
        code?: string;
        config?: { url?: string; method?: string; baseURL?: string; timeout?: number };
        response?: { status?: number; headers?: unknown; data?: unknown };
        request?: { readyState?: number; status?: number; responseURL?: string };
      };
      if (axiosErr?.isAxiosError) {
        console.error("AxiosError details", {
          message: axiosErr.message,
          code: axiosErr.code,
          url: axiosErr.config?.url,
          method: axiosErr.config?.method,
          baseURL: axiosErr.config?.baseURL,
          timeout: axiosErr.config?.timeout,
          status: axiosErr.response?.status,
          responseHeaders: axiosErr.response?.headers,
          responseDataType: typeof axiosErr.response?.data,
          requestReadyState: axiosErr.request?.readyState,
          requestStatus: axiosErr.request?.status,
          requestResponseURL: axiosErr.request?.responseURL,
        });
      }
      let errorMsg = "Transmission error connecting to logic engine.";
      const data = (axiosErr?.response as { data?: unknown } | undefined)?.data;
      const detail =
        typeof data === "object" && data !== null && "detail" in data && typeof (data as { detail?: unknown }).detail === "string"
          ? (data as { detail: string }).detail
          : undefined;
      if (detail) {
        errorMsg += "\n\n**SysLog**: " + detail;
      }
      setMessages([...newMessages, {
        role: "assistant",
        content: errorMsg,
      }]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex h-screen overflow-hidden bg-(--bg-main) font-sans text-foreground">
      
      {/* Toast Notification */}
      {toast && (
        <div className="absolute top-6 left-1/2 transform -translate-x-1/2 z-50 animate-fade-in">
          <div className={`flex items-center px-4 py-3 rounded-lg shadow-sm hover:shadow-md border border-slate-100/50 dark:border-slate-800/60 backdrop-blur-sm ${
            toast.type === "error"
              ? "bg-red-50 text-red-800 dark:bg-red-500/10 dark:text-red-200"
              : "bg-slate-50 text-slate-800 dark:bg-slate-900/40 dark:text-slate-100"
          }`}>
            {toast.type === "error" ? (
              <AlertCircle className="w-5 h-5 mr-3" />
            ) : (
              <CheckCircle2 className="w-5 h-5 mr-3" />
            )}
            <span className="font-semibold tracking-wide">{toast.msg}</span>
          </div>
        </div>
      )}

      {/* Confirm Clear All Modal */}
      {confirmClearAllOpen && (
        <div className="absolute inset-0 z-40 flex items-center justify-center p-6">
          <div
            className="absolute inset-0 bg-slate-900/20 dark:bg-black/60 backdrop-blur-sm"
            onClick={() => setConfirmClearAllOpen(false)}
          />
          <div className="relative w-full max-w-lg rounded-2xl border border-slate-100/50 dark:border-slate-800/60 bg-white/90 dark:bg-[#131314]/90 shadow-sm hover:shadow-md backdrop-blur-xl">
            <div className="p-6 border-b border-slate-100/50 dark:border-slate-800/60 flex items-start justify-between">
              <div>
                <div className="text-[10px] font-semibold tracking-widest uppercase text-red-600 dark:text-red-300">Destructive action</div>
                <div className="mt-1 text-lg font-semibold text-slate-900 dark:text-slate-100">Clear all documents?</div>
                <div className="mt-2 text-sm text-slate-700 dark:text-slate-300 leading-relaxed">
                  This will delete all uploaded PDFs and vector indexes. This cannot be undone.
                </div>
              </div>
              <button
                type="button"
                onClick={() => setConfirmClearAllOpen(false)}
                className="text-[10px] uppercase tracking-widest font-semibold text-slate-500 hover:text-slate-900 dark:hover:text-slate-100 transition-colors px-2 py-1 rounded-md hover:bg-slate-50 dark:hover:bg-slate-800/60"
              >
                Close
              </button>
            </div>
            <div className="p-6 flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => setConfirmClearAllOpen(false)}
                className="px-4 py-2 rounded-xl border border-slate-100/50 dark:border-slate-800/60 bg-white/80 dark:bg-slate-950/30 text-slate-900 dark:text-slate-100 font-semibold text-xs uppercase tracking-widest hover:bg-slate-50 dark:hover:bg-slate-900/40 transition-colors shadow-sm hover:shadow-md"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={async () => {
                  setConfirmClearAllOpen(false);
                  await handleClearAll();
                }}
                className="px-4 py-2 rounded-xl border border-red-200 dark:border-red-500/40 bg-red-50 dark:bg-red-500/10 text-red-800 dark:text-red-100 font-semibold text-xs uppercase tracking-widest hover:bg-red-100 dark:hover:bg-red-500/20 transition-colors shadow-sm hover:shadow-md"
              >
                Clear all
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Confirm Delete Document Modal */}
      {confirmDeleteOpen && deleteTarget && (
        <div className="absolute inset-0 z-40 flex items-center justify-center p-6">
          <div
            className="absolute inset-0 bg-slate-900/20 dark:bg-black/60 backdrop-blur-sm"
            onClick={() => setConfirmDeleteOpen(false)}
          />
          <div className="relative w-full max-w-lg rounded-2xl border border-slate-100/50 dark:border-slate-800/60 bg-white/90 dark:bg-[#131314]/90 shadow-sm hover:shadow-md backdrop-blur-xl">
            <div className="p-6 border-b border-slate-100/50 dark:border-slate-800/60 flex items-start justify-between">
              <div>
                <div className="text-[10px] font-semibold tracking-widest uppercase text-red-600 dark:text-red-300">Destructive action</div>
                <div className="mt-1 text-lg font-semibold text-slate-900 dark:text-slate-100">Delete this document?</div>
                <div className="mt-2 text-sm text-slate-700 dark:text-slate-300 leading-relaxed break-all">
                  {deleteTarget.filename}
                </div>
                <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                  This will delete the PDF and its vector index. This cannot be undone.
                </div>
              </div>
              <button
                type="button"
                onClick={() => setConfirmDeleteOpen(false)}
                className="text-[10px] uppercase tracking-widest font-semibold text-slate-500 hover:text-slate-900 dark:hover:text-slate-100 transition-colors px-2 py-1 rounded-md hover:bg-slate-50 dark:hover:bg-slate-800/60"
              >
                Close
              </button>
            </div>
            <div className="p-6 flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => setConfirmDeleteOpen(false)}
                className="px-4 py-2 rounded-xl border border-slate-100/50 dark:border-slate-800/60 bg-white/80 dark:bg-slate-950/30 text-slate-900 dark:text-slate-100 font-semibold text-xs uppercase tracking-widest hover:bg-slate-50 dark:hover:bg-slate-900/40 transition-colors shadow-sm hover:shadow-md"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={async () => {
                  setConfirmDeleteOpen(false);
                  const { docId } = deleteTarget;
                  setDeleteTarget(null);
                  await handleDelete(docId);
                }}
                className="px-4 py-2 rounded-xl border border-red-200 dark:border-red-500/40 bg-red-50 dark:bg-red-500/10 text-red-800 dark:text-red-100 font-semibold text-xs uppercase tracking-widest hover:bg-red-100 dark:hover:bg-red-500/20 transition-colors shadow-sm hover:shadow-md"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Sidebar */}
      <div className="w-80 bg-[#F1F3F4]/80 dark:bg-[#1A1C1E]/70 backdrop-blur-md border-r border-slate-200/40 dark:border-slate-800/60 flex-col shadow-(--shadow-soft) z-10 hidden md:flex">
        <div className="p-7 border-b border-slate-200/40 dark:border-slate-800/60 flex items-center space-x-3">
          <div
            className="p-2 rounded-xl text-white shadow-sm"
            style={{ background: "var(--brand-gradient)" }}
          >
            <svg
              viewBox="0 0 24 24"
              className="h-6 w-6"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              {/* Document frame */}
              <path d="M7 3.5h7l3 3V20a1.5 1.5 0 0 1-1.5 1.5H7A1.5 1.5 0 0 1 5.5 20V5A1.5 1.5 0 0 1 7 3.5Z" />
              <path d="M14 3.5V7h3.5" />
              {/* “scan / insight” lines */}
              <path d="M8.5 11h7" />
              <path d="M8.5 14h5.5" />
              <path d="M8.5 17h6.5" />
              {/* subtle lens dot */}
              <path d="M16.8 13.6a.01.01 0 0 0 0 0" />
            </svg>
          </div>
          <div>
            <h1 className="font-semibold text-xl tracking-tight text-slate-900 dark:text-slate-100">
              Lumina
            </h1>
            <p className="text-[10px] text-slate-500 dark:text-slate-400 font-semibold tracking-widest uppercase mt-0.5">
              Document copilot
            </p>
          </div>
        </div>

        <div className="p-6 shrink-0">
          <FileUpload onUpload={handleUpload} isLoading={isUploading} />
        </div>

        <div className="flex-1 overflow-y-auto px-5 pb-5 custom-scrollbar">
          <div className="mb-4 px-1 flex items-center justify-between">
            <h2 className="text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-widest">
              Data Registry
            </h2>
            <div className="flex items-center space-x-2">
              {documents.length > 0 && (
                <button 
                  onClick={() => setConfirmClearAllOpen(true)} 
                  className="p-1 text-slate-500 hover:text-red-600 hover:bg-slate-50 dark:hover:bg-slate-800/60 rounded transition-colors" 
                  title="Purge all documents"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              )}
              <span className="text-[10px] bg-slate-50 dark:bg-slate-900/40 border border-slate-100/50 dark:border-slate-800/60 text-slate-700 dark:text-slate-200 px-2 py-0.5 rounded-full font-semibold">
                {documents.length}
              </span>
            </div>
          </div>
          
          {documents.length === 0 ? (
            <div className="text-center py-10 text-sm text-slate-500 dark:text-slate-500 space-y-3">
              <FileText className="w-8 h-8 mx-auto opacity-30" />
              <p className="font-semibold tracking-wide text-xs uppercase">No documents yet</p>
            </div>
          ) : (
            <ul className="space-y-3">
              {documents.map((doc) => (
                <li
                  key={doc.doc_id}
                  className="group flex items-center justify-between p-3 bg-white/70 dark:bg-slate-900/20 border border-slate-100/50 dark:border-slate-800/60 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-900/40 transition-all duration-200 shadow-sm hover:shadow-md"
                >
                  <div className="flex items-start space-x-3 overflow-hidden">
                    <FileText className="w-5 h-5 text-slate-500 shrink-0 mt-0.5" />
                    <div className="flex flex-col min-w-0">
                      <span className="text-sm font-semibold text-slate-900 dark:text-slate-100 truncate block" title={doc.filename}>
                        {doc.filename}
                      </span>
                      <span className="text-[10px] text-slate-500 dark:text-slate-400 mt-1 uppercase tracking-wider font-semibold">
                        {doc.total_pages} pages
                        {!doc.indexed && (
                          <span className="ml-2 inline-flex items-center rounded-full border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900/40 px-2 py-0.5 text-[9px] font-semibold tracking-widest text-slate-600 dark:text-slate-300">
                            INDEXING...
                          </span>
                        )}
                      </span>
                    </div>
                  </div>
                  <button 
                    onClick={(e) => {
                      e.stopPropagation();
                      setDeleteTarget({ docId: doc.doc_id, filename: doc.filename });
                      setConfirmDeleteOpen(true);
                    }}
                    className="p-1.5 text-slate-400 hover:text-red-600 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800/60 transition-colors opacity-0 group-hover:opacity-100 focus:opacity-100 focus:outline-none"
                    title="Purge document node"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        
        <div className="p-4 border-t border-slate-100/50 dark:border-slate-800/60 bg-white/80 dark:bg-[#1A1C1E]/70 flex justify-center text-slate-500">
           <span className="text-[10px] uppercase font-semibold tracking-widest text-slate-500 dark:text-slate-400">
             Secure environment
           </span>
        </div>
      </div>

      {/* Split Viewer Container */}
      <div className="flex-1 flex flex-row overflow-hidden relative bg-(--bg-main)">
        
        {/* Main Chat Area */}
        <div className={`flex flex-col relative transition-all duration-300 ${activePdf ? 'w-1/2 border-r border-slate-100/50 dark:border-slate-800/60' : 'w-full'}`}>
          
          {/* Header */}
          <header className="h-16 flex items-center justify-between px-6 bg-white/50 dark:bg-[#1A1C1E]/40 backdrop-blur-md border-b border-slate-200/40 dark:border-slate-800/60 z-10 sticky top-0">
            <div className="md:hidden font-semibold text-lg text-slate-900 dark:text-slate-100">Lumina</div>
            <div className="flex-1" />
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={toggleDarkMode}
                className="flex h-9 w-9 items-center justify-center rounded-xl border border-slate-200/70 bg-white/80 text-slate-600 shadow-(--shadow-soft) transition-all hover:bg-slate-50 dark:border-slate-600/60 dark:bg-slate-800/60 dark:text-slate-200 dark:hover:bg-slate-700/60"
                title={darkMode ? "Switch to light mode" : "Switch to dark mode"}
                aria-label={darkMode ? "Switch to light mode" : "Switch to dark mode"}
              >
                {darkMode ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              </button>
              <ModelSelector
                currentModel={selectedModel}
                onModelChange={setSelectedModel}
                availableModels={availableModels}
                disabled={isTyping}
              />
            </div>
          </header>

          {/* Chat History */}
          <div className="flex-1 overflow-y-auto px-4 py-8 md:px-10 scroll-smooth custom-scrollbar">
            <div className="max-w-4xl mx-auto flex flex-col justify-end">
              {messages.map((msg, idx) => (
                <MessageBubble key={idx} message={msg} onViewCitation={handleViewCitation} />
              ))}
              <div ref={messagesEndRef} />
            </div>
          </div>

          {/* Input Area */}
          <div className="p-5 md:p-10 bg-linear-to-t from-(--bg-main) via-(--bg-main)/90 to-transparent dark:from-(--bg-main) dark:via-(--bg-main)/90">
            <div className="max-w-4xl mx-auto relative px-2">
              <form onSubmit={handleSend} className="relative group">
                <div
                  className="absolute -inset-1 rounded-4xl blur-sm opacity-20 group-hover:opacity-35 transition-opacity duration-300"
                  style={{ background: "var(--brand-gradient)" }}
                />
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={documents.length > 0 ? "Ask about your documents..." : "Upload a PDF to begin..."}
                  disabled={isTyping || documents.length === 0}
                  className="relative w-full pl-6 pr-16 py-5 bg-white/60 dark:bg-[#1A1C1E]/40 backdrop-blur-md border border-slate-200/40 dark:border-slate-800/60 rounded-3xl shadow-[0_2px_8px_rgba(0,0,0,0.04)] focus:outline-none focus:ring-2 focus:ring-blue-400/30 text-foreground placeholder-slate-500 disabled:opacity-60 resize-none h-[76px] transition-all duration-200 leading-relaxed"
                  rows={1}
                />
                <button
                  type="submit"
                  disabled={!input.trim() || isTyping || documents.length === 0}
                  className="absolute right-4 bottom-4 p-2.5 text-white rounded-xl disabled:opacity-40 active:scale-95 transition-all duration-200 flex items-center justify-center shadow-[0_2px_8px_rgba(0,0,0,0.04)] hover:shadow-[0_2px_8px_rgba(0,0,0,0.06)]"
                  style={{ background: "var(--brand-gradient)" }}
                >
                  {isTyping ? <div className="w-5 h-5 border-2 border-slate-950 border-t-transparent rounded-full animate-spin"></div> : <Send className="w-5 h-5 ml-0.5" />}
                </button>
              </form>
              <div className="text-center mt-4">
                <span className="text-[10px] text-slate-500 dark:text-slate-400 font-semibold tracking-widest uppercase">
                  Verify important claims using sources.
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* PDF Viewer Panel */}
        {activePdf && (
           <div className="w-1/2 flex flex-col bg-white/50 dark:bg-[#1A1C1E]/40 backdrop-blur-md relative animate-fade-in z-20">
             <div className="h-16 flex items-center justify-between px-6 bg-white/50 dark:bg-[#1A1C1E]/40 border-b border-slate-200/40 dark:border-slate-800/60 shadow-[0_2px_8px_rgba(0,0,0,0.04)] shrink-0 backdrop-blur-md">
                <div className="flex items-center space-x-2">
                   <div
                     className="w-2.5 h-2.5 rounded-full animate-[lumina-breathe_2.2s_ease-in-out_infinite]"
                     style={{ background: "var(--brand-gradient)" }}
                   />
                   <span className="text-[10px] font-semibold text-slate-600 dark:text-slate-300 uppercase tracking-widest">
                     Sources - Page {activePdf.page_num}
                   </span>
                </div>
                <button 
                  onClick={() => setActivePdf(null)} 
                  className="text-[10px] uppercase tracking-widest font-semibold text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 transition-colors px-3 py-1.5 hover:bg-slate-50 dark:hover:bg-slate-800/60 rounded-md"
                >
                  Close
                </button>
             </div>
             <div className="flex-1 relative w-full overflow-hidden">
               <iframe
                 key={`${activePdf.doc_id}_${activePdf.page_num}`}
                 src={`${backendBaseUrl}/api/documents/${encodeURIComponent(activePdf.doc_id)}/pdf#page=${activePdf.page_num}`}
                 className="absolute inset-0 w-full h-full border-none"
                 title="PDF Source Viewer"
               />
             </div>
           </div>
        )}
      </div>

      <style jsx global>{`
        .custom-scrollbar::-webkit-scrollbar {
          width: 6px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background-color: #334155;
          border-radius: 20px;
        }
      `}</style>
    </div>
  );
}
