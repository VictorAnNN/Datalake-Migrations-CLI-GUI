"""Plano selado e definição pública ipynb para criação de Notebook Fabric."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import nbformat


PLAN_SCHEMA_VERSION = 1
DEFINITION_FORMAT = "ipynb"
DEFINITION_PART_PATH = "notebook-content.ipynb"


class NotebookPlanError(ValueError):
    pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_plan_hash(plan: dict[str, Any]) -> str:
    payload = {key: value for key, value in plan.items() if key != "planSha256"}
    return sha256_bytes(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def validate_ipynb(path: str | Path) -> dict[str, Any]:
    notebook_path = Path(path).resolve()
    if not notebook_path.is_file() or notebook_path.suffix.lower() != ".ipynb":
        raise NotebookPlanError(f"Notebook .ipynb não encontrado: {notebook_path}")
    raw = json.loads(notebook_path.read_text(encoding="utf-8"))
    nbformat.validate(nbformat.from_dict(raw))
    if raw.get("nbformat") != 4:
        raise NotebookPlanError(f"nbformat deve ser 4; encontrado: {raw.get('nbformat')}")
    for index, cell in enumerate(raw.get("cells", [])):
        if not cell.get("id"):
            raise NotebookPlanError(f"Célula {index} sem id.")
        if not isinstance(cell.get("source"), list):
            raise NotebookPlanError(f"Célula {index} com source fora do formato lista.")
    return raw


def build_definition(path: str | Path) -> dict[str, Any]:
    notebook_path = Path(path).resolve()
    validate_ipynb(notebook_path)
    return {
        "format": DEFINITION_FORMAT,
        "parts": [{
            "path": DEFINITION_PART_PATH,
            "payload": base64.b64encode(notebook_path.read_bytes()).decode("ascii"),
            "payloadType": "InlineBase64",
        }],
    }


def create_plan(
    *,
    notebook_path: str | Path,
    display_name: str,
    environment: str,
    workspace_name: str | None,
    workspace_id: str | None,
    contract: str,
    folder_path: str | None = None,
    description: str = "",
) -> dict[str, Any]:
    if not display_name.strip():
        raise NotebookPlanError("display_name é obrigatório.")
    if len(description) > 256:
        raise NotebookPlanError("description excede 256 caracteres.")
    notebook_path = Path(notebook_path).resolve()
    validate_ipynb(notebook_path)
    notebook_bytes = notebook_path.read_bytes()
    plan: dict[str, Any] = {
        "schemaVersion": PLAN_SCHEMA_VERSION,
        "operation": "create",
        "resourceType": "Notebook",
        "environment": environment.upper(),
        "workspaceName": workspace_name,
        "workspaceId": workspace_id,
        "displayName": display_name.strip(),
        "description": description,
        "folderPath": folder_path,
        "contract": contract,
        "notebookPath": str(notebook_path),
        "notebookSha256": sha256_bytes(notebook_bytes),
        "definitionFormat": DEFINITION_FORMAT,
        "definitionPartPath": DEFINITION_PART_PATH,
        "rollback": "delete-created-item-by-returned-id",
    }
    plan["planSha256"] = _canonical_plan_hash(plan)
    return plan


def load_and_verify_plan(path: str | Path) -> dict[str, Any]:
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    if plan.get("schemaVersion") != PLAN_SCHEMA_VERSION:
        raise NotebookPlanError("Versão de plano incompatível.")
    if plan.get("planSha256") != _canonical_plan_hash(plan):
        raise NotebookPlanError("Hash do plano inválido; gere novamente.")
    notebook_path = Path(plan["notebookPath"])
    validate_ipynb(notebook_path)
    if sha256_bytes(notebook_path.read_bytes()) != plan.get("notebookSha256"):
        raise NotebookPlanError("Notebook mudou desde o plano; gere novamente.")
    if plan.get("definitionFormat") != DEFINITION_FORMAT or plan.get("definitionPartPath") != DEFINITION_PART_PATH:
        raise NotebookPlanError("Contrato de definição Notebook incompatível.")
    return plan
