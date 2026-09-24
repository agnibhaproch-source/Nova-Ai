// SSE chat load: TTFT p95 and stream completion (docs/40 §10). Run against a stub-backed stack:
//   docker run --rm -i -e PROXY_SECRET=... grafana/k6 run - < infra/k6/chat_stream.js
import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";

import { API, headers, newConversation, user } from "./lib.js";

const ttft = new Trend("nova_ttft_ms", true);
const completed = new Rate("nova_stream_completed");

export const options = {
  scenarios: {
    streams: {
      executor: "ramping-vus",
      startVUs: 1,
      stages: [
        { duration: __ENV.RAMP || "30s", target: Number(__ENV.VUS || 20) },
        { duration: __ENV.HOLD || "1m", target: Number(__ENV.VUS || 20) },
        { duration: "10s", target: 0 },
      ],
    },
  },
  thresholds: {
    nova_stream_completed: ["rate>=0.99"],
    nova_ttft_ms: ["p(95)<3000"],
    "http_req_failed{kind:stream}": ["rate<0.01"],
  },
};

let cid;

export default function () {
  const u = user();
  if (!cid) cid = newConversation(u);
  const r = http.post(
    `${API}/conversations/${cid}/messages`,
    JSON.stringify({ content: `load test ${Date.now()}` }),
    { headers: headers(u, { accept: "text/event-stream" }), tags: { kind: "stream" }, timeout: "120s" },
  );
  // k6 buffers SSE bodies; time-to-first-byte approximates TTFT for the stream.
  ttft.add(r.timings.waiting);
  const ok = r.status === 200 && r.body.includes("event: message_complete");
  completed.add(ok);
  check(r, { "stream completed": () => ok });
  // Think time: a person reads the answer before sending again (and per-user limits apply:
  // pro = 40 messages/min). Seed at least as many users as VUs.
  sleep(2 + Math.random() * 2);
}
