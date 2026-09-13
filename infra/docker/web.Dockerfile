# Forge web image
#
# Multi-stage build: install dependencies, build the Next.js app, and serve
# the production output in a slim runtime image.

FROM node:24-alpine AS deps
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml* ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile

FROM node:24-alpine AS builder
WORKDIR /app
RUN corepack enable
COPY --from=deps /app /app
COPY apps/web/ apps/web/
# Runtime API URLs are read server-side per request (see lib/urls.ts),
# so the build only needs placeholders.
ARG API_BASE_URL=http://api:8000
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV API_BASE_URL=${API_BASE_URL}
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
RUN pnpm --filter @forge/web build

FROM node:24-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN corepack enable

COPY --from=builder /app/apps/web/ ./apps/web/
COPY --from=builder /app/node_modules/ ./node_modules/
COPY --from=builder /app/apps/web/.next ./apps/web/.next

EXPOSE 3000
WORKDIR /app/apps/web
CMD ["pnpm", "start"]
