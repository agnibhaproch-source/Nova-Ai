import "server-only";

import { z } from "zod";

/** Server-only env (never exposed to the browser). docs/42 */
const schema = z.object({
  API_INTERNAL_URL: z.string().url(),
  API_PROXY_SHARED_SECRET: z.string().min(32),
  APP_URL: z.string().url(),
  S3_PUBLIC_ENDPOINT: z.string().optional().default(""),
});

let cached: z.infer<typeof schema> | null = null;

export function serverEnv(): z.infer<typeof schema> {
  if (!cached) {
    const parsed = schema.safeParse(process.env);
    if (!parsed.success) {
      const names = parsed.error.issues.map((i) => i.path.join(".")).join(", ");
      throw new Error(`Invalid server environment: ${names}`);
    }
    cached = parsed.data;
  }
  return cached;
}
