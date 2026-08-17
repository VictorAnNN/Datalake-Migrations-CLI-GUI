"""dlctl.core.manifest

Motor de manifests que replica o "Canonical Write Workflow" das skills:

    manifest validate -> plan -> dry-run -> apply --confirm-write -> status

Manifests seguem o formato documentado em datapipeline_manifest_patterns.md
(manifest_id, environment, operation, resource_type, safety, desired_state).
Suporta resource_type: DataPipeline, Notebook, Lakehouse, CopyJob, Environment,
VariableLibrary — qualquer item Fabric criável via definição.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, field_validator

from dlctl.core.gates import GateContext, SecurityError
from dlctl.core.secrets import assert_no_secret_like, redact
from dlctl.core.state import dump_evidence, record_manifest


class SafetyBlock(BaseModel):
    allow_write: bool = False
    delete_allowed: bool = False
    allow_move_existing: bool = False


class DesiredState(BaseModel):
    displayName: str
    description: str = ""
    folderPath: Optional[str] = None
    folderId: Optional[str] = None
    definition_file: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("displayName")
    @classmethod
    def _no_placeholder(cls, v: str) -> str:
        if not v or "PLACEHOLDER" in v.upper():
            raise ValueError("desired_state.displayName não pode ser vazio ou placeholder")
        return v


class Manifest(BaseModel):
    manifest_id: str
    environment: str = "DEV"
    operation: str = "ensure"  # ensure | delete
    owner: str = "dlctl-agent"
    resource_type: str
    displayName: str
    description: str = ""
    safety: SafetyBlock = Field(default_factory=SafetyBlock)
    desired_state: DesiredState

    _source_path: Optional[Path] = None

    @field_validator("operation")
    @classmethod
    def _valid_operation(cls, v: str) -> str:
        if v not in {"ensure", "delete"}:
            raise ValueError("operation deve ser 'ensure' ou 'delete'")
        return v


class ValidationIssue(BaseModel):
    level: str  # error | warning
    message: str


class ValidationResult(BaseModel):
    ok: bool
    issues: list[ValidationIssue] = Field(default_factory=list)


class PlanResult(BaseModel):
    manifest_id: str
    resource_type: str
    action: str  # create | update | noop | delete
    folder_id: Optional[str] = None
    resolved_definition_hash: Optional[str] = None
    current_definition_hash: Optional[str] = None
    diff_summary: str = ""
    plan_hash: str = ""


PLACEHOLDER_MARKERS = [
    "LakehouseOracle.Lakehouse",
    "abfss://Silver@",
    "abfss://Gold@",
    "PLACEHOLDER",
    "<SILVER_TABLE>",
    "<GOLD_TABLE>",
    "TODO",
]


def load_manifest(path: str | Path) -> Manifest:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    manifest = Manifest.model_validate(raw)
    manifest._source_path = path
    return manifest


def _sha256_of_file(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(manifest: Manifest) -> ValidationResult:
    """Validação local, sem chamadas de rede — equivalente a `manifest validate`."""
    issues: list[ValidationIssue] = []

    if manifest.operation == "ensure" and not manifest.safety.allow_write:
        issues.append(ValidationIssue(level="error", message="safety.allow_write=false impede qualquer escrita."))

    text_blob = json.dumps(manifest.model_dump(), default=str)
    for marker in PLACEHOLDER_MARKERS:
        if marker in text_blob:
            issues.append(ValidationIssue(level="error", message=f"Placeholder detectado: '{marker}'"))

    try:
        assert_no_secret_like(manifest.displayName)
    except ValueError as exc:
        issues.append(ValidationIssue(level="error", message=str(exc)))

    if manifest.desired_state.folderPath and manifest.desired_state.folderId:
        issues.append(ValidationIssue(
            level="warning",
            message="folderPath e folderId presentes; ambos devem resolver para a mesma pasta.",
        ))

    if manifest.desired_state.definition_file:
        base = (manifest._source_path.parent if manifest._source_path else Path("."))
        def_path = (base / manifest.desired_state.definition_file).resolve()
        if not def_path.exists():
            issues.append(ValidationIssue(level="error", message=f"definition_file não encontrado: {def_path}"))

    for key, value in manifest.desired_state.parameters.items():
        if not isinstance(value, dict) or "value" not in value or "type" not in value:
            issues.append(ValidationIssue(
                level="error",
                message=f"Parâmetro '{key}' deve ser objeto tipado {{value, type}}, não primitivo.",
            ))
            continue
        if value.get("type") not in {None, "string", "bool", "int", "float"}:
            issues.append(ValidationIssue(level="error", message=f"Tipo de parâmetro inválido em '{key}': {value.get('type')}"))

    ok = not any(i.level == "error" for i in issues)
    return ValidationResult(ok=ok, issues=issues)


def plan(manifest: Manifest, fabric_client: Optional[Any] = None) -> PlanResult:
    """Resolve folderPath->folderId e calcula diff local. Chamadas de rede são
    tentadas apenas se um fabric_client autenticado for fornecido; caso
    contrário, o plano é gerado localmente e o folder_id fica pendente
    (equivalente a manual_required em ambientes sem credenciais)."""
    v = validate(manifest)
    if not v.ok:
        raise SecurityError("manifest inválido: " + "; ".join(i.message for i in v.issues if i.level == "error"))

    def_hash = None
    if manifest.desired_state.definition_file:
        base = (manifest._source_path.parent if manifest._source_path else Path("."))
        def_hash = _sha256_of_file((base / manifest.desired_state.definition_file).resolve())

    folder_id = manifest.desired_state.folderId
    action = "create"
    diff = "Recurso não encontrado remotamente (ou Fabric não configurado) -> create."
    current_hash = None

    if fabric_client is not None:
        try:
            existing = fabric_client.find_item_by_name(manifest.displayName, manifest.resource_type)
            if manifest.desired_state.folderPath:
                folder_id = fabric_client.resolve_folder(manifest.desired_state.folderPath)
            if existing:
                action = "update"
                current_hash = existing.get("definitionHash")
                diff = "noop (hash idêntico)" if current_hash == def_hash else "update (definição mudou)"
                if current_hash == def_hash:
                    action = "noop"
        except Exception as exc:  # pragma: no cover - depende de rede/credenciais reais
            diff = f"manual_required: não foi possível consultar Fabric ({exc})"

    plan_payload = {
        "manifest_id": manifest.manifest_id,
        "resource_type": manifest.resource_type,
        "action": action,
        "folder_id": folder_id,
        "resolved_definition_hash": def_hash,
        "current_definition_hash": current_hash,
        "diff_summary": diff,
    }
    plan_hash = hashlib.sha256(json.dumps(plan_payload, sort_keys=True).encode()).hexdigest()
    result = PlanResult(**plan_payload, plan_hash=plan_hash)
    return result


def dry_run(manifest: Manifest, plan_result: PlanResult) -> ValidationResult:
    """Dry-run 100% offline: reprova hashes/definição sem chamar rede."""
    issues: list[ValidationIssue] = []
    if manifest.desired_state.definition_file:
        base = (manifest._source_path.parent if manifest._source_path else Path("."))
        def_path = (base / manifest.desired_state.definition_file).resolve()
        current_hash = _sha256_of_file(def_path)
        if current_hash != plan_result.resolved_definition_hash:
            issues.append(ValidationIssue(
                level="error",
                message="Hash da definição mudou desde o plano; re-execute 'manifest plan'.",
            ))
    ok = not any(i.level == "error" for i in issues)
    return ValidationResult(ok=ok, issues=issues)


def apply(
    manifest: Manifest,
    plan_result: PlanResult,
    gate: GateContext,
    confirm_write: bool,
    confirm_production: bool = False,
    confirm_move: bool = False,
    fabric_client: Optional[Any] = None,
    run_id: str = "",
) -> dict:
    """Aplica o manifest. Requer authorize_write() bem-sucedido antes de
    qualquer chamada mutante (Central Write Gate)."""
    gate.authorize_write(confirm_write=confirm_write, confirm_production=confirm_production)

    if plan_result.action == "update" and manifest.safety.allow_move_existing:
        gate.authorize_move(allow_move_existing=manifest.safety.allow_move_existing, confirm_move=confirm_move)

    result: dict[str, Any] = {"manifest_id": manifest.manifest_id, "action": plan_result.action, "status": "skipped"}

    if plan_result.action == "noop":
        result["status"] = "noop"
    elif fabric_client is not None:
        try:
            item = fabric_client.ensure_item(
                resource_type=manifest.resource_type,
                display_name=manifest.displayName,
                folder_id=plan_result.folder_id,
                definition_file=manifest.desired_state.definition_file,
                source_dir=(manifest._source_path.parent if manifest._source_path else Path(".")),
            )
            result["status"] = "applied"
            result["item"] = redact(item)
        except Exception as exc:  # pragma: no cover
            result["status"] = "failed"
            result["error"] = str(exc)
    else:
        result["status"] = "manual_required"
        result["reason"] = "Fabric client não configurado (credenciais ausentes) — aplique manualmente ou configure .env."

    record_manifest(
        gate.profile,
        manifest_id=manifest.manifest_id,
        resource_type=manifest.resource_type,
        display_name=manifest.displayName,
        environment=manifest.environment,
        operation=manifest.operation,
        stage="applied" if result["status"] in {"applied", "noop"} else "failed",
        allow_write=manifest.safety.allow_write,
        confirm_write=confirm_write,
        run_id=run_id,
    )
    dump_evidence(gate.profile, run_id or "adhoc", f"manifest_apply_{manifest.manifest_id}", result)
    return result
