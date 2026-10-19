FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.9.8
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --extra models --extra trace --no-dev --no-install-project \
    && useradd --create-home --uid 10001 knowledgeops \
    && mkdir -p /app/data /home/knowledgeops/.cache \
    && chown -R knowledgeops:knowledgeops /app /home/knowledgeops
ENV PATH="/app/.venv/bin:$PATH" KO_DATA_DIR=/app/data HF_HOME=/home/knowledgeops/.cache/huggingface
COPY --chown=knowledgeops:knowledgeops src ./src
RUN uv sync --frozen --extra models --extra trace --no-dev
COPY --chown=knowledgeops:knowledgeops scripts ./scripts
COPY --chown=knowledgeops:knowledgeops examples ./examples
USER knowledgeops
EXPOSE 8000
CMD ["uvicorn", "knowledgeops.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
