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
  - Updated `.agents/workflows/agent_rules.md` to remove the non-Cursor-specific `view_file` tool requirement and clarify using Cursor's file read tool instead, while keeping the same enforcement intent (`spec/Agents.md` → `spec/project.md` → append to `spec/history.md`).

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
