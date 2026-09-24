// Mixed read load: conversations list, messages, files, quota — p95 ≤ 300 ms (docs/40 §10).
import http from "k6/http";
import { check } from "k6";

import { API, headers, newConversation, user } from "./lib.js";

export const options = {
  scenarios: {
    reads: {
      executor: "constant-arrival-rate",
      rate: Number(__ENV.RPS || 50), // spread over many seeded users: api_read is limited per user
      timeUnit: "1s",
      duration: __ENV.DURATION || "1m",
      preAllocatedVUs: 20,
      maxVUs: 100,
    },
  },
  thresholds: { "http_req_duration{kind:read}": ["p(95)<300"], "http_req_failed{kind:read}": ["rate<0.01"] },
};

let cid;

export default function () {
  const u = user();
  if (!cid) cid = newConversation(u);
  const paths = ["/conversations?limit=30", `/conversations/${cid}/messages?limit=100`, "/files?limit=50", "/usage/quota", "/models"];
  const r = http.get(`${API}${paths[Math.floor(Math.random() * paths.length)]}`, { headers: headers(u), tags: { kind: "read" } });
  check(r, { "200": (x) => x.status === 200 });
}
