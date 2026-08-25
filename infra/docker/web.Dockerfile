# Forge web image
#
# Multi-stage build: install dependencies, build the Next.js app, and serve
# the production output in a slim runtime image.

FROM node:24-alpine AS deps
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml* ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --filter @forge/web... --frozen-lockfile

FROM node:24-alpine AS builder
WORKDIR /app
RUN corepack enable
COPY --from=deps /app /app
COPY apps/web/ apps/web/
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
