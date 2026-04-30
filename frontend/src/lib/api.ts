import axios from "axios";

const api = axios.create({
  // Same-origin; Next.js dev server rewrites `/api/*` -> `http://localhost:8000/api/*`.
  baseURL: "/api",
});

api.interceptors.response.use(
  (res) => res,
  (error) => {
    // Keep this log compact; detailed logs are printed at call sites (e.g. handleSend).
    // This helps detect cases where DevTools shows 200 but the client rejects the response.
    console.error("API request failed", {
      message: error?.message,
      code: error?.code,
      url: error?.config?.url,
      method: error?.config?.method,
      baseURL: error?.config?.baseURL,
      status: error?.response?.status,
    });
    return Promise.reject(error);
  }
);

export interface DocumentMeta {
  doc_id: string;
  filename: string;
  total_pages: number | null;
  uploaded_at: string;
  indexed: boolean;
  processing_status: "queued" | "parsing" | "ocr" | "indexing" | "ready" | "failed";
  processing_message: string;
  processing_error?: string | null;
  processed_pages: number;
  processing_progress_pct?: number | null;
  current_page?: number | null;
  ocr_candidate_pages_total: number;
  ocr_processed_pages: number;
  ocr_pages: number[];
  low_quality_pages: number[];
  ocr_provider?: string;
}

export interface Citation {
  page_num: number;
  text: string;
  filename: string;
  doc_id: string;
}

export interface ChatResponse {
  answer: string;
  citations: Citation[];
  model_used: string;
}

export interface AppModel {
  model_id: string;
  provider: string;
  display: string;
}

export const getAvailableModels = async (): Promise<AppModel[]> => {
  const response = await api.get("/chat/models");
  return response.data.models;
};

export const uploadPdf = async (file: File): Promise<DocumentMeta> => {
  const formData = new FormData();
  formData.append("file", file);
  
  const response = await api.post("/upload", formData, {
    headers: {
      "Content-Type": "multipart/form-data",
    },
  });
  return response.data;
};

export const getDocuments = async (): Promise<DocumentMeta[]> => {
  const response = await api.get("/documents");
  return response.data.documents;
};

export const getDocument = async (doc_id: string): Promise<DocumentMeta> => {
  const response = await api.get(`/documents/${doc_id}`);
  return response.data;
};

export const deleteDocument = async (doc_id: string): Promise<void> => {
  await api.delete(`/documents/${doc_id}`);
};

export const clearAllDocuments = async (): Promise<void> => {
  await api.delete("/documents");
};

export const chat = async (question: string, doc_ids: string[] = [], model: string = ""): Promise<ChatResponse> => {
  const response = await api.post("/chat", {
    question,
    doc_ids,
    model: model || undefined,
  });
  return response.data;
};
