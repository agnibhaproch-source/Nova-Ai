# 18 — File Uploads

## 1. Architecture

Direct-to-storage uploads using **S3 presigned POST** (supports `content-length-range` enforcement), followed by server-side verification and asynchronous processing. The API never proxies file bodies through the upload path. (Voice audio for transcription is a separate, small multipart request to `/api/v1/voice/transcriptions` that is never stored; see `26_VOICE_SYSTEM.md`.)

```
initiate (API) → browser POSTs to S3 → complete (API) → worker: verify/scan → process → ready
```

## 2. Supported formats

| Kind | Extensions | Declared MIME types accepted | Magic-byte detected (libmagic) must be one of |
|---|---|---|---|
| document | pdf | application/pdf | application/pdf |
| document | docx | application/vnd.openxmlformats-officedocument.wordprocessingml.document | same, or application/zip (then validated as OOXML by `[Content_Types].xml` + `word/document.xml`) |
| document | xlsx | application/vnd.openxmlformats-officedocument.spreadsheetml.sheet | same or zip (+ `xl/workbook.xml`) |
| document | pptx | application/vnd.openxmlformats-officedocument.presentationml.presentation | same or zip (+ `ppt/presentation.xml`) |
| document | txt | text/plain | text/* (must decode as UTF-8/UTF-16 with BOM/Latin-1 fallback) |
| document | md, markdown | text/markdown, text/plain, text/x-markdown | text/* |
| document | csv | text/csv, application/vnd.ms-excel, text/plain | text/* |
| image | png, jpg, jpeg, webp, gif | image/png, image/jpeg, image/webp, image/gif | same family |

Not supported (explicit rejection `415 UNSUPPORTED_FILE_TYPE`): legacy .doc/.xls/.ppt, macro-enabled (.docm/.xlsm/.pptm), archives (.zip, .rar), executables, SVG (XSS risk), HTML.

## 3. Size and count limits

| Limit | free | plus | pro |
|---|---|---|---|
| Max document size | 10 MB | 25 MB | 50 MB |
| Max image size | 5 MB | 10 MB | 10 MB |
| Uploads per day | 10 | 100 | 500 |
| Total storage | 100 MB | 2 GB | 10 GB |
| Max pages (PDF/PPTX) | 100 | 500 | 1,000 |
| Max extracted tokens per file | 200k | 1M | 2M |

Values live in `plans.limits` (`35_USAGE_TRACKING.md` §5). Avatar: 2 MB all plans. Global hard cap 50 MB.

## 4. Validation

**At initiate** (`POST /api/v1/files`):
```json
{"filename":"Q3 report.pdf","size_bytes":1048576,"mime_type":"application/pdf","purpose":"attachment","conversation_id":"uuid|null"}
```
1. Auth (session or API key with `files:write`), CSRF, rate limit `file_upload` (no email verification; ADR 0002).
2. Filename: NFC normalize, strip path components and control chars, max 255 bytes; derive extension (lower-case). Unknown extension → 415.
3. Extension ↔ declared MIME consistent per table §2 → else `415 FILE_TYPE_MISMATCH`.
4. Size ≤ plan limit for kind → else `413 FILE_TOO_LARGE`.
5. Quotas: uploads today, storage used (`SUM(size_bytes)` of non-deleted files, cached in Redis `nova:{env}:storage:{user_id}` 5 min + incremented on upload) → `429 QUOTA_EXCEEDED` / `413 STORAGE_QUOTA_EXCEEDED`.
6. Insert `files` row `status='pending_upload'`, `storage_key = users/{user_id}/files/{file_id}` (no user-controlled path parts).
7. Generate presigned POST (expires 10 min):
   ```python
   s3.generate_presigned_post(Bucket, Key=storage_key,
       Fields={"Content-Type": declared_mime},
       Conditions=[["content-length-range", 1, size_bytes], {"Content-Type": declared_mime}],
       ExpiresIn=600)
   ```
   The URL uses `S3_PUBLIC_ENDPOINT` (browser-reachable) when set.
8. Response `201 {data: {file, upload: {url, fields, expires_at}}}`.

**At complete** (`POST /api/v1/files/{id}/complete`):
1. Owner check, status must be `pending_upload` (idempotent if already beyond).
2. `HEAD` object: exists; `ContentLength` ≤ declared size (+0) and > 0 → else status `rejected`, delete object, `422 UPLOAD_INVALID`.
3. `status='uploaded'`, `size_bytes` = actual; if `conversation_id` given, insert `conversation_files`.
4. Enqueue `process_file(file_id)`; response `200 {data: file}`.

**In worker** (`process_file` first stage):
1. Download object to a temp file (worker ephemeral disk, `tempfile` in a per-job directory, deleted in `finally`).
2. SHA-256 compute → `files.sha256`.
3. libmagic detection → must match allowed set for extension → else `rejected` + `FILE_TYPE_MISMATCH`.
4. OOXML: validate zip structure (no entries with absolute paths or `..`, total uncompressed size ≤ 20× compressed and ≤ 500 MB, ≤ 10,000 entries — zip bomb protection); reject macro parts (`vbaProject.bin`).
5. PDF: reject encrypted PDFs that require a password (`FILE_ENCRYPTED`); flag JavaScript/embedded files (allowed but never executed — we only extract text).
6. Images: open with Pillow in `Image.open` + `verify()`, enforce max 40 megapixels (decompression-bomb guard `Image.MAX_IMAGE_PIXELS`), strip EXIF by re-encoding to the same format (for storage of derivative `…/derived/display.webp`, max 2048 px long edge); the original is kept for download.
7. Malware scan (§5).

## 5. Malware and security

- `CLAMAV_ENABLED=true` in staging/production: stream file to `clamd` via `INSTREAM` (TCP `CLAMAV_HOST:CLAMAV_PORT`), timeout 60 s. `FOUND` → status `rejected`, `error_code='FILE_MALWARE_DETECTED'`, object deleted, `moderation_flags(source='automated', category='abuse')` created, audit `file.malware_detected`. Scanner unavailable → retry job (backoff) up to 5 times, then `failed` with `SCAN_UNAVAILABLE` (never mark ready unscanned in production).
- Files are never executed or rendered as HTML. Downloads use `Content-Disposition: attachment` except images (inline in `<img>` only) — set via presigned GET `ResponseContentDisposition`.
- Bucket is private; no public ACLs; Block Public Access on; server-side encryption (SSE-S3 or SSE-KMS).
- Bucket CORS (browser upload): `AllowedOrigins=[APP_URL]`, `AllowedMethods=[POST, GET]`, `AllowedHeaders=["*"]`, `MaxAgeSeconds=3000`.

## 6. Storage layout

```
users/{user_id}/files/{file_id}                    original
users/{user_id}/files/{file_id}/derived/display.webp   image display derivative
users/{user_id}/files/{file_id}/derived/text.txt       normalized extracted text (for debugging/reprocess; deleted with file)
users/{user_id}/avatar/{file_id}.webp
users/{user_id}/exports/{export_id}.zip
```

Note: S3 keys `.../{file_id}` and `.../{file_id}/derived/...` coexist (S3 has no directories).

## 7. Upload states

| DB status | UI label | Meaning |
|---|---|---|
| pending_upload | Uploading… (progress %) | Awaiting browser upload/complete |
| uploaded | Processing… | Queued |
| scanning | Processing… | Type validation + malware scan |
| processing | Processing… (stage label: "Reading document", "Indexing") | Extraction/chunking/embedding |
| ready | Ready | Usable in RAG / as image input |
| failed | Failed — Retry | Processing error (retryable via `POST /files/{id}/retry`) |
| rejected | Rejected | Validation/malware failure (not retryable) |
| deleted | — | Hidden |

`files.metadata.stage` holds the fine-grained stage for UI (`validating`, `scanning`, `extracting`, `chunking`, `embedding`, `indexing`) and `progress` 0–100.

Client polling: `GET /api/v1/files/{id}` every 1.5 s while non-terminal (TanStack Query `refetchInterval`), max 10 minutes. Uploads stuck in `pending_upload` for > 1 h are deleted by `purge_deleted_files` (orphan cleanup).

Upload progress in the browser uses `XMLHttpRequest` `upload.onprogress` for the S3 POST (fetch lacks upload progress).

## 8. Authorization

- All file endpoints are owner-scoped (`FileRepository.get_for_user`).
- Attaching to a conversation verifies ownership of both.
- Presigned URLs are generated only after ownership checks and are short-lived (upload 10 min, download 5 min, image thumbnails 1 h).
- API keys need `files:read` / `files:write`.

## 9. Attachment to conversations and messages

- Composer attachments: files are uploaded immediately when selected (in parallel, max 3 concurrent); the send button is enabled when all are at least `uploaded` (documents may still be processing — the assistant is told "document X is still processing" via a system note, and RAG includes it only once ready; the UI shows a hint). Images must be `ready` before send (quick).
- `SubmitMessageInput.file_ids` → user message gets `file`/`image` parts and `conversation_files` rows.
- `POST /api/v1/conversations/{id}/files {file_id}` attaches an existing library file without sending a message; `DELETE /api/v1/conversations/{id}/files/{file_id}` detaches (does not delete the file).
- `GET /api/v1/conversations/{id}/files` lists attached files (shown in the conversation header "Files" popover).

## 10. Deletion

`DELETE /api/v1/files/{id}`:
1. Owner check; set `status='deleted'`, `deleted_at=now()` (immediately excluded from RAG queries which filter `files.status='ready' AND deleted_at IS NULL`).
2. `DELETE FROM document_chunks WHERE file_id=:id` in the same transaction (removes embeddings).
3. `conversation_files` rows removed; message parts keep `file_id` (FK SET NULL happens at hard-delete) and render "File deleted".
4. After commit enqueue `purge_file(file_id)`: delete original + derived objects, then hard-delete row.
5. Storage counter decremented. Audit not required (user action), analytics `file_deleted`.

## 11. Download

`GET /api/v1/files/{id}/download` → `302 Location: <presigned GET, 5 min, ResponseContentDisposition=attachment; filename*=UTF-8''<encoded original name>>`. Status must be `ready` or `failed` (not `rejected`). The proxy passes `Location` through.

`GET /api/v1/files/{id}/content-url?variant=display` → `{url, expires_at}` for inline image display (images only).

## 12. Library

`GET /api/v1/files?kind=&status=&q=&limit=&cursor=` lists the user's files (sorted `created_at DESC`); UI in the "Files" dialog accessible from the sidebar and the composer's attach menu ("Add from library").
