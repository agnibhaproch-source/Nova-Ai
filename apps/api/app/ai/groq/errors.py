"""Map Groq SDK exceptions to domain ProviderErrors (docs/14 §10)."""

from __future__ import annotations

import groq

from app.core.errors import AppError, ErrorCode


class ProviderError(AppError):
    retryable_before_first_token: bool = False

    def __init__(self, code: ErrorCode, *, retryable: bool, retry_after: int | None = None) -> None:
        super().__init__(code, retry_after=retry_after)
        self.retryable_before_first_token = retryable


class ModelUnavailableError(ProviderError):
    def __init__(self) -> None:
        super().__init__(ErrorCode.PROVIDER_MODEL_UNAVAILABLE, retryable=False)


class ContextTooLargeError(ProviderError):
    def __init__(self) -> None:
        super().__init__(ErrorCode.CONTEXT_TOO_LARGE, retryable=False)


def _retry_after(exc: groq.APIStatusError) -> int | None:
    value = exc.response.headers.get("retry-after") if exc.response is not None else None
    try:
        return min(10, int(float(value))) if value else None
    except ValueError:
        return None


def map_groq_error(exc: Exception) -> ProviderError:
    if isinstance(exc, groq.APITimeoutError):
        return ProviderError(ErrorCode.PROVIDER_TIMEOUT, retryable=True)
    if isinstance(exc, groq.APIConnectionError):
        return ProviderError(ErrorCode.PROVIDER_UNAVAILABLE, retryable=True)
    if isinstance(exc, groq.RateLimitError):
        return ProviderError(
            ErrorCode.PROVIDER_RATE_LIMITED, retryable=True, retry_after=_retry_after(exc)
        )
    if isinstance(exc, groq.InternalServerError):
        return ProviderError(ErrorCode.PROVIDER_UNAVAILABLE, retryable=True)
    if isinstance(exc, groq.AuthenticationError | groq.PermissionDeniedError):
        return ProviderError(ErrorCode.GROQ_KEY_INVALID, retryable=False)
    if isinstance(exc, groq.NotFoundError):
        return ModelUnavailableError()
    if isinstance(exc, groq.BadRequestError):
        text = str(getattr(exc, "message", "")).lower()
        if "context" in text and ("length" in text or "too long" in text or "tokens" in text):
            return ContextTooLargeError()
        return ProviderError(ErrorCode.PROVIDER_ERROR, retryable=False)
    if isinstance(exc, groq.APIStatusError):
        return ProviderError(ErrorCode.PROVIDER_UNAVAILABLE, retryable=exc.status_code >= 500)
    return ProviderError(ErrorCode.PROVIDER_ERROR, retryable=False)
