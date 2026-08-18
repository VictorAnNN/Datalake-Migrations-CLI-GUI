"""dlctl.auth.fabric_auth

Autenticacao contra a Fabric REST API via az CLI.

O token e obtido com ``az account get-access-token``:

    az account get-access-token \
        --resource https://api.fabric.microsoft.com \
        [--tenant <tenant_id>]

Sem credenciais MSAL, client_id ou secret. O az CLI ja gerencia o login
interativo. Se o usuario nao estiver autenticado, ``az_login_device_code()``
inicia o fluxo device code e retorna o codigo/URL para exibicao no front-end.
"""
from __future__ import annotations

import json
import subprocess
from typing import Optional

FABRIC_RESOURCE = "https://api.fabric.microsoft.com"


class FabricAuthError(RuntimeError):
    pass


class AzCliAuth:
    """Obtem token Bearer para a Fabric API usando o az CLI ja autenticado.

    Args:
        tenant_id: Se informado, passa ``--tenant <tenant_id>`` ao az CLI.
                   Util quando a conta az tem acesso a multiplos tenants.
    """

    def __init__(self, resource: str = FABRIC_RESOURCE, tenant_id: Optional[str] = None):
        self.resource = resource
        self.tenant_id = tenant_id

    def get_token(self) -> str:
        """Retorna o access token como string. Levanta FabricAuthError se falhar."""
        cmd = ["az", "account", "get-access-token", "--resource", self.resource]
        if self.tenant_id:
            cmd += ["--tenant", self.tenant_id]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except FileNotFoundError:
            raise FabricAuthError(
                "az CLI nao encontrado. Instale via: https://aka.ms/installazurecli"
            )
        except subprocess.TimeoutExpired:
            raise FabricAuthError("Timeout ao chamar 'az account get-access-token'.")

        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise FabricAuthError(
                f"'az account get-access-token' falhou (exit {result.returncode}).
"
                f"{stderr}

"
                "Execute 'az login' para autenticar, entao tente novamente."
            )

        try:
            payload = json.loads(result.stdout)
            token: Optional[str] = payload.get("accessToken")
        except (json.JSONDecodeError, AttributeError):
            raise FabricAuthError(
                f"Resposta inesperada do az CLI: {result.stdout[:200]}"
            )

        if not token:
            raise FabricAuthError(
                "az CLI retornou JSON mas sem 'accessToken'. "
                "Verifique se a conta esta autenticada: 'az account show'."
            )

        return token

    def get_account_info(self) -> Optional[dict]:
        """Retorna informacoes da conta az ativa, ou None se nao autenticado."""
        try:
            result = subprocess.run(
                ["az", "account", "show"], capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
        return None


def az_login_device_code(tenant_id: Optional[str] = None) -> dict:
    """Inicia ``az login --use-device-code`` bloqueante e retorna resultado.

    Roda de forma sincrona (bloqueia ate o usuario autenticar ou timeout).
    No Streamlit, chame dentro de st.spinner().

    Returns:
        dict com chaves:
          - ``ok`` (bool): True se o login foi concluido com sucesso.
          - ``message`` (str): Mensagem ou erro.
          - ``user`` (str | None): e-mail da conta logada se ok=True.
    """
    cmd = ["az", "login", "--use-device-code"]
    if tenant_id:
        cmd += ["--tenant", tenant_id]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except FileNotFoundError:
        return {"ok": False, "message": "az CLI nao encontrado. Instale via: https://aka.ms/installazurecli", "user": None}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "Timeout aguardando az login (3 min). Tente novamente.", "user": None}

    if result.returncode != 0:
        return {"ok": False, "message": result.stderr.strip() or "Falha no az login.", "user": None}

    try:
        accounts = json.loads(result.stdout)
        if isinstance(accounts, list) and accounts:
            user = accounts[0].get("user", {}).get("name", "?")
        else:
            user = "?"
        return {"ok": True, "message": "Login realizado com sucesso.", "user": user}
    except (json.JSONDecodeError, AttributeError):
        return {"ok": True, "message": "Login realizado.", "user": None}


# Retrocompatibilidade com FabricAuth(profile)
class FabricAuth:
    """Wrapper de compatibilidade -- delega para AzCliAuth, respeitando tenant do profile."""

    def __init__(self, profile=None):
        tenant_id = getattr(getattr(profile, "microsoft", None), "az_tenant_id", None)
        self._auth = AzCliAuth(tenant_id=tenant_id)

    def get_token(self) -> str:
        return self._auth.get_token()
