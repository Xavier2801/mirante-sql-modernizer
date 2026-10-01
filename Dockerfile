# Estágio 1: Builder com uv e compilação de dependências
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Copia manifestos de dependências primeiro (cache eficiente de camadas)
COPY pyproject.toml uv.lock* ./

# Instala dependências de produção sem instalar o projeto em modo editável
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Estágio 2: Runtime enxuto para execução
FROM python:3.14-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Cria usuário não-root por boas práticas de segurança
RUN useradd -m -u 1000 appuser

# Copia o ambiente virtual preparado no estágio anterior
COPY --from=builder /app/.venv /app/.venv

# Copia o código-fonte da aplicação
COPY src/ /app/src/

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Executa o servidor FastAPI com workers Uvicorn
CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]