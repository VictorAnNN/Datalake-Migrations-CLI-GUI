"""dlctl.auth.fabric_auth

Autenticação real contra o Microsoft Entra ID / Fabric REST API.
Suporta três modos, conforme configurado no profile (FABRIC_AUTH_MODE):

- ``azure_cli`` (recomendado/padrão para uso local): reaproveita a sessão já
  aberta via ``az login`` no Azure CLI, sem exigir App Registration própria
  (nem tenant_id/client_id/client_secret). É a forma padrão de conexão entre
  as ações do CLI-GUI e o Azure/Fabric.
- ``device_code``: fluxo interativo MSAL (usuário loga no navegador).
- ``client_credentials``: MSAL aplicação/serviço (client_id + client_secret).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import msal

from dlctl.config import Profile

TOKEN_CACHE_DIR = ".token_cache"

DEFAULT_FABRIC_RESOURCE = "https://api.fabric.microsoft.com"


class FabricAuthError(RuntimeError):
    pass


def find_azure_cli() -> str:
    """Localiza o executável do Azure CLI (`az`), inclusive no caminho padrão do Windows."""
    azure_cli = shutil.which("az")
    if azure_cli:
        return azure_cli

    import os

    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    default_path = Path(program_files) / "Microsoft SDKs" / "Azure" / "CLI2" / "wbin" / "az.cmd"
    if default_path.is_file():
        return str(default_path)

    raise FabricAuthError(
        "Azure CLI não encontrado. Instale-o (winget install --exact --id Microsoft.AzureCLI) "
        "e execute 'az login'."
    )


def get_azure_cli_token(resource: str = DEFAULT_FABRIC_RESOURCE) -> str:
    """Obtém um access token via Azure CLI (`az account get-access-token`).

    Não requer App Registration nem client secret: usa a sessão iniciada por
    `az login` / `az account set --subscription ...` no ambiente local.
    """
    try:
        result = subprocess.run(
            [
                find_azure_cli(), "account", "get-access-token",
                "--resource", resource,
                "--query", "accessToken",
                "--output", "tsv",
            ],
            check=False,
            capture_output=True,
            text=True,
            shell=False,
        )
    except FileNotFoundError as error:
        raise FabricAuthError("Azure CLI não encontrado. Instale-o e execute 'az login'.") from error

    token = result.stdout.strip()
    if result.returncode or not token:
        detail = result.stderr.strip() or "Execute 'az login' com a conta que acessa o workspace."
        raise FabricAuthError(f"Não foi possível obter o token do Azure CLI: {detail}")
    return token


class FabricAuth:
    def __init__(self, profile: Profile):
        self.profile = profile
        ms = profile.microsoft
        self.scopes = ms.scopes or ["https://api.fabric.microsoft.com/.default"]

        if ms.auth_mode == "azure_cli":
            # Não exige App Registration: usa a sessão do `az login` local.
            self._app = None
            return

        if not ms.tenant_id or not ms.client_id:
            raise FabricAuthError(
                "FABRIC_TENANT_ID/FABRIC_CLIENT_ID não configurados. Preencha o .env (veja .env.example), "
                "ou use FABRIC_AUTH_MODE=azure_cli para autenticar apenas com 'az login'."
            )
        self.authority = f"https://login.microsoftonline.com/{ms.tenant_id}"
        self._cache_path = profile.paths.state_root / TOKEN_CACHE_DIR
        self._cache_path.mkdir(parents=True, exist_ok=True)
        self._token_cache_file = self._cache_path / f"{profile.name}.bin"
        self._app = self._build_app()

    def _serializable_cache(self) -> msal.SerializableTokenCache:
        cache = msal.SerializableTokenCache()
        if self._token_cache_file.exists():
            cache.deserialize(self._token_cache_file.read_text(encoding="utf-8"))
        return cache

    def _persist_cache(self, cache: msal.SerializableTokenCache) -> None:
        if cache.has_state_changed:
            self._token_cache_file.write_text(cache.serialize(), encoding="utf-8")

    def _build_app(self):
        ms = self.profile.microsoft
        cache = self._serializable_cache()
        if ms.auth_mode == "client_credentials":
            if not ms.client_secret:
                raise FabricAuthError("FABRIC_CLIENT_SECRET ausente para auth_mode=client_credentials.")
            return msal.ConfidentialClientApplication(
                client_id=ms.client_id, client_credential=ms.client_secret,
                authority=self.authority, token_cache=cache,
            )
        return msal.PublicClientApplication(
            client_id=ms.client_id, authority=self.authority, token_cache=cache,
        )

    def _azure_cli_resource(self) -> str:
        scope = self.scopes[0] if self.scopes else DEFAULT_FABRIC_RESOURCE
        return scope.removesuffix("/.default") or DEFAULT_FABRIC_RESOURCE

    def get_token(self) -> str:
        ms = self.profile.microsoft
        if ms.auth_mode == "azure_cli":
            return get_azure_cli_token(self._azure_cli_resource())
        if ms.auth_mode == "client_credentials":
            result = self._app.acquire_token_for_client(scopes=self.scopes)
        else:
            accounts = self._app.get_accounts()
            result = None
            if accounts:
                result = self._app.acquire_token_silent(self.scopes, account=accounts[0])
            if not result:
                flow = self._app.initiate_device_flow(scopes=self.scopes)
                if "user_code" not in flow:
                    raise FabricAuthError(f"Falha ao iniciar device flow: {flow}")
                print(flow["message"])  # instrução para o usuário logar no navegador
                result = self._app.acquire_token_by_device_flow(flow)
        self._persist_cache(self._app.token_cache)  # type: ignore[arg-type]
        if not result or "access_token" not in result:
            raise FabricAuthError(f"Falha de autenticação: {result.get('error_description') if result else 'sem resposta'}")
        return result["access_token"]
