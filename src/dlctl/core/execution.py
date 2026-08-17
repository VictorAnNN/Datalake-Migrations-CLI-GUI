"""dlctl.core.execution

Lógica pura (sem Typer) do Canonical Execution Workflow: plan -> dry-run ->
apply --confirm-execute. Compartilhada pelo CLI (`dlctl execute ...`) e pelo
dashboard Streamlit.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel

from dlctl.core.gates import GateContext
from dlctl.core.state import dump_evidence


class ExecutionManifest(BaseModel):
    execution_id: str
    item_display_name: str
    item_type: str = "Notebook"  # Notebook | DataPipeline | Dataflow | CopyJob
    parameters: dict = {}


JOB_TYPE_BY_ITEM = {"Notebook": "RunNotebook", "DataPipeline": "Pipeline", "Dataflow": "Refresh", "CopyJob": "Execute"}


def load_execution_manifest(path: str | Path) -> ExecutionManifest:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return ExecutionManifest.model_validate(raw)


def plan_execution(manifest: ExecutionManifest) -> dict:
    """Planejador local de prontidão. NUNCA executa nada."""
    return {
        "execution_id": manifest.execution_id,
        "item_display_name": manifest.item_display_name,
        "item_type": manifest.item_type,
        "parameters": manifest.parameters,
        "note": "Nenhuma chamada de execução foi feita (apenas planejamento local).",
    }


def dry_run_execution(manifest: ExecutionManifest) -> list[str]:
    issues = []
    if not manifest.item_display_name:
        issues.append("item_display_name vazio")
    if manifest.item_type not in JOB_TYPE_BY_ITEM:
        issues.append(f"item_type inválido: {manifest.item_type}")
    return issues


def apply_execution(
    manifest: ExecutionManifest,
    gate: GateContext,
    confirm_execute: bool,
    fabric_client: Optional[object] = None,
    run_id: str = "",
) -> dict:
    """Aplica (dispara) a execução. Requer authorize_execute() satisfeito."""
    gate.authorize_execute(confirm_execute=confirm_execute)

    result: dict = {"execution_id": manifest.execution_id, "status": "manual_required"}
    if fabric_client is not None:
        try:
            item = fabric_client.find_item_by_name(manifest.item_display_name, manifest.item_type)
            if not item:
                result = {"execution_id": manifest.execution_id, "status": "failed", "error": "item não encontrado"}
            else:
                job_type = JOB_TYPE_BY_ITEM[manifest.item_type]
                instance = fabric_client.run_item_job(item["id"], job_type=job_type, parameters=manifest.parameters)
                result = {"execution_id": manifest.execution_id, "status": "started",
                          "job_instance": instance, "item_id": item["id"]}
        except Exception as exc:  # pragma: no cover - depende de rede/credenciais reais
            result = {"execution_id": manifest.execution_id, "status": "failed", "error": str(exc)}

    dump_evidence(gate.profile, run_id or "adhoc", f"execute_apply_{manifest.execution_id}", result)
    return result


TERMINAL_STATUSES = {"Completed", "Failed", "Cancelled", "Deduped"}


def poll_job_status(
    fabric_client: object,
    item_id: str,
    job_instance_id: str,
    wait: bool = False,
    poll_seconds: float = 5.0,
    timeout_seconds: float = 300.0,
) -> dict:
    """Consulta (e opcionalmente aguarda) o status real de uma execução no
    Fabric — fecha o gap 'avaliar sucesso de execuções ao vivo' apontado
    anteriormente. É uma LEITURA (GET), não passa por nenhum gate de escrita.

    Sem `wait`, faz uma única consulta. Com `wait=True`, faz polling até um
    status terminal (Completed/Failed/Cancelled/Deduped) ou até
    `timeout_seconds`, retornando `status='TIMEOUT'` se o timeout estourar
    antes de um status terminal."""
    import time as _time

    attempts = []
    deadline = _time.time() + timeout_seconds
    while True:
        instance = fabric_client.job_instance_status(item_id, job_instance_id)
        current_status = instance.get("status", "Unknown")
        attempts.append({"status": current_status})
        if current_status in TERMINAL_STATUSES or not wait:
            return {"status": current_status, "instance": instance, "attempts": len(attempts), "terminal": current_status in TERMINAL_STATUSES}
        if _time.time() >= deadline:
            return {"status": "TIMEOUT", "instance": instance, "attempts": len(attempts), "terminal": False}
        _time.sleep(poll_seconds)

