"""dlctl.auth.fabric_auth

Autenticação real contra o Microsoft Entra ID / Fabric REST API usando MSAL.
Suporta device_code (usuário interativo) e client_credentials (aplicação/serviço),
conforme configurado no profile (FABRIC_AUTH_MODE).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import msal

from dlctl.config import Profile

TOKEN_CACHE_DIR = ".token_cache"


class FabricAuthError(RuntimeError):
    pass


class FabricAuth:
    def __init__(self, profile: Profile):
        self.profile = profile
        ms = profile.microsoft
        if not ms.tenant_id or not ms.client_id:
            raise FabricAuthError(
                "FABRIC_TENANT_ID/FABRIC_CLIENT_ID não configurados. Preencha o .env (veja .env.example)."
            )
        self.authority = f"https://login.microsoftonline.com/{ms.tenant_id}"
        self.scopes = ms.scopes or ["https://api.fabric.microsoft.com/.default"]
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

    def get_token(self) -> str:
        ms = self.profile.microsoft
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
