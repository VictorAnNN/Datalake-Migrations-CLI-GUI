# syntax=docker/dockerfile:1
# Imagem única (Linux) que roda de forma idêntica em hosts Windows e Linux,
# pois o Docker Desktop/Engine sempre executa o container em um kernel Linux.
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# Dependências de sistema:
# - build-essential/libpq-dev: compilar eventuais wheels nativos
# - curl/gnupg/lsb-release: pré-requisitos do instalador do Azure CLI
# Azure CLI é opcional (usado só por FABRIC_AUTH_MODE=azure_cli), mas fica
# disponível na imagem para permitir `az login` dentro do container.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ca-certificates \
        gnupg \
        lsb-release \
    && curl -sL https://aka.ms/InstallAzureCLIDeb | bash \
    && apt-get purge -y --auto-remove gnupg lsb-release \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

# Instala o pacote com todos os extras necessários para uso completo (Oracle + dashboard).
RUN pip install --no-cache-dir -e ".[oracle,dashboard,dev]"

COPY . .

EXPOSE 8501

# Healthcheck simples do dashboard Streamlit quando ele estiver rodando.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; \
        urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=3)" || exit 1

ENTRYPOINT ["dlctl"]
CMD ["dashboard", "--port", "8501"]
