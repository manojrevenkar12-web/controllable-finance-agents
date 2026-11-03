FROM node:22-slim AS web
WORKDIR /web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml ./
COPY cfa/ cfa/
RUN uv pip install --system --no-cache . confluent-kafka
COPY config/ config/
COPY prompts/ prompts/
COPY --from=web /web/dist web/dist
RUN useradd --create-home cfa && chown -R cfa /app
USER cfa
EXPOSE 8080
CMD ["cfa", "serve", "--host", "0.0.0.0", "--port", "8080"]
