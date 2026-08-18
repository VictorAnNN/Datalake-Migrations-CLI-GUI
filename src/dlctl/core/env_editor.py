"""dlctl.core.env_editor

Leitura/escrita segura do `.env` e do `config/profiles.yaml`, para uso pela
página de Configuração do dashboard. Regras de segurança:

- Segredos (client secret, senhas) NUNCA são lidos de volta para exibição —
  a UI só mostra se já estão configurados (booleano), nunca o valor.
- Escrever uma chave de segredo com valor vazio NÃO apaga o valor existente
  (evita apagar acidentalmente ao deixar o campo em branco no formulário).
- Todo write recarrega o cache de `load_profile` para refletir imediatamente.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from dlctl.config import CONFIG_PATH, PROJECT_ROOT, load_profile

ENV_PATH = PROJECT_ROOT / ".env"

SECRET_ENV_KEYS = {"ORACLE_DB_PASSWORD", "ORACLE_BIP_PASSWORD"}

ALL_ENV_KEYS = [
    "DLCTL_PROFILE",
    "FABRIC_WORKSPACE_NAME", "FABRIC_WORKSPACE_ID",
    "FABRIC_AZ_TENANT_ID", "FABRIC_AZ_PERMISSION_SCOPE",
    "ORACLE_DB_DSN", "ORACLE_DB_USER", "ORACLE_DB_PASSWORD",
    "ORACLE_BIP_BASE_URL", "ORACLE_BIP_USER", "ORACLE_BIP_PASSWORD",
    "DLCTL_ALLOW_WRITE", "DLCTL_ALLOW_PRODUCTION",
]


def read_env_raw() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}
    values: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        k, v = stripped.split("=", 1)
        values[k.strip()] = v.strip()
    return values


def read_env_for_form() -> dict[str, str]:
    """Retorna valores atuais, mas com segredos sempre em branco (nunca
    reexibidos), para preencher um formulário de edição com segurança."""
    raw = read_env_raw()
    out = {}
    for key in ALL_ENV_KEYS:
        out[key] = "" if key in SECRET_ENV_KEYS else raw.get(key, "")
    return out


def secret_status() -> dict[str, bool]:
    """Retorna quais variáveis de segredo Oracle estão configuradas (sem expor os valores)."""
    raw = read_env_raw()
    return {k: bool(raw.get(k)) for k in SECRET_ENV_KEYS}


def update_env(updates: dict[str, str]) -> None:
    """Atualiza/adiciona chaves no `.env`, preservando linhas/comentários
    existentes. Chaves de segredo com valor vazio são ignoradas (não apagam
    o segredo já salvo)."""
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    to_write = {k: v for k, v in updates.items() if not (k in SECRET_ENV_KEYS and v == "")}

    seen: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in to_write:
                new_lines.append(f"{key}={to_write[key]}")
                seen.add(key)
                continue
        new_lines.append(line)
    for key, value in to_write.items():
        if key not in seen:
            new_lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    load_profile.cache_clear()


def read_profiles_yaml() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {"profiles": {}, "domains": {}}


def write_profiles_yaml(data: dict) -> None:
    CONFIG_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    load_profile.cache_clear()


def update_profile_flags(profile_name: str, allow_write: bool, allow_production: bool,
                          workspace_name: str, workspace_id: str, environment: str) -> None:
    data = read_profiles_yaml()
    profiles = data.setdefault("profiles", {})
    prof = profiles.setdefault(profile_name, {})
    ms = prof.setdefault("microsoft", {})
    ms["allow_write"] = allow_write
    ms["allow_production"] = allow_production
    prof["environment"] = environment
    write_profiles_yaml(data)
    # workspace name/id são armazenados via .env (referenciados por *_env em profiles.yaml)
    update_env({"FABRIC_WORKSPACE_NAME": workspace_name, "FABRIC_WORKSPACE_ID": workspace_id})


def list_domains() -> dict:
    return read_profiles_yaml().get("domains", {})


def upsert_domain(domain_key: str, description: str, folder_path: str,
                   silver_lakehouse: str, gold_lakehouse: str) -> None:
    data = read_profiles_yaml()
    domains = data.setdefault("domains", {})
    domains[domain_key] = {
        "description": description,
        "folder_path": folder_path,
        "silver_lakehouse": silver_lakehouse,
        "gold_lakehouse": gold_lakehouse,
    }
    write_profiles_yaml(data)


def delete_domain(domain_key: str) -> None:
    data = read_profiles_yaml()
    domains = data.get("domains", {})
    domains.pop(domain_key, None)
    write_profiles_yaml(data)
