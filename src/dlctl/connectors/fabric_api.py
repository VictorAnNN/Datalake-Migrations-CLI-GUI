"""dlctl.connectors.fabric_api

Cliente REST real para a Microsoft Fabric API (api.fabric.microsoft.com),
cobrindo os recursos citados nas skills: workspaces, items, lakehouses,
notebooks, pipelines, dataflows, copy jobs, definitions, environments, git,
variable libraries. Toda chamada mutante passa pelo Central Write Gate
(dlctl.core.gates) antes de ser emitida.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Optional

import requests

from dlctl.auth.fabric_auth import FabricAuth
from dlctl.config import Profile
from dlctl.core.secrets import redact
from dlctl.core.state import cache_item, get_cached_item, log_activity

FABRIC_BASE_URL = "https://api.fabric.microsoft.com/v1"

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
TRANSIENT_EXC = (requests.exceptions.ConnectionError, requests.exceptions.Timeout)


class FabricApiError(RuntimeError):
    def __init__(self, message: str, status_code: Optional[int] = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class FabricClient:
    """Cliente HTTP para a Fabric REST API. Toda chamada de escrita (POST/PATCH/
    PUT/DELETE) exige um GateContext.authorize_write()/authorize_execute() ter
    sido chamado no comando antes de instanciar/usar este método -- este
    cliente por si só não decide autorização de negócio, apenas transporte."""

    def __init__(self, profile: Profile, workspace_id: Optional[str] = None):
        self.profile = profile
        self.workspace_id = workspace_id or profile.microsoft.default_workspace_id
        self._auth = FabricAuth(profile)
        self._session = requests.Session()

    # ---------------- transport ----------------

    def _headers(self) -> dict:
        token = self._auth.get_token()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _request(self, method: str, path: str, is_write: bool = False, **kwargs) -> requests.Response:
        url = path if path.startswith("http") else f"{FABRIC_BASE_URL}{path}"
        headers = kwargs.pop("headers", {}) or {}
        headers = {**self._headers(), **headers}

        attempts = 4 if method.upper() in {"GET", "HEAD", "OPTIONS"} else 1
        # mutações só podem ser re-tentadas em 429 (throttled = nunca aplicado)
        if is_write:
            attempts = 1

        last_exc: Optional[Exception] = None
        for attempt in range(attempts):
            try:
                resp = self._session.request(method, url, headers=headers, timeout=60, **kwargs)
                if resp.status_code in RETRYABLE_STATUS and attempt < attempts - 1:
                    if is_write and resp.status_code != 429:
                        break
                    # retro: throttling — log cada retry para o detector 'throttling'
                    # (grupo por tool/rota) do motor de análise (core/retro.py)
                    log_activity(
                        self.profile,
                        f"HTTP {resp.status_code} retry {attempt + 1}/{attempts} after {[1, 2, 4][min(attempt, 2)]}s",
                        level="WARN", source="fabric_api.retry",
                    )
                    time.sleep([1, 2, 4][min(attempt, 2)])
                    continue
                if resp.status_code >= 400:
                    raise FabricApiError(
                        f"{method} {path} -> HTTP {resp.status_code}: {resp.text[:500]}",
                        status_code=resp.status_code,
                        payload=redact(_safe_json(resp)),
                    )
                return resp
            except TRANSIENT_EXC as exc:
                last_exc = exc
                if attempt < attempts - 1:
                    time.sleep([1, 2, 4][min(attempt, 2)])
                    continue
                raise FabricApiError(f"Falha de transporte em {method} {path}: {exc}") from exc
        if last_exc:
            raise FabricApiError(f"Falha de transporte em {method} {path}: {last_exc}") from last_exc
        raise FabricApiError(f"Falha não recuperável em {method} {path}")

    def get(self, path: str, **kwargs) -> dict:
        return _safe_json(self._request("GET", path, **kwargs))

    def post(self, path: str, json_body: dict | None = None, **kwargs) -> dict:
        return _safe_json(self._request("POST", path, is_write=True, json=json_body, **kwargs))

    def patch(self, path: str, json_body: dict | None = None, **kwargs) -> dict:
        return _safe_json(self._request("PATCH", path, is_write=True, json=json_body, **kwargs))

    def delete(self, path: str, **kwargs) -> dict:
        return _safe_json(self._request("DELETE", path, is_write=True, **kwargs))

    # ---------------- workspaces / items ----------------

    def list_workspaces(self) -> list[dict]:
        return self.get("/workspaces").get("value", [])

    def resolve_workspace_id(self, name: str) -> str:
        for ws in self.list_workspaces():
            if ws.get("displayName") == name:
                return ws["id"]
        raise FabricApiError(f"Workspace '{name}' não encontrado.")

    def list_items(self, item_type: Optional[str] = None) -> list[dict]:
        params = {"type": item_type} if item_type else {}
        return self.get(f"/workspaces/{self.workspace_id}/items", params=params).get("value", [])

    def find_item_by_name(self, display_name: str, item_type: str) -> Optional[dict]:
        for item in self.list_items(item_type=item_type):
            if item.get("displayName") == display_name:
                return item
        return None

    def resolve_item_cached(self, display_name: str, item_type: str, cache_first: bool = True,
                             max_age_seconds: int = 300) -> Optional[dict]:
        """Resolve um item preferindo o cache local (retro: 'prefer-resolver' —
        evita repetir list_items() ao vivo quando o mesmo item já foi resolvido
        recentemente). `cache_first=False` força consulta ao vivo (equivalente a
        `--refresh`). O item completo só é retornado do cache com seu ID; para
        obter os demais campos após um cache hit, chame novamente com
        cache_first=False se precisar do payload completo."""
        if cache_first:
            cached_id = get_cached_item(self.profile, self.workspace_id, item_type, display_name, max_age_seconds)
            if cached_id:
                log_activity(self.profile, f"cache hit: {item_type}/{display_name}", source="fabric_api.cache")
                return {"id": cached_id, "displayName": display_name, "type": item_type, "_fromCache": True}
        log_activity(self.profile, f"live lookup: {item_type}/{display_name}", source="fabric_api.cache")
        item = self.find_item_by_name(display_name, item_type)
        if item:
            cache_item(self.profile, self.workspace_id, item_type, display_name, item["id"])
        return item

    def list_folders(self) -> list[dict]:
        return self.get(f"/workspaces/{self.workspace_id}/folders").get("value", [])

    def resolve_folder(self, folder_path: str) -> Optional[str]:
        """Resolve um folderPath tipo 'pipelines/SUPRIMENTOS' para folderId,
        percorrendo a árvore de pastas do workspace."""
        parts = [p for p in folder_path.split("/") if p]
        folders = self.list_folders()
        by_id = {f["id"]: f for f in folders}
        current_parent = None
        current_id = None
        for part in parts:
            match = next(
                (f for f in folders if f.get("displayName") == part and f.get("parentFolderId") == current_parent),
                None,
            )
            if not match:
                return None
            current_id = match["id"]
            current_parent = current_id
        return current_id

    def create_item(self, display_name: str, item_type: str, folder_id: Optional[str],
                     definition: Optional[dict] = None, description: str = "") -> dict:
        body: dict[str, Any] = {"displayName": display_name, "type": item_type, "description": description}
        if folder_id:
            body["folderId"] = folder_id
        if definition:
            body["definition"] = definition
        return self.post(f"/workspaces/{self.workspace_id}/items", json_body=body)

    def ensure_item(self, resource_type: str, display_name: str, folder_id: Optional[str],
                     definition_file: Optional[str], source_dir: Path) -> dict:
        """Cria (ou seria: atualiza) um item Fabric a partir de um arquivo de
        definição local, para uso pelo manifest engine."""
        definition = None
        if definition_file:
            def_path = (source_dir / definition_file).resolve()
            raw = json.loads(def_path.read_text(encoding="utf-8"))
            definition = {
                "parts": [
                    {
                        "path": def_path.name,
                        "payload": base64.b64encode(json.dumps(raw).encode()).decode(),
                        "payloadType": "InlineBase64",
                    }
                ]
            }
        existing = self.find_item_by_name(display_name, resource_type)
        if existing:
            return self.patch(f"/workspaces/{self.workspace_id}/items/{existing['id']}",
                               json_body={"displayName": display_name})
        return self.create_item(display_name, resource_type, folder_id, definition=definition)

    def get_definition(self, item_id: str) -> dict:
        return self.post(f"/workspaces/{self.workspace_id}/items/{item_id}/getDefinition")

    def get_definition_lro(self, item_id: str, item_type: str = "notebooks", max_polls: int = 20) -> dict:
        """Igual a `get_definition`, mas trata o caso assíncrono (202 Accepted +
        polling em `Location`) usado por itens grandes (ex.: notebooks). Usado
        pela sincronização de linhagem (dlctl.connectors.fabric_notebook_sync)."""
        resp = self._request(
            "POST", f"/workspaces/{self.workspace_id}/{item_type}/{item_id}/getDefinition", is_write=False,
        )
        if resp.status_code != 202:
            return _safe_json(resp).get("definition", _safe_json(resp))

        operation_url = resp.headers.get("Location")
        if not operation_url:
            raise FabricApiError("Fabric iniciou a exportação, mas não retornou a operação para consulta (Location ausente).")

        for _ in range(max_polls):
            retry_after = int(resp.headers.get("Retry-After", "5"))
            time.sleep(min(max(retry_after, 1), 30))
            operation = self._session.request("GET", operation_url, headers=self._headers(), timeout=60)
            if not operation.ok:
                raise FabricApiError(f"Falha ao consultar exportação: {operation.text[:500]}")
            body = _safe_json(operation)
            if body.get("status") == "Succeeded":
                result_url = f"{operation_url.rstrip('/')}/result"
                exported = self._session.request("GET", result_url, headers=self._headers(), timeout=60)
                if not exported.ok:
                    raise FabricApiError(f"Falha ao baixar definição: {exported.text[:500]}")
                return _safe_json(exported).get("definition", _safe_json(exported))
            if body.get("status") in {"Failed", "Cancelled"}:
                raise FabricApiError(f"Exportação terminou com status {body.get('status')}.")
            resp = operation
        raise FabricApiError("A exportação da definição excedeu o tempo de espera.")

    # ---------------- lakehouses ----------------

    def schema_inventory(self, lakehouse_id: str) -> dict:
        return self.get(f"/workspaces/{self.workspace_id}/lakehouses/{lakehouse_id}/tables")

    # ---------------- notebooks / pipelines / dataflows / copy jobs ----------------

    def run_item_job(self, item_id: str, job_type: str = "RunNotebook", parameters: Optional[dict] = None) -> dict:
        """Dispara a execução. A Fabric API responde 202 Accepted com o corpo
        tipicamente vazio e o ID da instância no header `Location`; capturamos
        esse header aqui (`jobInstanceId`) para permitir o polling real de
        status via `job_instance_status`/`poll_job_status` logo em seguida."""
        body = {"executionData": {"parameters": parameters or {}}}
        resp = self._request(
            "POST", f"/workspaces/{self.workspace_id}/items/{item_id}/jobs/instances?jobType={job_type}",
            is_write=True, json=body,
        )
        result = _safe_json(resp)
        location = resp.headers.get("Location", "")
        if location:
            job_instance_id = location.rstrip("/").split("/")[-1]
            result.setdefault("id", job_instance_id)
            result["jobInstanceId"] = job_instance_id
        return result

    def job_instance_status(self, item_id: str, job_instance_id: str) -> dict:
        return self.get(f"/workspaces/{self.workspace_id}/items/{item_id}/jobs/instances/{job_instance_id}")

    # ---------------- pipelines: diagnose-run (Incid. 1, P0) ----------------
    # queryactivityruns é semanticamente uma LEITURA (é um POST só porque a API
    # de atividades do Fabric/ADF exige filtro no corpo), então este método
    # NUNCA passa por authorize_write — registrado aqui como leitura tipada,
    # com resumo padrão em vez de despejar o payload bruto no chat/log.
    def query_activity_runs(self, pipeline_item_id: str, run_id: str,
                             last_updated_after: Optional[str] = None,
                             last_updated_before: Optional[str] = None) -> dict:
        """Consulta as atividades internas de uma execução de pipeline
        (rota oficial `queryactivityruns`). Leitura tipada — substitui o uso
        de `api request` cru citado no Incidente 1."""
        body = {
            "lastUpdatedAfter": last_updated_after or "2000-01-01T00:00:00.000Z",
            "lastUpdatedBefore": last_updated_before or "2999-01-01T00:00:00.000Z",
            "filters": [{"operand": "PipelineRunId", "operator": "Equals", "values": [run_id]}],
        }
        return self.post(
            f"/workspaces/{self.workspace_id}/items/{pipeline_item_id}/jobs/instances/{run_id}/queryactivityruns",
            json_body=body,
        )

    def diagnose_pipeline_run(self, pipeline_item_id: str, run_id: str, failed_only: bool = True) -> dict:
        """Agrega erros/activityRunId/iterationHash/notebook run id/Copy output
        de uma execução, no lugar de despejar o payload bruto de
        `queryactivityruns` (Incid. 1, P0 `pipelines diagnose-run`)."""
        raw = self.query_activity_runs(pipeline_item_id, run_id)
        activities = raw.get("value", raw.get("activityRuns", []))
        diagnosed = []
        for act in activities:
            status = act.get("status", "")
            if failed_only and status not in {"Failed", "Cancelled"}:
                continue
            diagnosed.append({
                "activityName": act.get("activityName"),
                "activityRunId": act.get("activityRunId"),
                "status": status,
                "error": redact(act.get("error", {})),
                "output_summary": redact(act.get("output", {})) if not failed_only else None,
            })
        return {"run_id": run_id, "failed_only": failed_only, "activity_count": len(activities),
                "diagnosed_count": len(diagnosed), "activities": diagnosed}

    # ---------------- jobs: driver-log com wait/retry (Incid. 2, P0) ----------------

    UNKNOWN_APP_MARKERS = ("unknown app", "no available log", "404")

    def driver_log_wait(self, item_id: str, job_instance_id: str, get_log_fn: Optional[Callable] = None,
                         max_attempts: int = 10, poll_seconds: float = 3.0) -> dict:
        """Poll de driver-log que só repete o 404 exato 'unknown app'/'no
        available log' (nunca reprocessa outra falha) e persiste
        tentativa+hash de cada resposta, conforme o incidente 2."""
        attempts_log = []
        fetch = get_log_fn or (lambda: self.get(
            f"/workspaces/{self.workspace_id}/items/{item_id}/jobs/instances/{job_instance_id}/driverLog"
        ))
        for attempt in range(1, max_attempts + 1):
            try:
                result = fetch()
                content_hash = hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()
                attempts_log.append({"attempt": attempt, "status": "ok", "hash": content_hash})
                return {"status": "ok", "log": result, "attempts": attempts_log}
            except FabricApiError as exc:
                msg = str(exc).lower()
                is_unknown_app = any(marker in msg for marker in self.UNKNOWN_APP_MARKERS)
                attempts_log.append({"attempt": attempt, "status": "retry" if is_unknown_app else "fatal", "error": str(exc)})
                if not is_unknown_app:
                    raise
                time.sleep(poll_seconds)
        return {"status": "timeout", "attempts": attempts_log}

    # ---------------- SQL endpoint refresh (Incid. 2, P0 — rota corrigida) ----------------
    # Rota antiga (obsoleta, retornava 400 InvalidJobType):
    #   POST /items/{lakehouseId}/jobs/instances?jobType=RefreshSqlEndpointMetadata
    # Rota correta confirmada na doc oficial do Fabric:
    #   POST /sqlEndpoints/{sqlEndpointId}/refreshMetadata  body: {"recreateTables": false}
    # https://learn.microsoft.com/en-us/rest/api/fabric/sqlendpoint/items/refresh-sql-endpoint-metadata
    def refresh_sql_endpoint_metadata(self, sql_endpoint_id: str, recreate_tables: bool = False,
                                       require_visible: bool = False, expected_tables: Optional[list[str]] = None,
                                       poll_seconds: float = 2.0, timeout_seconds: float = 60.0) -> dict:
        """Dispara o refresh do SQL endpoint pela rota correta. Se
        `require_visible=True`, NÃO trata HTTP 200 como sucesso quando alguma
        tabela esperada aparece como `NotRun`/ausente na resposta — reporta
        `status=INCOMPLETE` em vez disso (Incid. 2, P0)."""
        result = self.post(f"/sqlEndpoints/{sql_endpoint_id}/refreshMetadata",
                            json_body={"recreateTables": recreate_tables})
        if not require_visible:
            return {"status": "ok", "raw": result}

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            table_statuses = {t.get("name"): t.get("status") for t in result.get("value", result.get("tables", []))}
            expected = expected_tables or list(table_statuses.keys())
            not_run = [t for t in expected if table_statuses.get(t) in {None, "NotRun"}]
            if not not_run:
                return {"status": "ok", "raw": result, "table_statuses": table_statuses}
            time.sleep(poll_seconds)
            result = self.post(f"/sqlEndpoints/{sql_endpoint_id}/refreshMetadata",
                                json_body={"recreateTables": False})
        return {"status": "INCOMPLETE", "raw": result,
                "reason": "Tabelas ainda NotRun/ausentes após timeout; HTTP 200 não é tratado como sucesso (require_visible)."}

    # ---------------- git ----------------

    def git_status(self) -> dict:
        return self.get(f"/workspaces/{self.workspace_id}/git/status")

    def git_connection(self) -> dict:
        return self.get(f"/workspaces/{self.workspace_id}/git/connection")

    def git_commit(self, comment: str, item_ids: Optional[list[str]] = None) -> dict:
        body: dict = {"comment": comment}
        if item_ids:
            body["items"] = [{"objectId": i} for i in item_ids]
        return self.post(f"/workspaces/{self.workspace_id}/git/commitToGit", json_body=body)

    def git_plan_commit(self, item_ids: Optional[list[str]] = None) -> dict:
        """Planejamento de commit com seleção de itens (Incid. 1, P1:
        `git commit` aceita `--item-ids`, `git plan-commit` não — corrigido
        aqui mostrando só o delta dos itens selecionados)."""
        status = self.git_status()
        changes = status.get("changes", [])
        if item_ids:
            changes = [c for c in changes if c.get("itemMetadata", {}).get("itemIdentifier", {}).get("objectId") in item_ids]
        return {"workspaceHead": status.get("workspaceHead"), "conflictCount": status.get("conflictCount", 0),
                "selectedChanges": changes, "selectedCount": len(changes)}

    def git_update_from_git(self) -> dict:
        return self.post(f"/workspaces/{self.workspace_id}/git/updateFromGit", json_body={})

    def git_lro_result(self, operation_id: str) -> dict:
        """Consulta o resultado de uma LRO do Git; trata `OperationHasNoResult`
        como sucesso-sem-conteúdo em vez de erro (Incid. 1, P1)."""
        try:
            return {"status": "ok", "result": self.get(f"/operations/{operation_id}/result")}
        except FabricApiError as exc:
            if "OperationHasNoResult" in str(exc):
                return {"status": "ok_no_content", "result": None}
            raise

    # ---------------- variable libraries ----------------

    def list_variable_libraries(self) -> list[dict]:
        return self.list_items(item_type="VariableLibrary")

    def get_variable_library_definition(self, item_id: str) -> dict:
        return self.get_definition(item_id)

    # ---------------- environments ----------------

    def get_environment(self, item_id: str) -> dict:
        return self.get(f"/workspaces/{self.workspace_id}/environments/{item_id}")

    def publish_environment(self, item_id: str) -> dict:
        return self.post(f"/workspaces/{self.workspace_id}/environments/{item_id}/staging/publish")


def _safe_json(resp: requests.Response) -> dict:
    try:
        return resp.json()
    except ValueError:
        return {"raw": resp.text}


def build_client_from_profile(profile: Profile) -> FabricClient:
    return FabricClient(profile)
