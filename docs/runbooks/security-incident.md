# Security incident

**Triage (first 30 min):** open an incident channel, assign an owner and a scribe, record a timeline.
Classify: leaked secret · account takeover · data exposure · abuse (sandbox/tools) · dependency CVE.

**Contain**
- Leaked server secret → rotate it in the secret store and redeploy:
  - `AUTH_SECRET` (keep the old value in `AUTH_SECRET_PREVIOUS` for one session lifetime; note BYOK chat keys encrypted with the old secret become unreadable — users re-enter them),
  - `API_PROXY_SHARED_SECRET` (API + web together), `S3_*`, `SANDBOX_RUNNER_TOKEN`, `GROQ_API_KEY` (server mode).
- Compromised account → Admin → Users → suspend; revoke sessions and API keys.
- Leaked user Groq key (BYOK) → tell the user to revoke it at console.groq.com; `DELETE /conversations/{id}/groq-key` removes our copy.
- Feature abuse → kill switches in Admin → Settings (`disabled_tools`, `signups_enabled`, `chat_enabled`).

**Eradicate & recover:** fix the root cause, patch, redeploy; verify with the audit log (Admin → Audit logs) that the attacker's access is gone.

**Notify:** affected users (and the Data Protection Board where the DPDP Act 2023 requires) within 72 h, after legal review.

**Post-mortem** within 5 working days: timeline, root cause, what worked, action items with owners.
