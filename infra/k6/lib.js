// Shared helpers (docs/40 §10). Load users are pre-seeded verified pro accounts with API keys:
//   (cd apps/api && uv run python -m tests.fakes.seed_load_users 20) > infra/k6/users.json
// Point at a Groq-stub-backed environment; never at production with real keys.
import http from "k6/http";
import { check } from "k6";

export const API = __ENV.API_URL || "http://host.docker.internal:8010/api/v1";
const PROXY = __ENV.PROXY_SECRET; // X-Nova-Proxy-Secret, passed with -e (never committed)
export const GROQ_KEY = __ENV.GROQ_KEY || "gsk_k6_load_test_key_not_real_0000";
const USERS = JSON.parse(open(__ENV.USERS_FILE || "./users.json"));

export function user() {
  return USERS[(__VU - 1) % USERS.length];
}

export function headers(u, extra = {}) {
  return {
    "content-type": "application/json",
    authorization: `Bearer ${u.api_key}`,
    "x-nova-proxy-secret": PROXY,
    ...extra,
  };
}

export function newConversation(u) {
  const r = http.post(`${API}/conversations`, JSON.stringify({ groq_api_key: GROQ_KEY }), { headers: headers(u) });
  check(r, { "conversation 201": (x) => x.status === 201 });
  return r.json("data.id");
}
