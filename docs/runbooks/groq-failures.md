# Groq failures / auth errors / slow TTFT

**Means:** Groq error ratio > 10%, the per-model circuit is open, auth errors, or p95 TTFT > 3 s.

**BYOK note:** with `GROQ_KEY_MODE=user` (default) each chat uses its owner's key. `GROQ_KEY_INVALID`
and per-key `PROVIDER_RATE_LIMITED` errors are **user-level** (they don't trip the circuit) — they are
only an incident if many users see them at once (Groq-side auth outage).

**Check**
1. <https://status.groq.com> for incidents.
2. Admin → Errors → `groq` group: `PROVIDER_UNAVAILABLE` / `PROVIDER_TIMEOUT` (Groq side) vs `MODEL_UNAVAILABLE` (model id retired) vs `GROQ_KEY_INVALID`.
3. Server mode only: Admin → Health → `groq.models` shows each configured id as found/missing.

**Fix**
- Groq outage: nothing to change; users see a retryable error. Post a banner: Admin → Settings → `maintenance_banner`.
- Model retired (`MODEL_UNAVAILABLE`): set `GROQ_DEFAULT_MODEL` to the replacement from Groq's docs, update its facts in `config/models.yaml`, deploy.
- Server key revoked (server mode): rotate `GROQ_API_KEY` in the secret store, restart API/worker.
- Cost spike (server mode): check Admin → Dashboard top users; suspend abusive accounts; lower plan limits.

**Verify:** error ratio < 2%, circuit closed, TTFT p95 < 3 s for 15 min.
