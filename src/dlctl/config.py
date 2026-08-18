"""dlctl.config

Carrega o arquivo config/profiles.yaml e variaveis de ambiente (.env), expondo
um objeto `Profile` fortemente tipado.

Autenticacao com o Fabric e delegada ao az CLI (`az account get-access-token`).
Nenhuma credencial MSAL/client_id/secret e necessaria.

permission_scope controla quais acoes sao permitidas:
  - ``contributor``: escrita, execucao, publish (requer role Contributor no workspace).
  - ``read_only``: somente leitura (inventario, gerac?o de notebooks local, dry-run).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
except ImportError:
    pass

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "profiles.yaml"

# Escopos de permissao az CLI para acoes Fabric
PERMISSION_SCOPE_CONTRIBUTOR = "contributor"
PERMISSION_SCOPE_READ_ONLY = "read_only"


class MicrosoftConfig:
    """Configuracao do lado Microsoft Fabric.

    auth_mode suportado: ``az_cli`` (padrao e unico obrigatorio).
    O token e obtido via ``az account get-access-token``.

    permission_scope indica o nivel de acesso que a conta az tem no workspace:
      - ``contributor``: pode criar/atualizar/executar itens Fabric.
      - ``read_only``: somente pode listar/ler. Acoes de escrita sao bloqueadas.
    """

    def __init__(
        self,
        allow_write: bool = False,
        allow_production: bool = False,
        auth_mode: str = "az_cli",
        az_tenant_id: Optional[str] = None,
        permission_scope: str = PERMISSION_SCOPE_READ_ONLY,
        default_workspace_name: Optional[str] = None,
        default_workspace_id: Optional[str] = None,
    ):
        self.allow_write = allow_write
        self.allow_production = allow_production
        self.auth_mode = auth_mode
        self.az_tenant_id = az_tenant_id
        self.permission_scope = permission_scope
        self.default_workspace_name = default_workspace_name
        self.default_workspace_id = default_workspace_id

    @property
    def is_read_only(self) -> bool:
        return self.permission_scope == PERMISSION_SCOPE_READ_ONLY

    @property
    def is_contributor(self) -> bool:
        return self.permission_scope == PERMISSION_SCOPE_CONTRIBUTOR

    @property
    def scope_label(self) -> str:
        if self.is_contributor:
            return "Contributor (escrita/execucao habilitadas)"
        return "Read-only (somente leitura ? acoes de escrita bloqueadas)"

    def __repr__(self) -> str:
        return (
            f"MicrosoftConfig(auth_mode={self.auth_mode!r}, "
            f"permission_scope={self.permission_scope!r}, "
            f"workspace={self.default_workspace_name!r}, "
            f"allow_write={self.allow_write})"
        )


class OracleConfig:
    def __init__(
        self,
        dsn: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        bip_base_url: Optional[str] = None,
        bip_user: Optional[str] = None,
        bip_password: Optional[str] = None,
    ):
        self.dsn = dsn
        self.user = user
        self.password = password
        self.bip_base_url = bip_base_url
        self.bip_user = bip_user
        self.bip_password = bip_password


class ResolvedPaths:
    def __init__(
        self,
        state_root: Path,
        evidence_root: Path,
        manifests_root: Path,
        mappings_root: Path,
        notebooks_silver_root: Path,
        notebooks_gold_root: Path,
    ):
        self.state_root = state_root
        self.evidence_root = evidence_root
        self.manifests_root = manifests_root
        self.mappings_root = mappings_root
        self.notebooks_silver_root = notebooks_silver_root
        self.notebooks_gold_root = notebooks_gold_root

    def model_dump(self) -> dict:
        return {k: str(v) for k, v in self.__dict__.items()}


class PathsConfig:
    state_root: str = "state"
    evidence_root: str = "state/evidence"
    manifests_root: str = "manifests"
    mappings_root: str = "mappings"
    notebooks_silver_root: str = "notebooks/silver"
    notebooks_gold_root: str = "notebooks/gold"

    def __init__(self, **kwargs):
        for key in ("state_root", "evidence_root", "manifests_root",
                    "mappings_root", "notebooks_silver_root", "notebooks_gold_root"):
            setattr(self, key, kwargs.get(key, getattr(PathsConfig, key)))

    def resolve(self, root: Path) -> ResolvedPaths:
        return ResolvedPaths(
            state_root=root / self.state_root,
            evidence_root=root / self.evidence_root,
            manifests_root=root / self.manifests_root,
            mappings_root=root / self.mappings_root,
            notebooks_silver_root=root / self.notebooks_silver_root,
            notebooks_gold_root=root / self.notebooks_gold_root,
        )


class Profile:
    def __init__(
        self,
        name: str,
        description: str = "",
        environment: str = "DEV",
        microsoft: Optional[MicrosoftConfig] = None,
        oracle: Optional[OracleConfig] = None,
        paths: Optional[ResolvedPaths] = None,
    ):
        self.name = name
        self.description = description
        self.environment = environment
        self.microsoft = microsoft or MicrosoftConfig()
        self.oracle = oracle or OracleConfig()
        self.paths = paths  # type: ignore[assignment]


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
    """Carrega um profile do config/profiles.yaml, resolvendo variaveis de ambiente."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Arquivo de configuracao nao encontrado: {CONFIG_PATH}")

    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    profiles = raw.get("profiles", {})

    name = profile_name or os.environ.get("DLCTL_PROFILE") or next(iter(profiles), None)
    if not name or name not in profiles:
        raise KeyError(f"Profile '{name}' nao encontrado em {CONFIG_PATH}")

    data = profiles[name]
    ms_raw = data.get("microsoft", {})
    oracle_raw = data.get("oracle", {})
    paths_raw = data.get("paths", {})

    permission_scope = (
        _env("FABRIC_AZ_PERMISSION_SCOPE")
        or ms_raw.get("permission_scope", PERMISSION_SCOPE_READ_ONLY)
    )

    microsoft = MicrosoftConfig(
        allow_write=_env_bool("DLCTL_ALLOW_WRITE", ms_raw.get("allow_write", False)),
        allow_production=_env_bool("DLCTL_ALLOW_PRODUCTION", ms_raw.get("allow_production", False)),
        auth_mode=ms_raw.get("auth_mode", "az_cli"),
        az_tenant_id=_env("FABRIC_AZ_TENANT_ID") or ms_raw.get("az_tenant_id"),
        permission_scope=permission_scope,
        default_workspace_name=_env(ms_raw.get("default_workspace_name_env")),
        default_workspace_id=_env(ms_raw.get("default_workspace_id_env")),
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
