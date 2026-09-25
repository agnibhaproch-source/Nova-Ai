"""GenerationRunner: runs one assistant generation, decoupled from the HTTP connection
(docs/13 §4–§8, docs/12 §6, docs/14 §8 tool loop, docs/20 §8 citations)."""

from __future__ import annotations

import asyncio
import base64
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import delete, select, update

from app.ai.groq import keys as groq_keys
from app.ai.groq.errors import ProviderError
from app.ai.groq.service import get_groq_service
from app.ai.models_registry import ModelConfig, get_registry
from app.ai.provider import (
    CallContext,
    ChatRequest,
    ImageInput,
    LLMMessage,
    LLMToolCall,
    ToolSchema,
    Usage,
)
from app.ai.tokens import estimate
from app.core.errors import ERROR_META, AppError, ErrorCode
from app.core.redis import get_redis, rkey
from app.core.security import end_user_hash
from app.db.session import get_sessionmaker
from app.files import storage
from app.models import ConversationFile, File, Message, MessagePart, UserPreferences
from app.services import (
    analytics_service,
    context_service,
    memory_service,
    message_service,
    quota_service,
    rag_service,
    settings_service,
)
from app.services.usage_service import record as record_usage
from app.streaming.broker import broker
from app.tools import engine as tool_engine
from app.tools.base import ToolContext
from app.workers.queue import enqueue

log = structlog.get_logger("app.generation")
COALESCE_MS = 30
COALESCE_CHARS = 256
CHECKPOINT_S = 1.0
CHECKPOINT_CHARS = 2000
MAX_GENERATION_S = 300
CITE_RE = re.compile(r"\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]")
_tasks: dict[str, asyncio.Task[None]] = {}


@dataclass
class GenerationJob:
    assistant_message_id: uuid.UUID
    conversation_id: uuid.UUID
    user_id: uuid.UUID
    plan_key: str
    request_id: str
    is_first_turn: bool
    is_edit: bool = False
    is_regenerate: bool = False
    tool_toggles: dict[str, bool] | None = None


def conv_lock_key(conversation_id: uuid.UUID) -> str:
    return rkey("conv_gen", conversation_id)


async def acquire_conv_lock(conversation_id: uuid.UUID, message_id: uuid.UUID) -> bool:
    try:
        return bool(
            await get_redis().set(
                conv_lock_key(conversation_id), str(message_id), nx=True, px=180_000
            )
        )
    except Exception:
        return True  # degraded: allow; DB state guards still apply


async def release_conv_lock(conversation_id: uuid.UUID) -> None:
    try:
        await get_redis().delete(conv_lock_key(conversation_id))
    except Exception:
        pass


def start(job: GenerationJob) -> asyncio.Task[None]:
    task = asyncio.create_task(_run(job), name=f"gen:{job.assistant_message_id}")
    _tasks[str(job.assistant_message_id)] = task
    task.add_done_callback(lambda _t: _tasks.pop(str(job.assistant_message_id), None))
    return task


def local_task(message_id: str) -> asyncio.Task[None] | None:
    return _tasks.get(message_id)


async def shutdown_generations(grace_s: float = 25.0) -> None:
    tasks = list(_tasks.values())
    if not tasks:
        return
    _done, pending = await asyncio.wait(tasks, timeout=grace_s)
    for t in pending:
        t.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


@dataclass
class _State:
    texts: dict[int, str] = field(default_factory=dict)  # part position -> text
    text_pos: int | None = None
    next_pos: int = 0
    buffer: str = ""
    last_publish: float = 0.0
    last_checkpoint: float = field(default_factory=time.monotonic)
    chars_since_checkpoint: int = 0
    first_token_at: float | None = None
    usage: Usage = field(default_factory=lambda: Usage(0, 0, 0))
    usage_reported: bool = False
    finish_reason: str | None = None
    model: ModelConfig | None = None
    user_cancelled: bool = False
    sources: dict[int, dict[str, Any]] = field(default_factory=dict)  # citation index -> source
    tools_used: list[str] = field(default_factory=list)
    iterations: int = 0

    @property
    def text(self) -> str:
        return "\n\n".join(t for _, t in sorted(self.texts.items()) if t)

    def alloc(self, n: int) -> int:
        p = self.next_pos
        self.next_pos += n
        return p


def _add_usage(st: _State, u: Usage | None) -> None:
    if u is None:
        return
    st.usage_reported = True
    st.usage = Usage(
        st.usage.prompt_tokens + u.prompt_tokens,
        st.usage.completion_tokens + u.completion_tokens,
        st.usage.total_tokens + u.total_tokens,
    )


async def _prepare(
    job: GenerationJob, st: _State
) -> tuple[Any, list[Any], ToolContext | None, ModelConfig]:
    """Loads everything the turn needs and builds the context (docs/16)."""
    mid = job.assistant_message_id
    sm = get_sessionmaker()
    async with sm() as db:
        from app.models import Conversation

        conv = await db.get(Conversation, job.conversation_id)
        msg = await db.get(Message, mid)
        prefs = await db.get(UserPreferences, job.user_id) or UserPreferences(
            user_id=job.user_id,
            memory_enabled=True,
            web_search_enabled=True,
            code_execution_enabled=True,
            timezone="UTC",
        )
        assert conv is not None and msg is not None and msg.parent_message_id is not None
        ids = await message_service.path_ids(db, conv.id, msg.parent_message_id)
        path = await message_service.load_messages(db, ids)
        limits = await quota_service.plan_limits(db, job.plan_key)
        model = get_registry().resolve(msg.model_key)
        current = path[-1]
        parts = (
            (await db.execute(select(MessagePart).where(MessagePart.message_id == current.id)))
            .scalars()
            .all()
        )
        budget, _ = context_service.budget(model, int(limits.get("max_output_tokens", 2048)))

        # Images (current turn only, vision models only — docs/25 §3)
        images: list[ImageInput] = []
        image_ids = [p.file_id for p in parts if p.type == "image" and p.file_id]
        if image_ids and model.supports_vision:
            files = (
                (
                    await db.execute(
                        select(File).where(File.id.in_(image_ids), File.user_id == job.user_id)
                    )
                )
                .scalars()
                .all()
            )
            for f in files[: model.max_images_per_request or 4]:
                data = await storage.get_bytes(f"{f.storage_key}/derived/model.jpg")
                images.append(
                    ImageInput("data:image/jpeg;base64," + base64.b64encode(data).decode())
                )

        # RAG over attached documents (docs/20 §3)
        has_files = bool(
            await db.scalar(
                select(ConversationFile.file_id)
                .join(File, File.id == ConversationFile.file_id)
                .where(
                    ConversationFile.conversation_id == conv.id,
                    File.kind == "document",
                    File.deleted_at.is_(None),
                )
                .limit(1)
            )
        )
        rag_block = None
        if has_files:
            chunks = await rag_service.retrieve(
                db,
                job.user_id,
                current.content_text,
                conversation_id=conv.id,
                token_budget=int(budget * 0.3),
            )
            if chunks:
                rag_block = rag_service.render_block(chunks)
                st.sources.update({c.citation_index: c.citation() for c in chunks})
            else:
                rag_block = rag_service.NO_MATCH_NOTE
        memory_block, memory_ids = await memory_service.select_for_context(
            db, job.user_id, current.content_text, min(800, int(budget * 0.05))
        )

        library = bool(
            await db.scalar(
                select(File.id)
                .where(
                    File.user_id == job.user_id,
                    File.status == "ready",
                    File.kind == "document",
                    File.deleted_at.is_(None),
                )
                .limit(1)
            )
        )
        disabled = await settings_service.get(db, "disabled_tools")
        available = [
            t
            for t in tool_engine.registry().values()
            if tool_engine.disabled_reason(
                t,
                model=model,
                limits=limits,
                prefs=prefs,
                disabled_tools=disabled,
                has_files=library,
                toggles=job.tool_toggles,
            )
            is None
        ]
        conv_snapshot, prefs_snapshot = conv, prefs
    built = context_service.build(
        context_service.TurnContext(
            conversation=conv_snapshot,
            path=path,
            model=model,
            preferences=prefs_snapshot,
            plan_max_output_tokens=int(limits.get("max_output_tokens", 2048)),
            tool_names=[t.name for t in available],
            rag_block=rag_block,
            memory_block=memory_block,
            images=images,
        )
    )
    built.truncation["memory_ids"] = [str(i) for i in memory_ids]
    tool_ctx = None
    if available:
        tool_ctx = ToolContext(
            user_id=job.user_id,
            conversation_id=job.conversation_id,
            message_id=mid,
            request_id=job.request_id,
            plan_key=job.plan_key,
            limits=limits,
            preferences=prefs_snapshot,
            attached_file_ids=[],
            cancel_event=asyncio.Event(),
        )
    return built, available, tool_ctx, model


async def _run(job: GenerationJob) -> None:
    mid = job.assistant_message_id
    started = time.monotonic()
    st = _State()
    ctx = CallContext(
        request_id=job.request_id,
        user_id=job.user_id,
        conversation_id=job.conversation_id,
        message_id=mid,
    )
    built = None
    try:
        # BYOK: this task (and every Groq call it makes) uses the conversation owner's key.
        groq_keys.set_current(await groq_keys.for_conversation(job.conversation_id))
        built, available, tool_ctx, model = await _prepare(job, st)
        st.model = model
        consumer = asyncio.create_task(_consume(job, built, available, tool_ctx, ctx, st))
        watcher = asyncio.create_task(_watch_cancel(str(mid), consumer, st, tool_ctx))
        try:
            await asyncio.wait_for(asyncio.shield(consumer), MAX_GENERATION_S)
        except TimeoutError:
            consumer.cancel()
            raise ProviderError(ErrorCode.PROVIDER_TIMEOUT, retryable=True) from None
        except asyncio.CancelledError:
            if not st.user_cancelled:
                consumer.cancel()
                raise
        finally:
            watcher.cancel()
        status = "cancelled" if st.user_cancelled else "completed"
        reason = "cancelled" if st.user_cancelled else (st.finish_reason or "stop")
        await _finish(job, st, started, status=status, finish_reason=reason, context=built)
    except asyncio.CancelledError:
        if st.user_cancelled:
            await _finish(
                job, st, started, status="cancelled", finish_reason="cancelled", context=built
            )
        else:  # process shutdown
            await _fail(job, st, started, ErrorCode.GENERATION_INTERRUPTED)
    except AppError as e:
        await _fail(job, st, started, e.code)
    except Exception:
        log.exception("chat.generation.crashed", message_id=str(mid))
        await _fail(job, st, started, ErrorCode.INTERNAL_ERROR)
    finally:
        await release_conv_lock(job.conversation_id)


async def _watch_cancel(
    message_id: str, consumer: asyncio.Task[None], st: _State, tool_ctx: ToolContext | None
) -> None:
    while not consumer.done():
        if await broker.is_cancel_requested(message_id):
            st.user_cancelled = True
            if tool_ctx is not None:
                tool_ctx.cancel_event.set()  # stops running tools (sandbox gets DELETE)
            consumer.cancel()  # closes the upstream Groq stream via the generator's finally
            return
        await asyncio.sleep(0.2)


async def _consume(
    job: GenerationJob,
    built: Any,
    available: list[Any],
    tool_ctx: ToolContext | None,
    ctx: CallContext,
    st: _State,
) -> None:
    mid = job.assistant_message_id
    messages: list[LLMMessage] = list(built.messages)
    schemas: list[ToolSchema] = tool_engine.schemas(available) if available else []
    engine = None
    if tool_ctx is not None:

        async def publish(event: str, data: dict[str, Any]) -> None:
            await broker.publish(str(mid), event, data)

        engine = tool_engine.ToolEngine(available, tool_ctx, publish)

    def next_tool_position() -> int:
        st.text_pos = None  # text after a tool starts a new text part
        return st.alloc(2)

    for iteration in range(tool_engine.MAX_ITERATIONS + 1):
        st.iterations = iteration + 1
        use_tools = bool(schemas) and iteration < tool_engine.MAX_ITERATIONS
        req = ChatRequest(
            model_key=(st.model.key if st.model else ""),
            messages=messages,
            max_output_tokens=built.max_output_tokens,
            end_user_hash=end_user_hash(str(job.user_id)),
            tools=schemas if use_tools else (),
            tool_choice="auto" if use_tools else "none",
        )
        calls: dict[int, dict[str, str]] = {}
        iter_text = ""
        finish: str | None = None
        used: list[ModelConfig] = []
        try:
            async for chunk in get_groq_service().stream_chat(req, ctx=ctx, on_model=used):
                if used:
                    st.model = used[0]
                _add_usage(st, chunk.usage)
                if chunk.finish_reason:
                    finish = chunk.finish_reason
                for d in chunk.tool_call_deltas:
                    c = calls.setdefault(d.index, {"id": "", "name": "", "args": ""})
                    c["id"] = c["id"] or (d.id or "")
                    c["name"] = c["name"] or (d.name or "")
                    c["args"] += d.arguments_fragment
                if chunk.text_delta:
                    if st.first_token_at is None:
                        st.first_token_at = time.monotonic()
                        await _mark_streaming(mid)
                    if st.text_pos is None:
                        await _flush(mid, st)
                        st.text_pos = st.alloc(1)
                    st.texts[st.text_pos] = st.texts.get(st.text_pos, "") + chunk.text_delta
                    iter_text += chunk.text_delta
                    st.buffer += chunk.text_delta
                    st.chars_since_checkpoint += len(chunk.text_delta)
                    now = time.monotonic()
                    if (now - st.last_publish) * 1000 >= COALESCE_MS or len(
                        st.buffer
                    ) >= COALESCE_CHARS:
                        await _flush(mid, st)
                    if (
                        now - st.last_checkpoint >= CHECKPOINT_S
                        or st.chars_since_checkpoint >= CHECKPOINT_CHARS
                    ):
                        await _checkpoint(mid, st)
        finally:
            await _flush(mid, st)
        st.finish_reason = finish
        if not (finish == "tool_calls" and calls and engine is not None):
            break
        if st.first_token_at is None:
            st.first_token_at = time.monotonic()
            await _mark_streaming(mid)
        llm_calls = [
            LLMToolCall(id=c["id"] or f"call_{i}", name=c["name"], arguments_json=c["args"] or "{}")
            for i, c in sorted(calls.items())
        ]
        assert tool_ctx is not None
        tool_ctx.citation_offset = max(st.sources, default=0)
        executed = await engine.execute_all(llm_calls, iteration, next_tool_position)
        messages.append(
            LLMMessage(
                role="assistant",
                content=iter_text or None,
                tool_calls=tuple(e.call for e in executed),
            )
        )
        for e in executed:
            st.tools_used.append(e.tool_name)
            for c in e.result.citations:
                st.sources[int(c["index"])] = c
            messages.append(
                LLMMessage(
                    role="tool",
                    tool_call_id=e.call.id,
                    name=e.tool_name,
                    content=_fit(e.result.model_content),
                )
            )
        st.finish_reason = None


def _fit(content: str, max_tokens: int = 4000) -> str:
    if estimate(content) <= max_tokens:
        return content
    keep = max_tokens * 3
    return content[:keep] + f"…[truncated {len(content) - keep} chars]"


async def _flush(mid: uuid.UUID, st: _State) -> None:
    if not st.buffer or st.text_pos is None:
        st.buffer = ""
        return
    await broker.publish(
        str(mid),
        "content_delta",
        {"message_id": str(mid), "part_position": st.text_pos, "delta": st.buffer},
    )
    st.buffer = ""
    st.last_publish = time.monotonic()


async def _mark_streaming(mid: uuid.UUID) -> None:
    async with get_sessionmaker()() as db:
        await message_service.transition(db, mid, "streaming")
        await db.commit()


async def _save_texts(db: Any, mid: uuid.UUID, st: _State) -> None:
    for pos, text in st.texts.items():
        await message_service.upsert_text_part(db, mid, pos, text)


async def _checkpoint(mid: uuid.UUID, st: _State) -> None:
    async with get_sessionmaker()() as db:
        await _save_texts(db, mid, st)
        await db.execute(
            update(Message)
            .where(Message.id == mid, Message.status.in_(("pending", "streaming")))
            .values(content_text=st.text)
        )
        await db.commit()
    st.last_checkpoint = time.monotonic()
    st.chars_since_checkpoint = 0


def cited_indices(text: str, valid: set[int]) -> list[int]:
    found: list[int] = []
    for m in CITE_RE.finditer(text):
        for n in (int(x) for x in m.group(1).split(",")):
            if n in valid and n not in found:
                found.append(n)
    return sorted(found)


def _usage_or_estimate(st: _State, context: Any) -> Usage:
    if st.usage_reported:
        return st.usage
    prompt = getattr(context, "estimated_prompt_tokens", 0) or 0
    completion = estimate(st.text)
    return Usage(prompt, completion, prompt + completion)


async def _finish(
    job: GenerationJob,
    st: _State,
    started: float,
    *,
    status: str,
    finish_reason: str,
    context: Any = None,
) -> None:
    mid = job.assistant_message_id
    usage = _usage_or_estimate(st, context)
    latency = int((time.monotonic() - started) * 1000)
    ttft = int((st.first_token_at - started) * 1000) if st.first_token_at else None
    model = st.model or get_registry().resolve(None)
    citations = [st.sources[i] for i in cited_indices(st.text, set(st.sources))]
    async with get_sessionmaker()() as db:
        await _save_texts(db, mid, st)
        meta = {
            "context": (context.truncation if context else {}),
            "tools_used": sorted(set(st.tools_used)),
            "iterations": st.iterations,
            "rag": [str(s.get("chunk_id")) for s in st.sources.values() if s.get("chunk_id")],
        }
        ok = await message_service.transition(
            db,
            mid,
            status,
            content_text=st.text,
            finish_reason=finish_reason,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            time_to_first_token_ms=ttft,
            latency_ms=latency,
            completed_at=datetime.now(UTC),
            groq_model_id=model.groq_model_id,
            metadata_=meta,
        )
        if not ok:  # already terminal (e.g. reaped) — never resurrect
            await db.rollback()
            return
        await db.execute(
            delete(MessagePart).where(MessagePart.message_id == mid, MessagePart.type == "citation")
        )
        for i, c in enumerate(citations):
            db.add(
                MessagePart(
                    message_id=mid,
                    position=st.next_pos + i,
                    type="citation",
                    file_id=uuid.UUID(c["file_id"]) if c.get("file_id") else None,
                    data=c,
                )
            )
        record_usage(
            db,
            kind="chat",
            model=model,
            usage=usage,
            request_id=job.request_id,
            user_id=job.user_id,
            status="cancelled" if status == "cancelled" else "success",
            latency_ms=latency,
            ttft_ms=ttft,
            conversation_id=job.conversation_id,
            message_id=mid,
        )
        await analytics_service.track(
            db,
            "message_completed" if status == "completed" else "generation_stopped",
            user_id=job.user_id,
            properties={
                "model_key": model.key,
                "status": status,
                "finish_reason": finish_reason,
                "ttft_ms": ttft,
                "latency_ms": latency,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "tokens_before_stop": usage.completion_tokens,
                "tool_count": len(st.tools_used),
                "citation_count": len(citations),
                "used_rag": any(s.get("source_type") == "file" for s in st.sources.values()),
                "used_memory": bool(meta["context"].get("memory_ids")),
            },
        )
        await db.commit()
        final = await db.get(Message, mid)
        assert final is not None
        await db.refresh(final)
        serialized = (await message_service.serialize(db, [final]))[0]
        user_msg = (
            await db.get(Message, final.parent_message_id) if final.parent_message_id else None
        )
    for c in citations:
        await broker.publish(str(mid), "citation", {"message_id": str(mid), "citation": c})
    await broker.publish(
        str(mid),
        "usage",
        {
            "message_id": str(mid),
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
            "time_to_first_token_ms": ttft,
            "latency_ms": latency,
        },
    )
    await broker.publish(
        str(mid),
        "message_complete",
        {
            "message_id": str(mid),
            "status": status,
            "finish_reason": finish_reason,
            "message": serialized,
        },
    )
    log.info(
        "chat.generation.completed" if status == "completed" else "chat.generation.cancelled",
        message_id=str(mid),
        model_key=model.key,
        ttft_ms=ttft,
        latency_ms=latency,
        completion_tokens=usage.completion_tokens,
        tools=len(st.tools_used),
    )
    if status == "completed":
        if job.is_first_turn:
            await enqueue(
                "generate_title", str(job.conversation_id), _job_id=f"title:{job.conversation_id}"
            )
        await enqueue(
            "maybe_summarize",
            str(job.conversation_id),
            _job_id=f"summary:{job.conversation_id}:{mid}",
        )
        if user_msg is not None and memory_service.should_extract(user_msg.content_text):
            await enqueue("extract_memories", str(mid), _job_id=f"memory:{mid}")


async def _fail(job: GenerationJob, st: _State, started: float, code: ErrorCode) -> None:
    mid = job.assistant_message_id
    latency = int((time.monotonic() - started) * 1000)
    async with get_sessionmaker()() as db:
        await _save_texts(db, mid, st)
        ok = await message_service.transition(
            db,
            mid,
            "failed",
            content_text=st.text,
            finish_reason="error",
            error_code=str(code),
            latency_ms=latency,
            completed_at=datetime.now(UTC),
        )
        record_usage(
            db,
            kind="chat",
            model=st.model,
            usage=st.usage if st.usage_reported else None,
            request_id=job.request_id,
            user_id=job.user_id,
            status="error",
            latency_ms=latency,
            conversation_id=job.conversation_id,
            message_id=mid,
            error_code=str(code),
        )
        await db.commit()
    _status, retryable, message = ERROR_META[code]
    log.error("chat.generation.failed", message_id=str(mid), error_code=str(code))
    if ok:
        await broker.publish(
            str(mid),
            "error",
            {
                "message_id": str(mid),
                "code": str(code),
                "message": message,
                "retryable": retryable,
                "retry_after_seconds": None,
            },
        )


async def reap_stale(max_age_s: int = 120) -> int:
    """Marks orphaned pending/streaming messages as failed (docs/12 §4)."""
    cutoff = datetime.now(UTC) - timedelta(seconds=max_age_s)
    async with get_sessionmaker()() as db:
        rows = (
            await db.execute(
                select(Message.id, Message.conversation_id).where(
                    Message.status.in_(("pending", "streaming")), Message.updated_at < cutoff
                )
            )
        ).all()
        n = 0
        for mid, cid in rows:
            if local_task(str(mid)):
                continue
            if await message_service.transition(
                db,
                mid,
                "failed",
                finish_reason="error",
                error_code=str(ErrorCode.GENERATION_INTERRUPTED),
                completed_at=datetime.now(UTC),
            ):
                n += 1
                await release_conv_lock(cid)
        await db.commit()
    return n
