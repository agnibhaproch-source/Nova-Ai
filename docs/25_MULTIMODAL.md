# 25 — Multimodal Architecture

## 1. Principle

Capabilities are activated **only** when the configured service/model actually supports them, as declared in `config/models.yaml` (and verified at startup where possible). The UI queries `GET /api/v1/models` and `GET /api/v1/capabilities` and hides or disables inputs that are unsupported. Nothing is simulated (e.g., no fake "image understanding" via filename).

`GET /api/v1/capabilities` (auth required):
```json
{"data":{
  "vision": {"enabled": true, "model_keys": ["vision"], "max_images_per_message": 4},
  "documents": {"enabled": true, "extensions": ["pdf","docx","txt","md","csv","xlsx","pptx"]},
  "voice_input": {"enabled": true},
  "voice_output": {"enabled": false},
  "web_search": {"enabled": true},
  "code_execution": {"enabled": true},
  "video": {"enabled": false}
}}
```
Computed from registry + settings + plan + admin `system_settings` (cached 60 s per plan).

## 2. Modality matrix

| Modality | Input path | Processing | Model input | Status |
|---|---|---|---|---|
| Text | composer | — | text | v1 |
| Documents | upload (18) | extraction + RAG (19, 20) | retrieved text chunks | v1 |
| Images | upload (18) | validation, EXIF strip, display derivative | image content parts to a vision model | Phase 9 (if a vision model is configured) |
| Audio (speech) | recorder → upload | Groq STT → text (26) | text | Phase 9 (if STT configured) |
| Audio (files, e.g. meeting recordings) | upload | STT → transcript treated as a document | chunks | Future |
| Video | — | frame sampling + STT (future) | images + text | Future — disabled |

## 3. Images

### 3.1 Flow
1. User attaches PNG/JPEG/WEBP/GIF (first frame only for GIF) ≤ plan limit.
2. Upload pipeline validates and creates `derived/display.webp` (max 2048 px) and `derived/model.jpg` (JPEG quality 85, long edge ≤ 1568 px, ≤ `model.max_image_bytes`).
3. On send, `ChatService` checks: the selected model has `supports_vision`; image count ≤ `max_images_per_request` (registry) and ≤ 4 per message.
   - If the selected model lacks vision but a `vision` model is enabled for the plan: the UI proactively switches the per-message model to `vision` and shows a chip "Using Nova Vision for this image" (the user can cancel). The API never switches silently; it returns `422 MODEL_CAPABILITY_MISSING` if the request is inconsistent.
   - If no vision model is enabled: the attach menu hides "Image" and image drops are rejected client-side with "Image understanding isn't available."
4. `ContextService` loads `model.jpg` bytes from S3, base64-encodes to a `data:` URL, and attaches as `ImageInput` on the current user message (`14_GROQ_INTEGRATION.md` §5.2).
5. Historical images are replaced by text placeholders except for the last 2 user messages (`16_CONTEXT_MANAGEMENT.md` §3.2).
6. Token cost estimate uses `image_token_cost`.

### 3.2 Storage and rendering
Message `image` parts reference `file_id`; the client displays the `display` variant via presigned URL (1 h) in a thumbnail grid (max 2 columns), click → lightbox dialog.

### 3.3 Safety
- EXIF (including GPS) stripped from derivatives sent to the model and displayed.
- Images from other users can never be referenced (ownership check on `file_ids`).

## 4. Documents

Documents are never sent whole to the model. They go through extraction and RAG. A "summarize this document" request on a long document uses a **map-reduce summarization** path when the question is detected as whole-document (heuristic: message contains summarize/overview/tl;dr and exactly one document is attached and no specific question):
1. Chunks grouped into windows of ≤ 40% of B tokens.
2. Up to 8 windows summarized in parallel (`purpose="summary"`, fast model).
3. Window summaries passed as a `<retrieved_documents>`-style block with page-range citations.
Documents larger than 8 windows: summarize the first 8 windows and state the coverage ("Covers pages 1–120 of 300").

## 5. Audio

Speech input is converted to text through `VoiceService` (`26_VOICE_SYSTEM.md`) and then treated as a normal text message. Audio is not attached to the message and is deleted immediately after transcription (v1 does not keep voice recordings).

## 6. Future video

Design reservation (not implemented): `kind='video'` in `files`, frame extraction at 1 fps (max 32 frames) + audio track transcription, sent to a vision model as images + transcript. Enabled only when a configured Groq model supports the required inputs. Until then, video uploads are rejected with `415 UNSUPPORTED_FILE_TYPE`.

## 7. Message and API schema implications

- `message_parts.type` already includes `image` and `file`; future `audio`/`video` part types require a CHECK constraint migration and doc update.
- `SubmitMessageInput.file_ids` covers all attachment kinds; the server classifies by `files.kind`.
- `LLMMessage.images` is the only path by which binary content reaches Groq.
