"""dlctl.core.copyjob_bulk

Bulk Copy Jobs (Plan 39 do cli_command_surface.md / copyjob_surface.md):
"copyjobs bulk plan|diff|reconcile são comparações somente-leitura das
definições do gerador Constellation contra o live (identidade = displayName,
comparação = hash canônico do copyjob-content; relatório de duplicatas cobre
nomes com sufixo _N e itens distintos com a mesma assinatura origem→destino
— deleção nunca é automática); bulk dry-run é offline e prova
frozen-plan/local-hash/validação de definição com zero chamadas de rede.
bulk apply precisa do arquivo de plano de volta + --confirm-write
(--confirm-production adicionalmente para PRD), aborta em staleness (hash
live OU local mudou desde o plano) e em qualquer problema de validação.
Apply nunca roda os jobs — runs continuam sendo por-job via
`copyjobs run --confirm-execute`."

Este módulo implementa esse fluxo de forma real, operando sobre um diretório
local de definições de Copy Job (`*.copyjob.yaml` + o `copyjob-content.json`
referenciado por cada um). Sem um Fabric client configurado, plan/diff/
reconcile funcionam em modo local-apenas (mostram o catálogo e as
duplicatas, mas toda ação vira `create` já que não há como comparar com o
live) — nunca fingem uma comparação que não fizeram.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field

from dlctl.config import Profile
from dlctl.core.gates import GateContext, SecurityError
from dlctl.core.state import dump_evidence, record_manifest


class CopyJobBulkEntry(BaseModel):
    display_name: str
    folder_path: Optional[str] = None
    definition_file: str  # caminho relativo (à pasta do próprio yaml) do copyjob-content.json
    source_signature: str = ""  # ex.: "ORACLE:AP_INVOICES_ALL->LAKEHOUSE:LH_SUPRIMENTOS.bronze.ap_invoices_all"
    job_mode: str = "Batch"  # Batch | CDC

    _source_path: Optional[Path] = None


class BulkEntryPlan(BaseModel):
    display_name: str
    action: str  # create | update | noop | manual_required
    local_hash: str
    live_hash: Optional[str] = None
    folder_path: Optional[str] = None
    definition_file: str


class BulkPlanResult(BaseModel):
    definitions_dir: str
    entries: list[BulkEntryPlan] = Field(default_factory=list)
    duplicates: list[dict] = Field(default_factory=list)
    plan_hash: str = ""
    live_compared: bool = False


class BulkValidationIssue(BaseModel):
    display_name: str
    level: str  # error | warning
    message: str


def _canonical_hash(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        canonical = json.dumps(data, sort_keys=True, ensure_ascii=False)
    except json.JSONDecodeError:
        canonical = path.read_text(encoding="utf-8-sig")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_bulk_definitions(definitions_dir: str | Path) -> list[CopyJobBulkEntry]:
    """Carrega todos os `*.copyjob.yaml` de um diretório local."""
    definitions_dir = Path(definitions_dir)
    entries: list[CopyJobBulkEntry] = []
    for path in sorted(definitions_dir.glob("*.copyjob.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
        entry = CopyJobBulkEntry.model_validate(raw)
        entry._source_path = path
        entries.append(entry)
    return entries


def detect_duplicates(entries: list[CopyJobBulkEntry]) -> list[dict]:
    """Detecta duplicatas por dois critérios (Plan 39):
    - nomes com sufixo `_N` (ex.: cpj_ap_invoices_1, cpj_ap_invoices_2);
    - itens distintos compartilhando a mesma assinatura origem→destino.
    Nunca deleta nada automaticamente — apenas reporta."""
    import re

    duplicates: list[dict] = []

    by_base_name: dict[str, list[str]] = defaultdict(list)
    suffix_re = re.compile(r"^(.*)_(\d+)$")
    for e in entries:
        m = suffix_re.match(e.display_name)
        base = m.group(1) if m else e.display_name
        by_base_name[base].append(e.display_name)
    for base, names in by_base_name.items():
        if len(names) > 1:
            duplicates.append({"type": "suffix_name", "base": base, "names": names})

    by_signature: dict[str, list[str]] = defaultdict(list)
    for e in entries:
        if e.source_signature:
            by_signature[e.source_signature].append(e.display_name)
    for sig, names in by_signature.items():
        if len(names) > 1:
            duplicates.append({"type": "same_source_dest_signature", "signature": sig, "names": names})

    return duplicates


def bulk_plan(profile: Profile, definitions_dir: str | Path, fabric_client: Optional[Any] = None) -> BulkPlanResult:
    """Somente leitura: identidade = displayName, comparação = hash canônico
    do copyjob-content.json. Sem client, toda entrada vira `create` (não há
    como comparar com o live) e `live_compared=False` deixa isso explícito."""
    definitions_dir = Path(definitions_dir)
    entries = load_bulk_definitions(definitions_dir)
    duplicates = detect_duplicates(entries)

    plan_entries: list[BulkEntryPlan] = []
    live_compared = fabric_client is not None
    for e in entries:
        def_path = (e._source_path.parent / e.definition_file).resolve()
        local_hash = _canonical_hash(def_path)
        action = "create"
        live_hash = None
        if fabric_client is not None:
            try:
                existing = fabric_client.find_item_by_name(e.display_name, "CopyJob")
                if existing:
                    live_hash = existing.get("definitionHash")
                    action = "noop" if live_hash == local_hash else "update"
            except Exception:
                action = "manual_required"
        plan_entries.append(BulkEntryPlan(
            display_name=e.display_name, action=action, local_hash=local_hash,
            live_hash=live_hash, folder_path=e.folder_path, definition_file=e.definition_file,
        ))

    payload = {"definitions_dir": str(definitions_dir), "entries": [p.model_dump() for p in plan_entries]}
    plan_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return BulkPlanResult(
        definitions_dir=str(definitions_dir), entries=plan_entries, duplicates=duplicates,
        plan_hash=plan_hash, live_compared=live_compared,
    )


def bulk_dry_run(plan_result: BulkPlanResult) -> list[BulkValidationIssue]:
    """100% offline: reprova hash/definição local desde o plano (frozen-plan),
    sem nenhuma chamada de rede — proíbe aplicar um plano obsoleto."""
    issues: list[BulkValidationIssue] = []
    definitions_dir = Path(plan_result.definitions_dir)
    for entry in plan_result.entries:
        def_path = definitions_dir / entry.definition_file
        current_hash = _canonical_hash(def_path)
        if current_hash != entry.local_hash:
            issues.append(BulkValidationIssue(
                display_name=entry.display_name, level="error",
                message="Hash local mudou desde o plano (staleness); re-execute 'bulk plan'.",
            ))
        if not def_path.exists():
            issues.append(BulkValidationIssue(
                display_name=entry.display_name, level="error",
                message=f"definition_file não encontrado: {def_path}",
            ))
    if plan_result.duplicates:
        for dup in plan_result.duplicates:
            issues.append(BulkValidationIssue(
                display_name=", ".join(dup.get("names", [])), level="warning",
                message=f"Duplicata detectada ({dup['type']}): {dup}",
            ))
    return issues


def bulk_reconcile(profile: Profile, definitions_dir: str | Path, fabric_client: Optional[Any] = None) -> dict:
    """Comparação somente-leitura: o que existe localmente mas não no live
    (missing_in_fabric), o que existe no live mas não localmente
    (orphaned_in_fabric — nunca deletado automaticamente), e duplicatas."""
    entries = load_bulk_definitions(definitions_dir)
    duplicates = detect_duplicates(entries)
    local_names = {e.display_name for e in entries}

    if fabric_client is None:
        return {
            "live_compared": False, "local_count": len(entries), "duplicates": duplicates,
            "missing_in_fabric": [], "orphaned_in_fabric": [],
            "note": "manual_required: sem Fabric client configurado, não é possível comparar com o live.",
        }

    live_items = fabric_client.list_items(item_type="CopyJob")
    live_names = {i.get("displayName") for i in live_items}
    return {
        "live_compared": True, "local_count": len(entries), "duplicates": duplicates,
        "missing_in_fabric": sorted(local_names - live_names),
        "orphaned_in_fabric": sorted(live_names - local_names),
    }


def bulk_apply(
    profile: Profile,
    plan_result: BulkPlanResult,
    gate: GateContext,
    confirm_write: bool,
    confirm_production: bool = False,
    fabric_client: Optional[Any] = None,
    run_id: str = "",
) -> dict:
    """Aplica o plano (cria/atualiza definições de Copy Job). Nunca roda os
    jobs — isso continua sendo `copyjobs run --confirm-execute`, por item."""
    gate.authorize_write(confirm_write=confirm_write, confirm_production=confirm_production)

    dry_run_issues = bulk_dry_run(plan_result)
    if any(i.level == "error" for i in dry_run_issues):
        raise SecurityError(
            "bulk apply abortado: " + "; ".join(i.message for i in dry_run_issues if i.level == "error")
        )

    definitions_dir = Path(plan_result.definitions_dir)
    results: dict[str, dict] = {}
    for entry in plan_result.entries:
        if entry.action == "noop":
            results[entry.display_name] = {"status": "noop"}
            continue
        if entry.action == "manual_required":
            results[entry.display_name] = {"status": "manual_required"}
            continue
        if fabric_client is None:
            results[entry.display_name] = {"status": "manual_required", "reason": "Fabric client não configurado."}
            continue
        try:
            folder_id = fabric_client.resolve_folder(entry.folder_path) if entry.folder_path else None
            item = fabric_client.ensure_item(
                resource_type="CopyJob", display_name=entry.display_name, folder_id=folder_id,
                definition_file=entry.definition_file, source_dir=definitions_dir,
            )
            results[entry.display_name] = {"status": "applied", "action": entry.action, "item_id": item.get("id")}
        except Exception as exc:  # pragma: no cover - depende de rede/credenciais reais
            results[entry.display_name] = {"status": "failed", "error": str(exc)}

    for display_name, result in results.items():
        record_manifest(
            profile, manifest_id=f"copyjob_bulk:{display_name}", resource_type="CopyJob",
            display_name=display_name, environment=profile.environment, operation="ensure",
            stage="applied" if result["status"] in {"applied", "noop"} else "failed",
            allow_write=True, confirm_write=confirm_write, run_id=run_id,
        )
    dump_evidence(profile, run_id or "adhoc", "copyjobs_bulk_apply", results)
    return {"results": results, "duplicates": plan_result.duplicates}
