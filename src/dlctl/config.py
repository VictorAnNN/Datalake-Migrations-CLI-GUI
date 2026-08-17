"""dlctl.config

Carrega o arquivo config/profiles.yaml e variáveis de ambiente (.env), expondo
um objeto `Profile` fortemente tipado — equivalente ao `accountctl profile show`
mencionado nas skills, mas local e autocontido.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "profiles.yaml"

load_dotenv(PROJECT_ROOT / ".env", override=False)


class MicrosoftConfig(BaseModel):
    allow_write: bool = False
    allow_production: bool = False
    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    auth_mode: str = "device_code"
    default_workspace_name: Optional[str] = None
    default_workspace_id: Optional[str] = None
    scopes: list[str] = Field(default_factory=list)


class OracleConfig(BaseModel):
    dsn: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None
    bip_base_url: Optional[str] = None
    bip_user: Optional[str] = None
    bip_password: Optional[str] = None


class PathsConfig(BaseModel):
    state_root: str = "state"
    evidence_root: str = "state/evidence"
    manifests_root: str = "manifests"
    mappings_root: str = "mappings"
    notebooks_silver_root: str = "notebooks/silver"
    notebooks_gold_root: str = "notebooks/gold"

    def resolve(self, root: Path) -> "ResolvedPaths":
        return ResolvedPaths(
            state_root=root / self.state_root,
            evidence_root=root / self.evidence_root,
            manifests_root=root / self.manifests_root,
            mappings_root=root / self.mappings_root,
            notebooks_silver_root=root / self.notebooks_silver_root,
            notebooks_gold_root=root / self.notebooks_gold_root,
        )


class ResolvedPaths(BaseModel):
    state_root: Path
    evidence_root: Path
    manifests_root: Path
    mappings_root: Path
    notebooks_silver_root: Path
    notebooks_gold_root: Path


class Profile(BaseModel):
    name: str
    description: str = ""
    environment: str = "DEV"
    microsoft: MicrosoftConfig
    oracle: OracleConfig
    paths: ResolvedPaths


def _env(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    return os.environ.get(name) or None


def _env_bool(name: Optional[str], default: bool) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=8)
def load_profile(profile_name: Optional[str] = None) -> Profile:
    """Carrega um profile do config/profiles.yaml, resolvendo variáveis de ambiente."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Arquivo de configuração não encontrado: {CONFIG_PATH}")

    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    profiles = raw.get("profiles", {})

    name = profile_name or os.environ.get("DLCTL_PROFILE") or next(iter(profiles), None)
    if not name or name not in profiles:
        raise KeyError(f"Profile '{name}' não encontrado em {CONFIG_PATH}")

    data = profiles[name]
    ms_raw = data.get("microsoft", {})
    oracle_raw = data.get("oracle", {})
    paths_raw = data.get("paths", {})

    microsoft = MicrosoftConfig(
        allow_write=_env_bool("DLCTL_ALLOW_WRITE", ms_raw.get("allow_write", False)),
        allow_production=_env_bool("DLCTL_ALLOW_PRODUCTION", ms_raw.get("allow_production", False)),
        tenant_id=_env(ms_raw.get("tenant_id_env")),
        client_id=_env(ms_raw.get("client_id_env")),
        client_secret=_env(ms_raw.get("client_secret_env")),
        auth_mode=_env(ms_raw.get("auth_mode_env")) or "device_code",
        default_workspace_name=_env(ms_raw.get("default_workspace_name_env")),
        default_workspace_id=_env(ms_raw.get("default_workspace_id_env")),
        scopes=ms_raw.get("scopes", []),
    )
    oracle = OracleConfig(
        dsn=_env(oracle_raw.get("dsn_env")),
        user=_env(oracle_raw.get("user_env")),
        password=_env(oracle_raw.get("password_env")),
        bip_base_url=_env(oracle_raw.get("bip_base_url_env")),
        bip_user=_env(oracle_raw.get("bip_user_env")),
        bip_password=_env(oracle_raw.get("bip_password_env")),
    )
    paths = PathsConfig(**paths_raw).resolve(PROJECT_ROOT)
    for p in [paths.state_root, paths.evidence_root, paths.manifests_root,
              paths.mappings_root, paths.notebooks_silver_root, paths.notebooks_gold_root]:
        p.mkdir(parents=True, exist_ok=True)

    return Profile(
        name=name,
        description=data.get("description", ""),
        environment=data.get("environment", "DEV"),
        microsoft=microsoft,
        oracle=oracle,
        paths=paths,
    )


def load_domains() -> dict:
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    return raw.get("domains", {})
