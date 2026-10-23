FROM node:22-bookworm-slim AS web
ARG NPM_CONFIG_REGISTRY=https://registry.npmjs.org
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --registry "$NPM_CONFIG_REGISTRY"
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
ARG APT_MIRROR=
RUN if [ -n "$APT_MIRROR" ]; then \
      sed -i "s|http://deb.debian.org/debian|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=pypi.org
RUN pip install --no-cache-dir -i "$PIP_INDEX_URL" --trusted-host "$PIP_TRUSTED_HOST" -r requirements.txt
COPY alembic.ini h3_client.py ./
COPY server server
COPY ontology ontology
COPY skills skills
COPY docs docs
COPY assets assets
COPY scripts scripts
# CLI packages: built by CI (tools/dist). Optional here; can also be mounted and pointed to with CVGEN_RELEASES.
COPY tools tools
RUN mkdir -p tools/dist
COPY --from=web /web/dist web/dist
COPY deploy/entrypoint.sh /entrypoint.sh
RUN useradd --create-home --uid 10001 cvgen \
    && chown -R cvgen /app \
    && chmod 755 /entrypoint.sh
ENV PYTHONPATH=/app CVGEN_DATA=/data
ENTRYPOINT ["/entrypoint.sh"]
CMD ["api"]
