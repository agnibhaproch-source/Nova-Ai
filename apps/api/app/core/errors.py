"""Standard error codes and the AppError hierarchy (docs/32_ERROR_HANDLING.md)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTH_INVALID = "AUTH_INVALID"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    ACCOUNT_SUSPENDED = "ACCOUNT_SUSPENDED"
    FORBIDDEN = "FORBIDDEN"
    CSRF_FAILED = "CSRF_FAILED"
    INSUFFICIENT_SCOPE = "INSUFFICIENT_SCOPE"
    SIGNUPS_DISABLED = "SIGNUPS_DISABLED"
    PLAN_FEATURE_UNAVAILABLE = "PLAN_FEATURE_UNAVAILABLE"
    TOKEN_INVALID = "TOKEN_INVALID"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    PASSWORD_POLICY = "PASSWORD_POLICY"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    REASON_REQUIRED = "REASON_REQUIRED"
    INVALID_CURSOR = "INVALID_CURSOR"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    CONFLICT = "CONFLICT"
    EMAIL_ALREADY_REGISTERED = "EMAIL_ALREADY_REGISTERED"
    LIMIT_REACHED = "LIMIT_REACHED"
    GENERATION_IN_PROGRESS = "GENERATION_IN_PROGRESS"
    CONVERSATION_DELETED = "CONVERSATION_DELETED"
    NOT_IN_TRASH = "NOT_IN_TRASH"
    INVALID_MESSAGE_STATE = "INVALID_MESSAGE_STATE"
    CANNOT_MODIFY_SELF = "CANNOT_MODIFY_SELF"
    RESTORE_WINDOW_EXPIRED = "RESTORE_WINDOW_EXPIRED"
    MODEL_NOT_AVAILABLE = "MODEL_NOT_AVAILABLE"
    MODEL_CAPABILITY_MISSING = "MODEL_CAPABILITY_MISSING"
    CONTEXT_TOO_LARGE = "CONTEXT_TOO_LARGE"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    GROQ_KEY_REQUIRED = "GROQ_KEY_REQUIRED"
    GROQ_KEY_INVALID = "GROQ_KEY_INVALID"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_RATE_LIMITED = "PROVIDER_RATE_LIMITED"
    PROVIDER_MODEL_UNAVAILABLE = "PROVIDER_MODEL_UNAVAILABLE"
    GENERATION_INTERRUPTED = "GENERATION_INTERRUPTED"
    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    DATABASE_ERROR = "DATABASE_ERROR"
    STORAGE_ERROR = "STORAGE_ERROR"
    SERVICE_DEGRADED = "SERVICE_DEGRADED"
    TIMEOUT = "TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    FILE_TYPE_MISMATCH = "FILE_TYPE_MISMATCH"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    STORAGE_QUOTA_EXCEEDED = "STORAGE_QUOTA_EXCEEDED"
    UPLOAD_INVALID = "UPLOAD_INVALID"
    INVALID_FILE = "INVALID_FILE"
    INVALID_FILE_STATE = "INVALID_FILE_STATE"
    FILE_NOT_READY = "FILE_NOT_READY"
    EXPORT_RATE_LIMITED = "EXPORT_RATE_LIMITED"
    EXPORT_NOT_READY = "EXPORT_NOT_READY"
    EXPORT_EXPIRED = "EXPORT_EXPIRED"
    MEMORY_CONTENT_REJECTED = "MEMORY_CONTENT_REJECTED"
    AUDIO_TOO_LONG = "AUDIO_TOO_LONG"
    NO_SPEECH_DETECTED = "NO_SPEECH_DETECTED"
    VOICE_UNAVAILABLE = "VOICE_UNAVAILABLE"
    PAYMENT_PROVIDER_ERROR = "PAYMENT_PROVIDER_ERROR"
    PAYMENT_SIGNATURE_INVALID = "PAYMENT_SIGNATURE_INVALID"
    PLAN_NOT_PURCHASABLE = "PLAN_NOT_PURCHASABLE"
    SUBSCRIPTION_EXISTS = "SUBSCRIPTION_EXISTS"
    NO_ACTIVE_SUBSCRIPTION = "NO_ACTIVE_SUBSCRIPTION"
    TOOL_ERROR = "TOOL_ERROR"


# code -> (http status, retryable, default user-safe message)
ERROR_META: dict[ErrorCode, tuple[int, bool, str]] = {
    ErrorCode.AUTH_REQUIRED: (401, False, "Please log in to continue."),
    ErrorCode.AUTH_INVALID: (401, False, "Your credentials are invalid."),
    ErrorCode.INVALID_CREDENTIALS: (401, False, "Incorrect email or password."),
    ErrorCode.ACCOUNT_LOCKED: (423, True, "Too many attempts. Try again later."),
    ErrorCode.ACCOUNT_SUSPENDED: (403, False, "This account has been suspended. Contact support."),
    ErrorCode.FORBIDDEN: (403, False, "You don't have permission to do that."),
    ErrorCode.CSRF_FAILED: (403, False, "Your session needs to be refreshed. Reload the page."),
    ErrorCode.INSUFFICIENT_SCOPE: (
        403,
        False,
        "This API key doesn't have permission for this action.",
    ),
    ErrorCode.SIGNUPS_DISABLED: (403, False, "Sign-ups are temporarily closed."),
    ErrorCode.PLAN_FEATURE_UNAVAILABLE: (403, False, "This feature isn't included in your plan."),
    ErrorCode.TOKEN_INVALID: (400, False, "This link is invalid or has expired."),
    ErrorCode.VALIDATION_ERROR: (422, False, "Some fields are invalid."),
    ErrorCode.PASSWORD_POLICY: (
        422,
        False,
        "Choose a stronger password (at least 12 characters, not a common password).",
    ),
    ErrorCode.CONFIRMATION_REQUIRED: (422, False, "Please confirm this action."),
    ErrorCode.REASON_REQUIRED: (422, False, "A reason is required for this action."),
    ErrorCode.INVALID_CURSOR: (400, False, "Invalid pagination cursor."),
    ErrorCode.PAYLOAD_TOO_LARGE: (413, False, "The request is too large."),
    ErrorCode.METHOD_NOT_ALLOWED: (405, False, "Method not allowed."),
    ErrorCode.IDEMPOTENCY_KEY_REUSED: (
        409,
        False,
        "This request key was already used with different data.",
    ),
    ErrorCode.RESOURCE_NOT_FOUND: (404, False, "Not found."),
    ErrorCode.CONFLICT: (
        409,
        False,
        "This change conflicts with the current state. Refresh and try again.",
    ),
    ErrorCode.EMAIL_ALREADY_REGISTERED: (409, False, "An account with this email already exists."),
    ErrorCode.LIMIT_REACHED: (409, False, "You've reached the limit for this item."),
    ErrorCode.GENERATION_IN_PROGRESS: (
        409,
        False,
        "Wait for the current response to finish or stop it.",
    ),
    ErrorCode.CONVERSATION_DELETED: (
        409,
        False,
        "This conversation is in the trash. Restore it to continue.",
    ),
    ErrorCode.NOT_IN_TRASH: (
        409,
        False,
        "Only conversations in the trash can be deleted permanently.",
    ),
    ErrorCode.INVALID_MESSAGE_STATE: (409, False, "This message can't be changed right now."),
    ErrorCode.CANNOT_MODIFY_SELF: (409, False, "You can't change your own role or status."),
    ErrorCode.RESTORE_WINDOW_EXPIRED: (410, False, "This item can no longer be restored."),
    ErrorCode.MODEL_NOT_AVAILABLE: (
        422,
        False,
        "This model isn't available. Choose another model.",
    ),
    ErrorCode.MODEL_CAPABILITY_MISSING: (422, False, "The selected model can't handle this input."),
    ErrorCode.CONTEXT_TOO_LARGE: (
        422,
        False,
        "Your message is too long for this model. Shorten it or attach it as a file.",
    ),
    ErrorCode.PROVIDER_ERROR: (502, True, "The AI provider returned an error. Please try again."),
    ErrorCode.GROQ_KEY_REQUIRED: (428, False, "Enter your Groq API key to use this chat."),
    ErrorCode.GROQ_KEY_INVALID: (
        422,
        False,
        "That Groq API key was rejected. Check it and try again.",
    ),
    ErrorCode.PROVIDER_UNAVAILABLE: (
        502,
        True,
        "Nova's AI provider is having trouble. Try again shortly.",
    ),
    ErrorCode.PROVIDER_TIMEOUT: (504, True, "The AI provider took too long to respond."),
    ErrorCode.PROVIDER_RATE_LIMITED: (
        503,
        True,
        "Nova is very busy right now. Try again in a moment.",
    ),
    ErrorCode.PROVIDER_MODEL_UNAVAILABLE: (503, True, "This model is temporarily unavailable."),
    ErrorCode.GENERATION_INTERRUPTED: (
        503,
        True,
        "The response was interrupted. Retry to generate it again.",
    ),
    ErrorCode.RATE_LIMITED: (429, True, "You're doing that too often. Try again shortly."),
    ErrorCode.QUOTA_EXCEEDED: (429, True, "You've reached your usage limit for now."),
    ErrorCode.DATABASE_ERROR: (503, True, "Something went wrong on our side. Please try again."),
    ErrorCode.STORAGE_ERROR: (503, True, "File storage is temporarily unavailable."),
    ErrorCode.SERVICE_DEGRADED: (503, True, "This feature is temporarily unavailable."),
    ErrorCode.TIMEOUT: (504, True, "The request took too long."),
    ErrorCode.INTERNAL_ERROR: (500, True, "Something went wrong. Please try again."),
    ErrorCode.UNSUPPORTED_FILE_TYPE: (415, False, "This file type isn't supported."),
    ErrorCode.FILE_TYPE_MISMATCH: (415, False, "The file's contents don't match its type."),
    ErrorCode.FILE_TOO_LARGE: (413, False, "This file is larger than your plan allows."),
    ErrorCode.STORAGE_QUOTA_EXCEEDED: (
        413,
        False,
        "You've used all your file storage. Delete files or upgrade.",
    ),
    ErrorCode.UPLOAD_INVALID: (422, False, "The upload didn't complete correctly. Try again."),
    ErrorCode.INVALID_FILE: (422, False, "This file can't be used here."),
    ErrorCode.INVALID_FILE_STATE: (
        409,
        False,
        "This file can't be processed in its current state.",
    ),
    ErrorCode.FILE_NOT_READY: (409, False, "This file is still processing."),
    ErrorCode.EXPORT_RATE_LIMITED: (429, True, "You can request one export per day."),
    ErrorCode.EXPORT_NOT_READY: (409, False, "Your export is still being prepared."),
    ErrorCode.EXPORT_EXPIRED: (410, False, "This export has expired. Request a new one."),
    ErrorCode.MEMORY_CONTENT_REJECTED: (
        422,
        False,
        "This can't be saved as a memory (it may contain sensitive data).",
    ),
    ErrorCode.AUDIO_TOO_LONG: (413, False, "Recording is too long (max 10 minutes)."),
    ErrorCode.NO_SPEECH_DETECTED: (422, False, "We couldn't hear any speech. Try again."),
    ErrorCode.VOICE_UNAVAILABLE: (503, False, "Voice isn't available right now."),
    ErrorCode.PAYMENT_PROVIDER_ERROR: (502, True, "Payment service error. Please try again."),
    ErrorCode.PAYMENT_SIGNATURE_INVALID: (400, False, "We couldn't verify this payment."),
    ErrorCode.PLAN_NOT_PURCHASABLE: (422, False, "This plan isn't available."),
    ErrorCode.SUBSCRIPTION_EXISTS: (409, False, "You already have an active subscription."),
    ErrorCode.NO_ACTIVE_SUBSCRIPTION: (404, False, "You don't have an active subscription."),
    ErrorCode.TOOL_ERROR: (502, True, "The tool failed. Please try again."),
}


class AppError(Exception):
    """Expected, user-safe error. Services raise these; handlers render the envelope."""

    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        *,
        details: list[dict[str, Any]] | None = None,
        retry_after: int | None = None,
        status: int | None = None,
    ) -> None:
        meta_status, retryable, default_msg = ERROR_META[code]
        self.code = code
        self.status = status or meta_status
        self.retryable = retryable
        self.message = message or default_msg
        self.details = details or []
        self.retry_after = retry_after
        super().__init__(f"{code}: {self.message}")

    def to_body(self, request_id: str) -> dict[str, Any]:
        err: dict[str, Any] = {
            "code": str(self.code),
            "message": self.message,
            "details": self.details,
            "request_id": request_id,
            "retryable": self.retryable,
        }
        if self.retry_after is not None:
            err["retry_after_seconds"] = self.retry_after
        return {"error": err}


def not_found() -> AppError:
    return AppError(ErrorCode.RESOURCE_NOT_FOUND)
