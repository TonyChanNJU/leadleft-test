# Persistent Jobs and Indexing Plan

This note breaks the longer-term document-processing roadmap into small, shippable steps. The goal is to make OCR/indexing progress more observable first, then make long-running work recoverable after restarts or worker stalls, without changing retrieval semantics along the way.

## Why this exists

Today the document pipeline already exposes staged states (`PARSING`, `OCR`, `INDEXING`), and `PARSING` / `OCR` now report real percentages. The remaining gap is that document processing still runs as in-process background work, so a server restart or stalled worker can lose progress. `INDEXING` also still runs as one large write, which makes progress reporting and recovery harder than it needs to be.

We want to fix that in a way that is:

1. Safe to land incrementally
2. Compatible with both cloud and local embeddings
3. Neutral to current retrieval quality unless we intentionally change chunking or metadata

## Design principles

* Keep parsing/OCR semantics stable while introducing persistence.
* Treat progress reporting and resumability as first-class product behavior, not log scraping.
* Batch at the **node write** layer, not by changing how tables or text are chunked.
* Prefer restarting the current page or batch over restarting the whole document.

## Non-goals

These steps are not intended to:

* change the current table extraction strategy
* split table nodes more aggressively for indexing progress
* improve retrieval accuracy by themselves
* replace the current vector store in the same milestone

## Phase 1: Persistent job shell

Goal: make document work survive process restarts at the job/state level.

### Scope

* Add a lightweight persistent job store, preferably SQLite.
* Create a durable job record when a PDF is accepted for processing.
* Move pipeline state from "memory only" to "memory + durable backing store".
* Recover unfinished jobs on backend startup.

### Suggested data model

`document_jobs`

* `job_id`
* `document_id`
* `status` (`queued`, `running`, `recoverable`, `ready`, `failed`)
* `stage` (`parsing`, `ocr`, `indexing`)
* `attempt_count`
* `lease_owner`
* `heartbeat_at`
* `last_error`
* `created_at`
* `updated_at`

`document_job_progress`

* `job_id`
* `total_pages`
* `parsed_pages`
* `ocr_candidate_pages_total`
* `ocr_processed_pages`
* `index_total_batches`
* `index_done_batches`
* `current_page`
* `current_batch`

### Expected outcome

After this phase, a backend restart should no longer make the system forget that a document was mid-processing. Recovery can still restart a whole stage, but the job itself becomes durable.

## Phase 2: Page-level OCR checkpoints

Goal: make OCR resume from the last unfinished page instead of starting over.

### Scope

* Persist per-page parse outputs to disk, for example under `data/jobs/{job_id}/pages/`.
* Store native extraction diagnostics separately from OCR output.
* Skip already completed pages when resuming an interrupted OCR run.

### Suggested page checkpoint shape

Per-page JSON can include:

* `page_number`
* `native_text`
* `table_markdown`
* `diagnostics`
* `ocr_text`
* `extraction_method`
* `status`

### Expected outcome

If OCR stops on page 180 of a 200-page report, a resumed job should continue from the missing pages instead of rerunning OCR for the first 179 pages.

## Phase 3: Batch-aware indexing

Goal: make indexing progress explicit and controllable without changing chunking semantics.

### Scope

* Keep current node generation behavior unchanged.
* Generate stable `node_id`s for all text/table nodes before writing.
* Write embeddings/vector records in configurable batches.
* Persist batch progress for frontend display and later recovery.

### Important boundary

Batching should happen **after** node creation. The system should continue to:

* chunk narrative text with the current splitter
* index tables as whole Markdown nodes
* preserve existing metadata shape unless intentionally changed

This is what keeps table understanding and retrieval behavior stable while improving observability and throughput control.

### Impact on embedding modes

This refactor is expected to help both embedding modes mainly through operational improvements:

* **Cloud embeddings**: better request sizing, retry boundaries, and lower full-document rerun cost after failures
* **Local embeddings**: better control of CPU/GPU memory pressure and long-run stability

It should **not** materially improve retrieval accuracy by itself unless chunking, metadata, reranking, or models also change.

### Main trade-off

Batches cannot be made arbitrarily small just to show smoother percentages. Tiny batches increase network round trips for cloud embeddings and can reduce throughput for local embeddings. Batch sizing therefore needs to be tuned together with progress reporting and resumable writes.

## Phase 4: Lease, heartbeat, and resumable indexing

Goal: recover not only from clean restarts, but also from stalled workers or interrupted indexing runs.

### Scope

* Add worker heartbeats while a job is running.
* Use a lease timeout so stalled jobs can be reclaimed.
* Resume indexing from the last unfinished batch rather than recreating the whole index from scratch.
* Keep vector writes idempotent by using stable node IDs.

### Expected outcome

This phase is what makes the system robust to:

* process crashes
* backend restarts
* worker stalls / hangs
* temporary embedding or vector-store failures

## Recommended delivery order

1. Land the persistent job shell
2. Add page-level OCR checkpoints
3. Refactor indexing into batch-aware writes
4. Add heartbeat/lease reclaim and batch-level resume

This order keeps the risk low because each phase improves one layer of the pipeline without forcing a full architectural rewrite all at once.

## Testing strategy

Each phase should add focused verification rather than one giant end-to-end rewrite.

### Phase 1

* job creation persists to SQLite
* startup recovery finds unfinished jobs
* API still returns stable staged status fields

### Phase 2

* interrupted OCR resumes from missing pages
* completed page checkpoints are reused
* per-page diagnostics survive restarts

### Phase 3

* batch progress is visible in status responses
* cloud/local embedding paths both succeed with the same node set
* table nodes remain whole and are not re-split

### Phase 4

* stalled jobs become recoverable after lease timeout
* indexing resumes from the last incomplete batch
* repeated resume attempts do not duplicate vector entries

## Suggested future follow-up

Once these pieces are in place, the frontend can safely show real `INDEXING` percentages backed by stable API fields instead of relying on terminal-only progress bars from library internals.
