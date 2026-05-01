# Lumina - Document QA Chatbot

**Languages:** English | [简体中文](README.zh-CN.md)

A production-ready chatbot that allows users to upload PDF documents and ask questions about their content. It uses Retrieval-Augmented Generation (RAG) to ensure answers are grounded in the uploaded documents rather than relying on prior knowledge.

> GitHub renders `README.md` by default. Use the link above to open the Chinese README (`README.zh-CN.md`).

## Quick Start

### 1. Configure Environment Variables
Copy the template and add your API keys:
```bash
cp .env.example .env
```
Edit `.env` to add at least one LLM API key (e.g., `OPENAI_API_KEY`) and an embedding provider key (e.g., `SILICONFLOW_API_KEY`).

#### LLM model availability (UI)

The frontend model dropdown is populated dynamically from `GET /api/chat/models` based on which API keys are present in your `.env`:

- **OpenAI**: set `OPENAI_API_KEY`
- **Anthropic (Claude)**: set `ANTHROPIC_API_KEY`
- **Google (Gemini)**: set `GOOGLE_API_KEY`
- **DeepSeek**: set `DEEPSEEK_API_KEY`

If a provider key is **not** set, models from that provider will **not** appear in the UI.

### 2. Run the Application
The project includes a unified Makefile. The command below will install dependencies (first run) and start both backend and frontend servers:
```bash
make run
```
Then navigate to [http://localhost:3000](http://localhost:3000) in your browser.

#### 2.1 (Optional) Local embedding (BGE-M3) mode

We support running embeddings locally via HuggingFace models (`EMBEDDING_PROVIDER=local`). This typically requires a one-time model download and may consume significant RAM/CPU.

In our testing, the **cloud embedding provider is usually faster** and is recommended as the default unless you specifically need offline/local execution.

Recommended (Makefile):

```bash
make install
make run-backend-local-embed
make run-frontend
```

Notes:
- The Makefile uses a Python venv at `backend/.venv` to avoid macOS permission issues with global/user site-packages.
- For local embedding, we redirect caches to workspace-writable directories under `data/cache/` (HuggingFace + LlamaIndex caches).
- For testing, prefer a PDF with good text extractability such as `腾讯2025年度报告.pdf`.

#### 2.2 (Optional) OCR fallback

The parser always records page-level extraction diagnostics. OCR fallback is disabled by default and can be enabled for low-quality pages only:

```env
OCR_PROVIDER=paddle
OCR_DPI=120
OCR_DETECTION_MODEL=PP-OCRv5_mobile_det
OCR_RECOGNITION_MODEL=PP-OCRv5_mobile_rec
```

Install OCR dependencies into the same backend venv before enabling this mode:

```bash
make install-ocr
```

To verify the real OCR path against the Meituan broken-font sample:

```bash
make test-ocr
```

To run the backend with OCR enabled and Paddle models cached under `data/cache/paddlex`:

```bash
make run-backend-ocr
```

Local CPU validation on `美团2024年度报告.pdf` used the default PP-OCRv5 mobile models at 120 DPI. On the first 10 pages, the integrated parser path averaged about 6.2 seconds/page with roughly 2.7 GB peak RSS. Full-document OCR for mostly broken-font PDFs can still take tens of minutes, so this mode is best treated as a quality fallback rather than the default path.

## Demo (Tencent 2025 annual report)

Use the provided PDF `腾讯2025年度报告.pdf` at the repo root and try questions from the challenge doc, for example:

- After uploading, wait for processing to complete. The UI may show `PARSING`, `OCR`, and `INDEXING` before the document becomes queryable.
- Fact: “腾讯2025年的总收入是多少？” / “Who is the CEO of the company?”
- Summary: “总结一下主要业务板块。”
- Numeric reasoning: “How much did net profit grow from 2024 to 2025?”

You should see **citations with page numbers**, and you can use the **PDF preview** to verify sources.

## Tests

Run:

```bash
make test
```

Notes:
- The real e2e test (`backend/tests/test_e2e_real_pdf.py`) needs `腾讯2025年度报告.pdf` plus valid `.env` keys.
- Parser diagnostics use `美团2024年度报告.pdf` as a real broken font-map sample when the file is present.
- Contract tests do not require external API keys.

## Retrieval Strategy

Our RAG pipeline is built tightly around LlamaIndex and is designed to handle challenging documents like Chinese financial reports:
1. **Document Parsing**: We use a layered approach. `pdfplumber` detects and extracts tables into Markdown format, while `PyMuPDF` extracts the remaining text, preserving reading order and handling Chinese multi-column text. Each page is diagnosed for extraction quality; low-quality pages can optionally use PaddleOCR fallback.
2. **Chunking**: Extracted text is broken into semantic chunks using LlamaIndex's `SentenceSplitter` (chunk size: 512, overlap: 128). Tables are also indexed as whole Markdown blocks to avoid header/value separation.
3. **Embedding**: We use BAAI's `BGE-M3` model (via SiliconFlow API), which is state-of-the-art for multilingual/Chinese retrieval.
4. **Retrieval**: Vector embeddings are saved to a persistent embedded `ChromaDB` database. We retrieve `top-k=15` chunks using cosine similarity to improve recall on large reports.
5. **Generation**: The retrieved chunks are formatted with their source page number and filename, fed into the user-selected LLM, and prompt constraints heavily enforce grounded citations. The UI sources list is aligned to page numbers explicitly cited in the answer when present; otherwise it falls back to a small top-N list.

## Trade-offs and Future Improvements

* **LLM Adapter vs LiteLLM**: To prevent supply chain attacks (specifically the recent LiteLLM malware incident), we built a custom lightweight adapter unifying OpenAI, Anthropic, Google Gemini, and DeepSeek. With more time, we would implement full streaming support end-to-end to improve perceived latency.
* **Multi-LLM support**: We support multiple LLM providers to match reviewer/user preferences and to compare answer quality across models during evaluation. In a commercial setting, the UI model selector can be hidden and the system can route to the best cost/performance model by default.
* **Cloud embedding + local embedding**: Cloud embeddings are sufficient for a fast first implementation. We still support local embeddings to improve determinism (can run without an external embedding service), and to enable future A/B comparisons and routing to the best embedding approach over time.
* **Edge cases (from challenge doc)**: The challenge mentions “edge cases” for testing but doesn’t enumerate them. Next, we will add targeted test cases based on a clarified edge-case checklist (OCR-only pages, broken `ToUnicode`, extreme multi-column layouts, large tables, mixed language pages, empty/duplicate uploads, etc.) to prevent regressions.
* **PDF preview for source verification**: We added a PDF preview panel to make citations easy to verify. For document Q&A products, “traceability” is a core UX requirement; preview reduces user trust friction and helps users judge answers against the original file.
* **Single-User Persistence**: The documents are persistently stored on disk (`/data`), but it assumes a single-user workflow. A full system would introduce multi-tenant isolation, SQLite tracking for users/sessions, and role-based access.
* **Vector Store**: `ChromaDB` is great for rapid local development but lacks scalability. Switching to `Qdrant` or `Milvus` in a Docker container would be preferred for high throughput.
* **Docker Composition**: We used `make run` for speed and simplicity. If given more time, a `docker-compose.yml` defining the NextJS node frontend, FastAPI backend, and Vector DB image separately would form a true robust deployment strategy.
* **Reranking**: For massive documents, adding a BGE-Reranker model as a post-processing step would significantly boost recall accuracy at the expense of a slightly longer retrieval delay.
* **"图文版" PDFs / Font mapping failures**: Some PDFs render fine visually but extract poorly (e.g., only symbols or `(cid:xxxx)` placeholders) due to missing/incorrect `ToUnicode` maps, subset CID fonts, or text being embedded as images/vectors. A real-world example is the Meituan 2024 Annual Report, whose `MHeiHK` CID fonts cause both PyMuPDF and pdfminer.six to produce garbled Chinese text while numbers remain readable.
  Current progress: the parser now records per-page diagnostics (text length, CJK ratio, symbol noise, table coverage, image density, font names), supports a default-off PaddleOCR fallback for pages detected as low quality, and exposes staged frontend processing states so users can see `PARSING`, `OCR`, and `INDEXING` separately.
  Current progress: local CPU validation uses PP-OCRv5 mobile detection/recognition models at 120 DPI by default for a better speed/quality balance; the first 10 Meituan pages averaged about 6.2 seconds/page.
  ~~Next steps: add stage-specific progress percentages for `PARSING` and `OCR`, then refactor indexing into batchable progress-aware writes so `INDEXING` can report real progress too.~~ Completed on 2026-05-01.
  ~~Next steps: that indexing refactor is expected to help both cloud and local embedding modes mainly through better throughput control, lower peak resource pressure, and easier retry/recovery behavior. It should improve stability and performance more than retrieval accuracy; retrieval quality should stay roughly the same unless chunking, metadata, or embedding models also change.~~ Completed on 2026-05-01.
  ~~Next steps: the trade-off is that batches cannot be made arbitrarily small just to get prettier percentages. Very small batches would raise network round-trip overhead for cloud embeddings and can also hurt throughput for local embeddings, so indexing progress should be designed together with batch-size tuning and resumable writes rather than layered on top as a UI-only feature.~~ Completed on 2026-05-01.
  ~~Next steps: move document processing from in-process background tasks to a persistent job model, checkpoint page-level OCR outputs, and resume unfinished indexing batches after restarts so interrupted jobs can continue instead of restarting from scratch.~~ Completed on 2026-05-01.
  Current progress: Phase 1 is now in place with a SQLite-backed job shell. Uploads create durable processing jobs, document-stage progress is mirrored into the job store, and backend startup requeues unfinished jobs instead of forgetting them after a restart.
  Current progress: Phase 2 is now in place for parsing/OCR. The parser writes per-page checkpoints under `data/jobs/<doc_id>/pages`, reuses completed native page outputs on rerun, and skips OCR pages that were already finished before an interruption.
  Current progress: Phase 3 is now in place for indexing progress. The indexer keeps the existing text/table node semantics, assigns stable node ids, writes vectors in explicit batches, and exposes real `INDEXING` percentages from durable node/batch counters instead of relying on terminal-only embedding logs.
  Current progress: Phase 4 is now in place for recovery control. Jobs carry lease owners and heartbeats, startup reclaims orphaned running jobs, a background monitor reclaims stale leases, and indexing resumes from the last fully completed batch while rerunning only the unfinished batch with idempotent node-id-based writes.
  Implementation plan: see [Persistent Jobs and Indexing Plan](spec/persistent_jobs_and_indexing_plan.md).

## Development: keep Cursor rules in sync

This repo treats `spec/agent_rules.md` as the single source of truth. The root `AGENTS.md` is the Codex entry point, and `.cursorrules` plus `.agents/workflows/agent_rules.md` must remain consistent with the canonical rules.

To enforce this locally:

```bash
pip install pre-commit
pre-commit install
```

Manual check:

```bash
python3 scripts/check_agent_rules_sync.py
```
