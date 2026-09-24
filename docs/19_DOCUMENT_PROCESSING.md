# 19 — Document Processing

## 1. Pipeline

```
upload (18) → validation (18 §4) → storage (S3) → [worker: process_file]
   → extraction (per format) → normalization → chunking → embedding → indexing → ready
```

All steps after `complete` run asynchronously in the ARQ worker job `process_file(file_id)` (`app/workers/tasks/files.py`) orchestrated by `DocumentPipeline` (`app/documents/pipeline.py`).

Job settings: `max_tries=5`, `timeout=900 s`, retry backoff `[10, 30, 90, 300, 900]` s, queue `files`. Idempotent: every run starts by deleting existing `document_chunks` for the file.

Per-stage progress updates `files.metadata.stage/progress` (throttled to one DB write per second).

## 2. Common extractor interface

```python
@dataclass
class ExtractedSegment:
    text: str
    page_number: int | None = None     # PDF page / PPTX slide (1-based)
    sheet_name: str | None = None      # XLSX/CSV
    section_title: str | None = None   # nearest heading
    kind: Literal["paragraph","heading","table","list","code","notes"] = "paragraph"

@dataclass
class ExtractionResult:
    segments: list[ExtractedSegment]
    page_count: int | None
    metadata: dict                      # title, author, created, sheet names, etc.
    warnings: list[str]                 # e.g. "page 7 has no extractable text"

class Extractor(Protocol):
    extensions: frozenset[str]
    def extract(self, path: Path, limits: ExtractionLimits) -> ExtractionResult: ...
```

Extractors are CPU-bound and run in a **process pool** (`concurrent.futures.ProcessPoolExecutor(max_workers=WORKER_EXTRACT_PROCESSES)`, default 2) via `loop.run_in_executor`, each call with a 300 s timeout; the pool is recreated if a child crashes. This isolates parser crashes and memory blowups from the worker event loop. Child processes have `resource.setrlimit(RLIMIT_AS, 2 GB)`.

## 3. Format-specific extraction

### PDF (`pypdf`)
- `PdfReader(path, strict=False)`; if `reader.is_encrypted`: try `decrypt("")`; failure → `FILE_ENCRYPTED`.
- Per page: `page.extract_text(extraction_mode="layout")` falling back to default mode if layout mode raises; one segment per page, `page_number = i+1`.
- Headings: heuristic — lines ≤ 80 chars, Title Case or ALL CAPS, followed by a blank line → `section_title` propagation.
- Page count > plan max → process first N pages, warning `truncated_pages`.
- If total extracted text < 50 chars per page on average for ≥ 80% of pages → mark `failed` with `error_code='NO_EXTRACTABLE_TEXT'` ("This PDF appears to be scanned images. OCR is not supported yet."). OCR is a future item (`52_ROADMAP.md`).
- Metadata: title, author, creation date from `reader.metadata`.

### DOCX (`python-docx`)
- Iterate body elements in document order (paragraphs and tables via `document.element.body.iterchildren()`).
- Paragraph style `Heading N`/`Title` → `kind='heading'`, updates `section_title`.
- Lists: style names containing `List` → prefix `- `.
- Tables → Markdown table text (`| a | b |`), `kind='table'`; cap 200 rows per table (warning).
- Headers/footers ignored; footnotes/comments ignored (v1).
- `page_number` = None (DOCX has no stable pages).

### TXT
- Detect encoding: BOM → UTF-8/UTF-16; else try UTF-8 strict; else `charset_normalizer` best guess; else Latin-1.
- Split into paragraphs on blank lines; one segment each.

### Markdown
- Decode as TXT; parse headings (`^#{1,6} `) to set `section_title`; keep Markdown syntax (the model reads Markdown well); fenced code blocks kept intact as `kind='code'` segments (never split mid-fence by the chunker if ≤ max chunk size).

### CSV
- Sniff dialect (`csv.Sniffer`, fallback comma); decode as TXT.
- First row as header if `Sniffer.has_header` or all non-numeric.
- Emit **row groups**: 25 rows per segment rendered as a Markdown table with the header repeated in each segment; `sheet_name = filename`.
- Also emit one "schema" segment: column names, row count, per-column inferred type and 3 sample values (lets the model answer structural questions).
- Cap: 50,000 rows (warning `truncated_rows`).

### XLSX (`openpyxl`)
- `load_workbook(path, read_only=True, data_only=True)` (cached formula values; formulas not evaluated).
- Per sheet (skip hidden sheets; warning): schema segment + row groups of 25 as Markdown tables; `sheet_name` set; empty rows skipped; cells formatted with `str()`; dates ISO-8601.
- Cap: 50,000 rows total, 100 sheets.

### PPTX (`python-pptx`)
- Per slide: title placeholder → `section_title`; text frames in shape order (grouped shapes flattened); tables → Markdown; notes (`slide.notes_slide.notes_text_frame.text`) as `kind='notes'` segment prefixed "Speaker notes:".
- `page_number` = slide number.

### Images (attachment kind `image`)
- No text extraction (OCR not supported). Stored derivative for display; used only as vision input (`25_MULTIMODAL.md`). Status goes directly to `ready` after validation/scan. Images are **not** chunked or embedded.

## 4. Normalization (`normalizer.py`)

Applied to every segment:
1. Unicode NFC.
2. Remove control chars except `\n` and `\t`; replace ` ` with space; remove soft hyphens `­`.
3. De-hyphenate line breaks in PDFs: `(\w)-\n(\w)` → `\1\2`.
4. Collapse runs of spaces/tabs to one space (except inside `code` segments); collapse 3+ newlines to 2.
5. Remove repeated page headers/footers in PDFs: lines appearing identically on ≥ 50% of pages (first/last 2 lines of each page) are removed.
6. Drop empty segments.

The normalized full text (segments joined by `\n\n` with offsets tracked) is stored to `derived/text.txt`; `char_start/char_end` of chunks refer to this text.

## 5. Chunking (`chunker.py`)

Structure-aware recursive splitter measured with `TokenEstimator`:

- Target chunk size **512 tokens**, max **800**, overlap **64 tokens** (overlap taken from the end of the previous chunk at sentence boundary).
- Boundaries respected in order: segment/page boundary → heading → paragraph (`\n\n`) → line → sentence (regex `(?<=[.!?।])\s+`) → word.
- Never merge text across different `page_number` or `sheet_name` values (keeps citations precise); small trailing pieces (< 100 tokens) merge with the previous chunk **only** if same page/sheet.
- Tables (`kind='table'`) are split by rows with the header row repeated.
- Each chunk carries: `chunk_index`, `content`, `token_count`, `page_number`, `sheet_name`, `section_title`, `char_start`, `char_end`.
- Contextual header: the stored `content` is prefixed with a one-line header used for embedding and display trimming: `"[{filename} · p.{page} · {section_title}]\n"` (omitted parts skipped). The header is included in `token_count`.
- Max chunks per file: `ceil(max_extracted_tokens / 448)`; beyond → truncate with warning.

## 6. Embedding

- `EmbeddingService.embed_documents(texts: list[str]) -> list[list[float]]` in batches of `EMBEDDING_BATCH_SIZE` (default 32), concurrency 2 per job.
- Each vector's length must equal `EMBEDDING_DIMENSIONS` → else fail job `EMBEDDING_DIMENSION_MISMATCH` (alerts; config error).
- Vectors are L2-normalized by the service before storage (cosine distance then equals `1 - dot`).
- Retries on embedding server 5xx/timeouts (3 attempts, backoff 1/2/4 s) before failing the job attempt.
- Usage: one `usage_records` row per job `kind='embedding'`, `provider='embeddings'`, `prompt_tokens` = sum of estimated tokens, cost `NULL` (self-hosted; infra cost tracked separately in `51_COST_OPTIMIZATION.md`).

## 7. Indexing

- Insert chunks in batches of 200 using `INSERT ... VALUES` via SQLAlchemy Core `insert().values([...])` in one transaction per batch.
- After all batches: in one transaction set `files.status='ready'`, `chunk_count`, `token_count`, `page_count`, `processed_at`, `metadata` (+ warnings).
- HNSW index updates are incremental (no rebuild).

## 8. Failure handling

| Error | Status | `error_code` | Retry |
|---|---|---|---|
| Parser exception / timeout | failed (after retries) | `EXTRACTION_FAILED` | auto ×5, then user "Retry" |
| No text | failed | `NO_EXTRACTABLE_TEXT` | no |
| Encrypted | failed | `FILE_ENCRYPTED` | no |
| Too large after decompression | rejected | `FILE_TOO_COMPLEX` | no |
| Embedding service down | processing (retrying) → failed | `EMBEDDING_UNAVAILABLE` | auto, then user retry |
| Dimension mismatch | failed | `EMBEDDING_DIMENSION_MISMATCH` | no (alert) |

`POST /api/v1/files/{id}/retry` re-enqueues `process_file` for `failed` files (max 3 manual retries/day per file).

User-facing `error_message` values are fixed strings from `app/documents/messages.py` (never raw exception text).

## 9. Reprocessing

Admin/system job `reprocess_files(filter)` (e.g., after chunker or embedding model changes) re-enqueues files in batches of 100 with low priority queue `files_low`. Files remain `ready` with old chunks until new chunks are written atomically (new chunks inserted, old deleted in one transaction per file).

## 10. Performance targets

- 50-page text PDF: extraction ≤ 10 s, chunking ≤ 1 s, embedding ≤ 30 s (depends on embedding server; target with CPU TEI and a small model), total p95 ≤ 60 s (NFR-006).
- Worker concurrency: `WORKER_MAX_JOBS` (default 8) with `files` queue limited to 4 concurrent jobs per worker to bound memory.
