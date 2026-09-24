# Web image (docs/43 §2.2). Build context: repo root. CI pins base images by digest.
FROM node:22-alpine AS base
RUN corepack enable
WORKDIR /repo

FROM base AS deps
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json ./
COPY apps/web/package.json apps/web/
COPY apps/desktop/package.json apps/desktop/
RUN --mount=type=cache,target=/root/.local/share/pnpm pnpm install --frozen-lockfile --filter web...

FROM deps AS dev
COPY apps/web apps/web
WORKDIR /repo/apps/web
CMD ["pnpm", "dev", "--hostname", "0.0.0.0"]

FROM deps AS build
COPY apps/web apps/web
WORKDIR /repo/apps/web
ARG NEXT_PUBLIC_APP_URL NEXT_PUBLIC_APP_NAME NEXT_PUBLIC_SENTRY_DSN NEXT_PUBLIC_RAZORPAY_KEY_ID APP_VERSION
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM node:22-alpine AS prod
WORKDIR /app
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0 NEXT_TELEMETRY_DISABLED=1
RUN addgroup -g 10001 app && adduser -u 10001 -G app -D app
COPY --from=build /repo/apps/web/.next/standalone ./
COPY --from=build /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=build /repo/apps/web/public ./apps/web/public
USER 10001
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
