"""dlctl.core.secrets

Utilitários de redação de segredos — nenhum payload de evidência ou log deve
conter valores sensíveis. Espelha a regra "HONESTY / never print secrets" das
skills fabric-full-agent e variable_libraries_workflow.
"""
from __future__ import annotations

import re
from typing import Any

SECRET_KEY_PATTERN = re.compile(
    r"(secret|password|senha|token|bearer|client_secret|apikey|api_key|"
    r"connectionstring|private_key|access_key)",
    re.IGNORECASE,
)

REDACTED = "***REDACTED***"


def is_secret_like_name(name: str) -> bool:
    return bool(SECRET_KEY_PATTERN.search(name or ""))


def redact(value: Any) -> Any:
    """Redige recursivamente chaves que parecem segredo em dicts/listas."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if is_secret_like_name(str(k)):
                out[k] = REDACTED
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def assert_no_secret_like(name: str, value: str | None = None) -> None:
    """Levanta erro se o nome (ou valor) parecer um segredo.

    Usado por Variable Libraries e manifests: uma Variable Library nunca deve
    guardar segredos (usar Key Vault reference em vez disso).
    """
    if is_secret_like_name(name):
        raise ValueError(
            f"Nome '{name}' parece um segredo. Use uma Key Vault reference "
            "(connectionId/secretName/version) em vez de um valor literal."
        )
    if value and SECRET_KEY_PATTERN.search(value):
        raise ValueError(f"Valor de '{name}' parece conter um segredo literal; recusado.")
