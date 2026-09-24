# 26 — Voice System

## 1. Pipeline

```
Microphone (browser MediaRecorder)
   → upload audio (multipart to API)          POST /api/v1/voice/transcriptions
   → VoiceService.transcribe → SttProvider (GroqSttProvider → GroqService.transcribe)
   → transcript text returned to client
   → [dictation] inserted into composer for review   |  [voice mode] auto-sent as user message
   → normal chat turn (Groq)
   → [voice mode] assistant text → VoiceService.synthesize → TtsProvider (GroqTtsProvider) → audio stream
   → browser playback
```

## 2. Replaceable providers

```python
class SttProvider(Protocol):
    async def transcribe(self, audio: bytes, filename: str, mime_type: str,
                         language: str | None, ctx: CallContext) -> TranscriptionResult

class TtsProvider(Protocol):
    def synthesize(self, text: str, voice: str, fmt: Literal["mp3","wav"], ctx: CallContext) -> AsyncIterator[bytes]
    def voices(self) -> list[VoiceInfo]

@dataclass
class TranscriptionResult:
    text: str
    language: str | None
    duration_seconds: float | None
```

v1 implementations: `GroqSttProvider`, `GroqTtsProvider` (both delegate to `GroqService`, `14_GROQ_INTEGRATION.md` §13). Selected by `VOICE_STT_PROVIDER=groq|none` and `VOICE_TTS_PROVIDER=groq|browser|none`.

- `browser` TTS: no server synthesis; the client uses the Web Speech API (`speechSynthesis`) — a real, on-device capability, labeled "Device voice" in settings. It is the fallback when `GROQ_TTS_MODEL` is not configured.
- A new provider (e.g., a self-hosted speech model) = new adapter class; no pipeline changes. Using a prohibited LLM vendor's speech API is not allowed.

## 3. Speech-to-text

`POST /api/v1/voice/transcriptions` — `multipart/form-data` fields: `audio` (file), `language` (optional BCP-47, e.g. `en`, `hi`).
- Auth: session (CSRF) or API key with `chat:write`.
- Limits: ≤ 25 MB, ≤ 600 s (duration read with a lightweight header probe; if unknown, enforced by size), plan `voice_minutes_per_day`, rate limit 20/min.
- Accepted MIME: `audio/webm`, `audio/ogg`, `audio/mpeg`, `audio/mp4`, `audio/wav`, `video/webm` (Chrome MediaRecorder).
- Processing: body streamed to a temp file (never to S3 in v1) → magic check → STT → delete temp → respond.
- Response: `{"data": {"text": "...", "language": "en", "duration_seconds": 7.4}}`.
- Usage record `kind='stt'`, `audio_seconds`; errors map to `VOICE_UNAVAILABLE`, `AUDIO_TOO_LONG`, `UNSUPPORTED_FILE_TYPE`, `PROVIDER_*`.
- Empty transcript → `422 NO_SPEECH_DETECTED`.

## 4. Text-to-speech

`POST /api/v1/voice/speech` body `{"message_id": uuid, "voice": str?, "format": "mp3"}` (text comes from the stored assistant message — the client cannot synthesize arbitrary text, preventing abuse as a free TTS API).
- Owner check; message must be assistant and `completed`.
- Text preparation: strip Markdown (code blocks replaced by "code omitted", URLs by domain name, citation markers removed), max `tts_max_input_chars` per request chunk; long texts split at sentence boundaries into sequential chunks streamed back-to-back.
- Response: `200` `Content-Type: audio/mpeg`, chunked streaming body.
- Usage `kind='tts'`, `characters`.
- Voice id validated against `registry.audio_tts().voices`; default `GROQ_TTS_DEFAULT_VOICE` or user's `tts_voice`.

## 5. Frontend

### 5.1 Dictation (composer mic button)
- Click → request mic permission → recording UI (waveform via `AnalyserNode`, timer, cancel ✕, stop ✓). Max 120 s (auto-stop).
- `MediaRecorder` with `audio/webm;codecs=opus` if supported else `audio/mp4`.
- Stop → upload → spinner in composer → transcript inserted at cursor; user edits and sends.
- Keyboard: `Ctrl/Cmd+Shift+Space` toggles recording.
- Hidden if `capabilities.voice_input.enabled=false`.

### 5.2 Voice mode (Phase 9)
- Full-screen overlay (`VoiceModeDialog`): large animated orb (reduced-motion: static), status text (Listening / Thinking / Speaking), buttons: mute mic, end.
- Turn-taking: push-to-talk by default (hold Space or tap orb); optional "hands-free" using simple energy-based VAD in an `AudioWorklet` (end of speech after 900 ms silence).
- Flow per turn: record → transcribe → send message (normal SSE) → when `message_complete`, request `/voice/speech` → play via `MediaSource`/`<audio>` streaming → auto-listen again in hands-free mode.
- Barge-in: user starts speaking (VAD) or taps → stop playback and, if still generating, call cancel.
- Transcript of the exchange appears in the conversation as normal messages.

### 5.3 Per-message "Read aloud"
Action-bar speaker button on assistant messages → `/voice/speech` (or `speechSynthesis` for browser TTS).

## 6. Privacy

- Audio is never stored beyond the request (deleted temp file).
- Transcripts become normal messages (same retention as chat).
- Mic permission is requested only on explicit user action.

## 7. Latency targets

STT p95 ≤ 1.5 s for 10 s of audio; TTS time-to-first-audio p95 ≤ 1.0 s.

## 8. Future: real-time duplex

A WebSocket-based streaming voice pipeline (partial transcripts, streamed TTS during generation) is a future ADR; SSE + HTTP is sufficient for v1.
