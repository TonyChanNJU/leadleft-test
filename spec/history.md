# DocChat Development History

## Overview
This document serves as an ongoing log of development activities, milestones achieved, and issues resolved during the lifecycle of the DocChat project.

---

## [Phase 1: Initial Backend Initialization]
- **Milestone:** M1 & M2
- **Activities:**
  - Initialized Python backend with FastAPI and `requirements.txt`.
  - Configured LlamaIndex alongside PyMuPDF and pdfplumber in `app/services/pdf_parser.py` for advanced PDF text block and table extraction.
  - Implemented the embedding interface with BGE-M3 (ChromaDB persistence) defaulting to SiliconFlow.
  - Added REST endpoints for `/upload` and `/documents`.

## [Phase 2: RAG Query Engine and LLM Adapter]
- **Milestone:** M3
- **Activities:**
  - Built a custom Multi-LLM provider adapter (`app/services/llm_provider.py`) substituting LiteLLM due to supply chain vulnerabilities.
  - Implemented citation tracking inside the querying engine, mapping response segments to exact page numbers.
  - Added the `/chat` endpoint for downstream access to the QA engine.

## [Phase 3: Frontend Development]
- **Milestone:** M4
- **Activities:**
  - Set up Next.js frontend with Tailwind CSS integrations.
  - Developed unified React Components: `FileUpload`, `CitationCard`, `MessageBubble`, and `ModelSelector`.
  - Stitched the components together in a clean single-page chat interface that interacts identically with the local FastAPI backend.

## [Phase 4: Persistence and Testing]
- **Milestone:** M5 & M6
- **Activities:**
  - Standardized JSON persistence mapping `doc_id` to file metadata mimicking simple database states (M5).
  - Wrote initial unit tests for PDF parser edges and API endpoints, properly injecting `PYTHONPATH`.
  - Performed fully loaded E2E validation script asserting the SiliconFlow extraction and DeepSeek interactions.
  - Created initial unified `README.md` and `.cursorrules` enforcement pipelines.

## [Phase 5: Bug Fixes and UI Polish]
- **Milestone:** Addressing immediate feedback after E2E tests
- **Activities:**
  - Refined UI styling (expanding text regions, adding richer contrast and box-shadows to improve legibility).
  - Remedied absolute path logic defaults in automatic Agent rule enforcement files.
  - Implemented PDF upload deduplication in the FastAPI backend based on pre-existing filenames.
  - Repaired underlying 500 Internal Server errors resulting from un-restarted NextJS or FastAPI process scopes after `.env` modifications.
  - **NEW (Phase 5.1):** Discovered `python-dotenv` was resolving the `.env` file within the `backend/` directory during `make run`. Fixed `app/config.py` to point absolute upstream correctly.
  - **NEW (Phase 5.1):** Transformed entire frontend aesthetic to Dark glassmorphism ("Neon Tech" styling) using slate, cyan, and deep shadows, as per user requests.
  - **NEW (Phase 5.1):** Replaced hard-coded JS `alert()` logic with modern toast components directly inside `page.tsx`.
  - **NEW (Phase 5.1):** Implemented completely new logic for `DELETE /documents` on the backend which clears Python Dict registers, ChromaDB, and `data/uploads/` arrays recursively. Added an overarching `Trash` button on the frontend for global wipes.

## [Maintenance: Cursor Agent Rules Compatibility]
- **Milestone:** Agent workflow polish
- **Activities:**
  - Updated `.agents/workflows/agent_rules.md` to remove the non-Cursor-specific `view_file` tool requirement and clarify using Cursor's file read tool instead, while keeping the same enforcement intent (development rules → `spec/project.md` → append to `spec/history.md`).

## [Maintenance: PDF Source Preview + Citation UX Fixes]
- **Milestone:** Improve source verification workflow
- **Activities:**
  - Fixed `GET /documents/{doc_id}/pdf` to serve PDFs with `Content-Disposition: inline` (RFC 5987 UTF-8 filename) so the right-side iframe preview renders instead of downloading.
  - Normalized citation filenames in the QA engine by mapping `doc_id` → registry filename, avoiding hash-prefixed disk basenames in answers and citation cards.
  - Updated the frontend PDF viewer header text to avoid mojibake caused by special glyphs in some environments.
  - Added an in-process cache for embedding models (`cloud` + `local`) to avoid re-instantiating heavy embedding providers on every query, reducing latency and preventing intermittent reloads/crashes under repeated questions.
  - Added structured LLM call logging (per-provider request_id + duration_ms + success/failure with traceback) in `app/services/llm_provider.py` to diagnose intermittent upstream model/API failures without leaking secrets.
  - Hardened frontend↔backend connectivity by allowing both `localhost` and `127.0.0.1` origins in FastAPI CORS, and by making the frontend API baseURL follow the current page hostname to reduce Axios "Network Error" cases caused by origin mismatch.
  - Added end-to-end request observability: backend middleware logs per-request `request_id` + duration and returns `X-Request-Id`; frontend logs expanded Axios error diagnostics to distinguish true network failures vs client-side response read/parse issues.
  - Documented the observed browser-side CORS/extension interaction in `README.md` and outlined a follow-up plan to move local traffic to a same-origin proxy (Next.js rewrite/API route) to eliminate cross-origin variability.
  - Implemented the same-origin proxy: Next.js rewrites `/api/*` → `http://localhost:8000/api/*`, updated frontend API baseURL and PDF iframe to use `/api/...` so the browser no longer performs cross-origin requests during local development.
  - Replaced the iframe-based PDF preview with a PDF.js (react-pdf) canvas renderer to avoid Chrome native PDF viewer edge cases where the PDF bytes are shown as text ("raw bytes" garbling) in embedded contexts.
  - Restored an iframe-based preview while eliminating raw-bytes rendering by pointing the iframe at a dedicated same-origin PDF.js viewer route (`/pdf-frame`) that loads the PDF from `/api/documents/{doc_id}/pdf` and supports page navigation.
  - Reverted to pure iframe PDF preview and hardened PDF response headers (`inline` + `filename`/`filename*` + `X-Content-Type-Options: nosniff`) to reduce cases where browsers render PDF bytes as plain text.
  - Temporarily disabled the Next.js same-origin `/api/*` rewrite proxy and reverted frontend API/PDF requests to direct backend URLs while testing whether the proxy contributes to iframe PDF garbling.
  - Confirmed the proxy affects Chrome’s embedded PDF behavior; restored the Next.js `/api/*` rewrite for JSON/XHR stability while keeping the PDF iframe on a direct backend URL (bypassing the rewrite) to prevent raw-bytes garbling.
  - Replaced the native `window.confirm` prompt for the sidebar “Purge all documents” action with a styled in-app confirmation modal consistent with the existing UI.
  - Fixed re-upload indexing after a global purge by resetting in-process Chroma/embedding caches during `DELETE /documents` and improving upload indexing error logging; this prevents `data/chroma/` remaining empty with `indexed=false` after clearing everything.
  - Validated local embedding mode end-to-end using a project venv (`backend/.venv`) and `EMBEDDING_PROVIDER=local`, with cache directories redirected to workspace-writable paths (`LLAMA_INDEX_CACHE_DIR`, `HF_HOME`/`TRANSFORMERS_CACHE`) to avoid macOS permission issues. Confirmed Chroma persistence is created and documents index successfully under local embeddings.
  - Updated `Makefile` to use the repository venv by default (`backend/.venv`) and added a `run-backend-local-embed` target. Updated both `README.md` and `README.zh-CN.md` with instructions for running local embeddings and recommended testing with `腾讯2025年度报告.pdf`.
  - Improved local-embedding UX by warming up the embedding model on server startup (background) and moving indexing to an asynchronous background task after upload; frontend now shows an `INDEXING…` badge and polls the registry until `indexed=true` without requiring a manual refresh.
  - Fixed mojibake in the indexing UI by replacing the special ellipsis glyph with ASCII (`...`), aligned upload messaging with background indexing state, and replaced the native confirm prompt for single-document delete with the same styled in-app confirmation modal pattern.
  - Removed the Axios/CORS troubleshooting section from both READMEs after the networking approach stabilized.
  - Smoothed onboarding by making `make run` depend on `make install`, so Quick Start can stay as a single command while still using the repo venv (`backend/.venv`) and installing dependencies on first run.

## [UI Refresh: Lumina (Gemini-inspired) Redesign]
- **Milestone:** Brand + UI overhaul
- **Activities:**
  - Rebranded the UI copy to **Lumina** (assistant) and **Pilot** (user), removing legacy “DocChat / AI Node / Operator” wording across the frontend.
  - Implemented the new visual baseline: white background in light mode and graphite `#131314` in dark mode, plus a global `--brand-gradient` CSS variable.
  - Refactored chat message bubbles: Pilot uses `#F0F4F9` (no border, `rounded-2xl`), Lumina uses a transparent bubble with a subtle gradient accent; thinking state now uses a pulsing gradient dot.
  - Updated citation/source UI: page numbers are now compact pill tags (`bg-blue-50 text-blue-600 px-2 py-0.5 rounded-full text-xs`) and citation cards adopt the light border/shadow style.
  - Refreshed sidebar document registry list to use `hover:bg-slate-50`, `rounded-lg`, `border-slate-100/50`, and minimal `shadow-sm` → `hover:shadow-md` interactions; aligned FileUpload/ModelSelector and confirmation modals to the same visual language.

## [UI Tuning: Soft Gemini (Eye Comfort)]
- **Milestone:** Softer palette + glassmorphism spacing
- **Activities:**
  - Shifted the global background to off-white `#F8F9FA` (dark: `#1A1C1E`) and reduced body text contrast to `#3C4043` for lower reading strain.
  - Updated Tailwind-facing CSS variables: `--bg-main`, `--card-border`, `--shadow-soft`, and a lower-saturation `--brand-gradient` (`135deg` with alpha).
  - Adjusted message bubbles: Pilot uses `#E9EEF6`; Lumina stays transparent with an ultra-thin border only on hover (`#E1E3E1`).
  - Slowed the thinking indicator to a gentler “breathing” animation (opacity 0.3 ↔ 0.7) via `@keyframes lumina-breathe`.
  - Softened source tags to a muted slate pill (`bg-slate-100 text-slate-600 border border-slate-200/50`) and applied glassmorphism (`backdrop-blur-md`) + very light shadows across key containers.

## [UI: Lumina bubble parity + Sources emphasis + manual dark mode]
- **Milestone:** Chat consistency + theme control
- **Activities:**
  - Unified assistant (Lumina) message bubbles with Pilot: same rounded bubble fill (`#E9EEF6` light / elevated slate in dark), typography, and shadow; aligned avatar chrome (Pilot keeps `User` icon, Lumina uses a small brand-gradient dot in the same circular frame).
  - Made the Sources block more scannable: grouped citations in a bordered glass card with a header + count, and restyled each citation row with a stronger surface, subtle ring, and a left brand-gradient accent bar.
  - Added manual dark mode: `html.dark` class strategy with `@custom-variant dark` in `globals.css`, Tailwind `darkMode: "class"`, persisted preference in `localStorage` (`lumina-theme`), and a header toggle (moon/sun). Dark theme tokens live under `.dark { ... }` so CSS variables track the selected mode instead of system media alone.

## [UI: Brand icon redesign + collapsible sources]
- **Milestone:** Brand relevance + source usability
- **Activities:**
  - Replaced the Lumina brand mark icon from a generic “CPU/electronics” glyph to a document-centric inline SVG while keeping the same brand-gradient background container.
  - Added a per-answer Sources collapse/expand control (chevron toggle) so citation lists can be hidden when not needed, while preserving the overall Soft Gemini visual style and dark mode compatibility.

## [Repo hygiene: ignore local venv]
- **Milestone:** Prevent committing local env artifacts
- **Activities:**
  - Updated `.gitignore` to ignore common Python virtual environment folders (`.venv/`, `venv/`, `backend/.venv/`).

## [Backend: DeepSeek V4 model IDs]
- **Milestone:** Dual-stack DeepSeek compatibility
- **Activities:**
  - Extended the backend model registry to include `deepseek-v4-pro` and `deepseek-v4-flash` while keeping `deepseek-chat` / `deepseek-reasoner` for backward compatibility (DeepSeek remains OpenAI-compatible via `base_url=https://api.deepseek.com/v1`).

## [Frontend: Brand favicon]
- **Milestone:** Browser tab branding
- **Activities:**
  - Added a Lumina favicon (`frontend/src/app/icon.svg`) so the browser tab uses the project’s brand mark.

## [Docs: LLM keys drive model selector]
- **Milestone:** Clarify model availability in UI
- **Activities:**
  - Updated `README.md` and `README.zh-CN.md` to document that the frontend model dropdown is populated dynamically based on which LLM provider API keys are set (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `DEEPSEEK_API_KEY`).

## [Maintenance: Testing hardening (contract + real e2e)]
- **Milestone:** Align tests with challenge requirements
- **Activities:**
  - Refactored upload registry persistence to compute `registry.json` path dynamically from `settings.upload_dir`, enabling temp-dir isolation in tests; added a test-only registry reload hook in `backend/app/routers/upload.py`.
  - Added `backend/tests/conftest.py` fixtures to isolate `upload_dir/chroma_dir` under `tmp_path`, reset in-process Chroma/embedding caches between tests, and provide a polling helper to wait for `indexed=true`.
  - Expanded API contract tests in `backend/tests/test_api.py` to cover upload validation (non-PDF, wrong content-type, empty file, duplicate filename), documents metadata + PDF headers, and chat input validation without requiring external API keys.
  - Added real integration test `backend/tests/test_e2e_real_pdf.py` (marked `e2e`) to upload `腾讯2025年度报告.pdf`, wait for background indexing, and assert the chat response includes structured citations (page number + excerpt + doc_id/filename) when API keys are present.
  - Hardened the legacy script `backend/tests/run_e2e.py` to run from any working directory, validate required env keys, and wait for async indexing completion before asking the model.
  - Registered the `e2e` pytest marker in `backend/pytest.ini` to avoid unknown-mark warnings.
  - Aligned end-to-end test prompts to the challenge document’s example questions (fact + summary + numeric reasoning), kept a negative-query regression, and added a parser smoke test on `腾讯2025年度报告.pdf` to assert non-garbled Chinese extraction and basic table signal.

## [Docs: README reviewer-first polish]
- **Milestone:** Make README easier for reviewers
- **Activities:**
  - Reorganized `README.md` and `README.zh-CN.md` to front-load challenge alignment, demo questions, and test instructions; moved “keep Cursor rules in sync” to the end.
  - Positioned the optional local embedding mode as a sub-section under Quick Start (Run the Application), and documented the trade-off of supporting both cloud and local embeddings for determinism and future A/B selection.
  - Added an explicit “edge cases” future-improvement note to READMEs, acknowledging the challenge doc mentions edge cases but does not enumerate them, and committing to add tests accordingly.

## [Repo hygiene: expand .gitignore]
- **Milestone:** Prevent accidental commits
- **Activities:**
  - Expanded `.gitignore` to include common IDE metadata (`.vscode/`, `.idea/`), coverage outputs (`.coverage`, `htmlcov/`, `coverage.xml`), logs (`*.log`), tooling caches (`.mypy_cache/`, `.ruff_cache/`), and temp files (`*.tmp`, `*.swp`).

## [Legal: add MIT license]
- **Milestone:** Open-source licensing
- **Activities:**
  - Added `LICENSE` with MIT License text (Copyright (c) 2026 Lawrence).

## [Docs: README language navigation]
- **Milestone:** Easier navigation between English and Chinese READMEs on GitHub
- **Activities:**
  - Added prominent bidirectional links between `README.md` and `README.zh-CN.md` (GitHub renders `README.md` by default; users switch via markdown links).

## [DevX: make run stability]
- **Milestone:** Improve local one-command startup
- **Activities:**
  - Updated `Makefile` `run` target to wait for `GET /api/health` before starting the frontend, and to skip starting a second backend if port 8000 is already healthy (prevents proxy `ECONNREFUSED/ETIMEDOUT` and `Address already in use` from duplicate starts).

## [DevX: revert make run changes]
- **Milestone:** Restore original Makefile behavior
- **Activities:**
  - Reverted the `Makefile` `run` target back to the original “start backend in background, then start frontend” behavior, since the root cause of backend startup failures was an x86_64 vs arm64 environment mismatch (Warp under Rosetta) rather than startup ordering.

## [RAG: improve revenue retrieval]
- **Milestone:** Increase recall for fact questions (tables + revenue)
- **Activities:**
  - Indexed detected PDF tables as whole markdown blocks (in addition to sentence-split page text) to reduce table header/value separation during retrieval.
  - Increased default `retrieval_top_k` to 15 to improve recall for key financial facts (e.g. total revenue) in large reports.

## [RAG: citation alignment + source hygiene]
- **Milestone:** Reduce noisy sources while keeping answers verifiable
- **Activities:**
  - Added a citation-selection layer that aligns the returned `citations` list to **page numbers explicitly referenced in the answer body** (e.g. `Page 6` / `第6页` / `(Source: ..., Page 6)`), preventing mismatches between the answer text and the UI sources list.
  - Kept a fallback policy: when the answer does not explicitly cite page numbers, return a small top-N citation list (bounded by `max_citations`) to avoid source spam.
  - Prevented leaking internal `[Source N]` identifiers into answer bodies by tightening prompt constraints and adding a post-processing rewrite from `Source N, Page P` → `(Source: filename, Page P)`.
  - Tuned answer-context vs citations candidate set: LLM context remains capped (`llm_context_top_k`) for noise control, while citation candidates can use the wider retrieval set to satisfy answer-cited pages.
  - Documented and categorized “font mapping failures” as a future improvement case (e.g., Meituan annual report with CID fonts causing garbled CJK extraction while numeric extraction remains readable).

## [DevX: clarify agent rule entry points]
- **Milestone:** Reduce confusion between Codex entry files and project development rules
- **Activities:**
  - Renamed the project-specific development guide to `spec/development_rules.md` so it no longer conflicts with Codex's root `AGENTS.md` convention.
  - Added root `AGENTS.md` as the Codex entry point, pointing agents to `spec/agent_rules.md` and structural-change guidance in `spec/project.md`.
  - Updated `spec/agent_rules.md`, `.cursorrules`, `.agents/workflows/agent_rules.md`, and `scripts/check_agent_rules_sync.py` to reference `spec/development_rules.md`.
  - Documented the relationship between `AGENTS.md`, `spec/agent_rules.md`, `.cursorrules`, and `.agents/workflows/agent_rules.md` in both READMEs.

## [PDF parsing: low-quality extraction diagnostics + OCR fallback]
- **Milestone:** Harden parsing for image-based PDFs and broken font maps
- **Activities:**
  - Added page-level diagnostics for native PDF extraction quality, including text length, CJK ratio, CID/replacement/private-use glyph signals, symbol noise, image density, table coverage, and font names.
  - Added `OCR_PROVIDER` / `OCR_DPI` settings and a default-off PaddleOCR fallback path that only runs on pages flagged as low quality.
  - Exposed `low_quality_pages` and `ocr_pages` in upload metadata/response and indexed extraction metadata with each page document.
  - Documented the optional OCR fallback in English and Chinese READMEs and added unit tests for diagnostics, PaddleOCR result parsing, OCR fallback behavior, and quality summary properties.

## [PDF parsing: Meituan font-map regression coverage]
- **Milestone:** Validate OCR fallback detection against a real broken CJK PDF
- **Activities:**
  - Added `美团2024年度报告.pdf` parser tests that assert the real report is flagged as a low-quality font mapping sample with replacement-character and CJK mapping failure signals.
  - Added a mocked PaddleOCR fallback test using the Meituan report to verify that enabling `OCR_PROVIDER=paddle` routes low-quality pages through the OCR path without requiring PaddleOCR in default test runs.
  - Documented the Meituan PDF as an optional parser diagnostic sample in both READMEs.

## [PDF parsing: real PaddleOCR validation + performance tuning]
- **Milestone:** Verify OCR fallback against the Meituan broken-font sample
- **Activities:**
  - Created a temporary Python 3.10 OCR validation environment and installed PaddleOCR/PaddlePaddle to run real OCR against `美团2024年度报告.pdf`.
  - Verified real OCR output on low-quality Meituan pages, recovering readable Chinese text and financial table values where native extraction produced replacement-character noise.
  - Cached the PaddleOCR instance and disabled optional document orientation/unwarping/textline orientation models to avoid repeated per-page initialization.
  - Switched OCR defaults to PP-OCRv5 mobile detection/recognition models and 120 DPI after benchmarking server vs mobile models on local CPU.
  - Measured the integrated parser path on the first 10 Meituan pages: ~6.2 seconds/page average with ~2.7GB peak RSS, confirming full-document OCR should remain an opt-in fallback.

## [DevX: integrate OCR dependencies into project environment]
- **Milestone:** Make real OCR reproducible in the backend venv
- **Activities:**
  - Verified `paddlepaddle`/`paddleocr` install and run successfully in the existing Python 3.13 `backend/.venv`, so a separate Python 3.10 OCR environment is no longer needed.
  - Added `backend/requirements-ocr.txt` for heavy optional OCR dependencies while keeping the default install lightweight.
  - Added `make install-ocr` to install PaddleOCR dependencies into the same backend venv used by the application.
  - Added `make test-ocr` and `backend/tests/run_ocr_smoke.py` to run a real OCR smoke test against `美团2024年度报告.pdf`.
  - Added `make run-backend-ocr` and project-local Paddle model caching under `data/cache/paddlex`.
  - Updated both READMEs to document the project-native OCR installation and verification flow.

## [UX: staged processing status for OCR fallback]
- **Milestone:** Make long-running OCR waits visible and cheaper to poll
- **Activities:**
  - Moved PDF parsing out of the synchronous upload request and into the existing background pipeline so upload returns quickly while parsing, OCR fallback, and indexing continue asynchronously.
  - Added document processing states (`queued`, `parsing`, `ocr`, `indexing`, `ready`, `failed`) plus progress metadata to the document registry and `/api/documents` responses.
  - Added parser progress callbacks so low-quality pages can flip the frontend into an explicit OCR state before indexing starts.
  - Switched the frontend from fixed-interval full-list polling to per-document adaptive polling with slower intervals during OCR-heavy phases.
  - Updated the document list and assistant status messages so users can see parsing, OCR, indexing, and failure transitions directly in the UI.

## [Docs: OCR progress + resumability roadmap]
- **Milestone:** Clarify what is done versus what remains
- **Activities:**
  - Updated the English and Chinese READMEs so the demo flow reflects the new staged processing UI (`PARSING`, `OCR`, `INDEXING`) instead of the old indexing-only wait.
  - Expanded the broken-font / OCR fallback trade-off section to distinguish current progress from next steps.
  - Documented the near-term plan to add explicit progress percentages for `PARSING` and `OCR`.
  - Documented the longer-term resumability direction: persistent job state, page-level OCR checkpoints, and resumable indexing batches after server restarts.

## [UX: parsing + OCR percentages]
- **Milestone:** Make staged progress more concrete
- **Activities:**
  - Split PDF processing into a native parsing pass followed by a targeted OCR pass over low-quality pages so `PARSING` and `OCR` progress can each report real percentages.
  - Added OCR candidate-count metadata and stage-specific progress percentages to document status responses for frontend rendering.
  - Updated the frontend status badge to display `PARSING xx%` and `OCR xx%` instead of only page counters.
  - Expanded the README trade-off note to clarify that future batch-aware indexing progress should mainly improve performance and recoverability for both cloud and local embedding modes, rather than retrieval accuracy by itself.
  - Added the missing README caveat that overly small indexing batches would increase cloud embedding round-trip overhead and can also reduce local embedding throughput.
  - Added `spec/persistent_jobs_and_indexing_plan.md` and linked it from both READMEs so the persistent-job and indexing roadmap has a concrete implementation note instead of living only in discussion.

## [Infra: persistent job shell for document processing]
- **Milestone:** Land Phase 1 of the resumability roadmap
- **Activities:**
  - Added a SQLite-backed persistent job store (`document_jobs` + `document_job_progress`) to track durable document-processing state outside process memory.
  - Synced upload/processing status changes into the persistent job store while preserving the existing `/api/documents` response shape for the frontend.
  - Added startup recovery that requeues unfinished jobs after backend restarts instead of silently dropping them.
  - Added cleanup hooks so document deletion and full resets also remove their persisted job rows.
  - Added focused backend tests covering durable job creation, unfinished-job recovery scheduling, and persistent-job cleanup on document deletion.

## [Infra: page-level OCR checkpoints]
- **Milestone:** Land Phase 2 of the resumability roadmap
- **Activities:**
  - Added per-page parser checkpoints under `data/jobs/<doc_id>/pages` so native extraction output is persisted before OCR/indexing finishes.
  - Extended the parser to reload completed native pages from checkpoint files instead of recomputing them on rerun.
  - Persisted OCR-completed page state so resumed runs skip pages whose fallback OCR already finished before an interruption.
  - Wired the upload pipeline to use document-specific checkpoint directories and to clean them up when documents/jobs are deleted.
  - Added backend tests covering native checkpoint reuse, OCR checkpoint reuse, and checkpoint-directory cleanup on document deletion.

## [UX: resume frontend polling after reload]
- **Milestone:** Keep recovered backend jobs visible in the browser
- **Activities:**
  - Added frontend startup polling for documents already in `queued` / `parsing` / `ocr` / `indexing` so reopening the page continues tracking recovered backend jobs.
  - Deduplicated polling per document in the browser so upload-triggered tracking and startup recovery tracking share one in-flight polling task.
  - Kept startup polling silent by default while preserving transition announcements for newly uploaded files in the current session.

## [Infra: batch-aware indexing progress]
- **Milestone:** Land Phase 3 of the resumability roadmap
- **Activities:**
  - Refactored the indexer to keep existing text/table node semantics while assigning stable node ids for future resumable writes.
  - Replaced the one-shot `VectorStoreIndex(nodes=...)` build path with explicit batch insertion so indexing progress can be reported per node and per batch.
  - Persisted `index_total_nodes`, `index_done_nodes`, `index_total_batches`, and `index_done_batches` into the document job store, including schema backfill for existing SQLite files.
  - Exposed real `INDEXING` percentages through `/api/documents` and updated the frontend badge to display them.
  - Added targeted backend tests covering stable node ids, table-node preservation, batch progress reporting, and indexing progress percentage calculation.

## [Infra: lease reclaim and resumable indexing]
- **Milestone:** Land Phase 4 of the resumability roadmap
- **Activities:**
  - Added lease-owner and heartbeat semantics to persistent document jobs so stale attempts can be distinguished from the current active owner.
  - Added startup recovery for orphaned running jobs and a background monitor that periodically reclaims stale leases during normal service operation.
  - Taught the indexer to resume from the last fully completed batch instead of always rebuilding from scratch, while deleting/reinserting the current batch by stable node ids to keep retries idempotent.
  - Guarded parser/indexing progress updates and final state transitions so stale attempts cannot overwrite the active attempt after lease handoff.
  - Added focused tests covering stale-job reclamation and resumed indexing from a partially completed batch.
