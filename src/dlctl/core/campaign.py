"""dlctl.core.campaign

Orquestrador multi-alvo `execute campaign` (Incid. 2, P0):
"Sem orquestrador multi-alvo: publicar -> executar -> coletar logs -> Delta
-> SQL endpoint -> selar vários alvos." O `execute apply` de antes é
essencialmente single-target; este módulo adiciona a camada de campanha.

Características (replicando a proposta do incidente):
- manifesto multi-alvo (YAML) com dependências entre alvos (`depends_on`),
  formando um DAG simples.
- execução **serial** (um alvo de cada vez, na ordem topológica).
- **zero replay de mutação**: cada fase gated (publish/execute) só roda uma
  vez por alvo; se falhar, não tenta de novo sozinho.
- **isolamento de falha por DAG**: se um alvo falha, apenas os alvos que
  dependem dele (direta ou indiretamente) são bloqueados; alvos
  independentes continuam normalmente.

Fases por alvo: preflight -> publish -> execute -> wait -> logs -> classify
-> delta -> sql_endpoint -> seal.

As fases que exigem um Fabric client autenticado (`wait`, `logs`,
`sql_endpoint`) reportam `skipped`/`manual_required` quando nenhum client é
passado — nesta sessão, por instrução explícita, **nenhuma chamada real ao
Fabric é feita**, então rode sempre com `fabric_client=None` ao testar.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import yaml
from pydantic import BaseModel, Field

from dlctl.config import Profile
from dlctl.core.gates import GateContext, SecurityError
from dlctl.core.log_classifier import classify_log
from dlctl.core.state import finish_campaign, record_campaign_step, register_ownership, start_campaign

PHASES = ["preflight", "publish", "execute", "wait", "logs", "classify", "delta", "sql_endpoint", "seal"]


class CampaignTarget(BaseModel):
    name: str
    manifest: Optional[str] = None            # manifest de publicação (DataPipeline/Notebook/...)
    execution_manifest: Optional[str] = None   # manifest de execução (item a rodar)
    sql_endpoint_tables: list[str] = Field(default_factory=list)
    log_text: Optional[str] = None             # log já coletado localmente (para classify offline)
    depends_on: list[str] = Field(default_factory=list)
    wait_poll_seconds: float = 5.0
    wait_timeout_seconds: float = 300.0


class CampaignManifest(BaseModel):
    campaign_id: str
    targets: list[CampaignTarget]


def load_campaign_manifest(path: str | Path) -> CampaignManifest:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8-sig"))
    return CampaignManifest.model_validate(raw)


def _topological_order(targets: list[CampaignTarget]) -> list[str]:
    """Ordenação topológica simples (Kahn) sobre depends_on; detecta ciclo."""
    names = [t.name for t in targets]
    deps = {t.name: list(t.depends_on) for t in targets}
    order: list[str] = []
    visited: set[str] = set()
    temp: set[str] = set()

    def visit(n: str):
        if n in visited:
            return
        if n in temp:
            raise ValueError(f"Ciclo detectado no DAG de targets envolvendo '{n}'.")
        temp.add(n)
        for d in deps.get(n, []):
            if d in names:
                visit(d)
        temp.discard(n)
        visited.add(n)
        order.append(n)

    for n in names:
        visit(n)
    return order


def run_campaign(
    profile: Profile,
    manifest_path: str | Path,
    confirm_write: bool = False,
    confirm_execute: bool = False,
    fabric_client: Optional[object] = None,
    on_step: Optional[Callable[[str, str, str, str], None]] = None,
) -> dict:
    """Executa a campanha alvo a alvo, em ordem topológica, isolando falhas
    por dependência. `fabric_client=None` (padrão nesta sessão) faz as fases
    de rede reportarem `skipped`/`manual_required` sem nenhuma chamada real."""
    manifest = load_campaign_manifest(manifest_path)
    campaign_id = start_campaign(profile, str(manifest_path))
    gate = GateContext(profile=profile, run_id=campaign_id)

    blocked_targets: dict[str, str] = {}
    results: dict[str, dict] = {}

    def emit(target: str, phase: str, status: str, detail: str = "") -> None:
        record_campaign_step(profile, campaign_id, target, phase, status, detail)
        if on_step:
            on_step(target, phase, status, detail)

    try:
        order = _topological_order(manifest.targets)
    except ValueError as exc:
        finish_campaign(profile, campaign_id, "failed", str(exc))
        return {"campaign_id": campaign_id, "status": "failed", "summary": str(exc)}

    by_name = {t.name: t for t in manifest.targets}

    for name in order:
        target = by_name[name]
        # isolamento de falha por DAG: se qualquer dependência foi bloqueada/falhou, bloqueia este alvo também
        blocking_dep = next((d for d in target.depends_on if d in blocked_targets), None)
        if blocking_dep:
            reason = f"Dependência '{blocking_dep}' falhou/bloqueou: {blocked_targets[blocking_dep]}"
            for phase in PHASES:
                emit(name, phase, "blocked", reason)
            blocked_targets[name] = reason
            results[name] = {"status": "blocked", "reason": reason}
            continue

        target_failed = False
        target_detail = ""

        # 1) preflight — valida se os manifests referenciados existem e são carregáveis
        try:
            if target.manifest and not Path(target.manifest).exists():
                raise FileNotFoundError(f"manifest não encontrado: {target.manifest}")
            if target.execution_manifest and not Path(target.execution_manifest).exists():
                raise FileNotFoundError(f"execution_manifest não encontrado: {target.execution_manifest}")
            emit(name, "preflight", "success", "Manifests localizados.")
        except Exception as exc:
            emit(name, "preflight", "failed", str(exc))
            target_failed, target_detail = True, str(exc)

        # 2) publish (gated) — só roda de fato se houver manifest e client
        if not target_failed:
            if target.manifest and confirm_write:
                try:
                    from dlctl.core import manifest as manifest_engine
                    m = manifest_engine.load_manifest(target.manifest)
                    plan_result = manifest_engine.plan(m, fabric_client=fabric_client)
                    apply_result = manifest_engine.apply(
                        m, plan_result, gate, confirm_write=confirm_write, fabric_client=fabric_client, run_id=campaign_id,
                    )
                    status = "success" if apply_result["status"] in {"applied", "noop"} else apply_result["status"]
                    emit(name, "publish", status, str(apply_result))
                    if status == "failed":
                        target_failed, target_detail = True, str(apply_result)
                except SecurityError as exc:
                    emit(name, "publish", "blocked", str(exc))
                    target_failed, target_detail = True, str(exc)
            else:
                emit(name, "publish", "skipped", "Sem manifest ou sem --confirm-write; publicação não realizada.")

        # 3) execute (gated)
        job_ref: dict = {}
        if not target_failed:
            if target.execution_manifest and confirm_execute:
                try:
                    from dlctl.core.execution import apply_execution, load_execution_manifest
                    em = load_execution_manifest(target.execution_manifest)
                    exec_result = apply_execution(em, gate, confirm_execute=confirm_execute,
                                                   fabric_client=fabric_client, run_id=campaign_id)
                    status = "success" if exec_result["status"] == "started" else exec_result["status"]
                    emit(name, "execute", status, str(exec_result))
                    if status == "failed":
                        target_failed, target_detail = True, str(exec_result)
                    elif status == "success":
                        instance = exec_result.get("job_instance", {}) or {}
                        if instance.get("jobInstanceId") and exec_result.get("item_id"):
                            job_ref = {"item_id": exec_result["item_id"], "job_instance_id": instance["jobInstanceId"]}
                except SecurityError as exc:
                    emit(name, "execute", "blocked", str(exc))
                    target_failed, target_detail = True, str(exc)
            else:
                emit(name, "execute", "skipped", "Sem execution_manifest ou sem --confirm-execute; execução não realizada.")

        # 4) wait — usa poll_job_status de verdade quando há client E job_instance_id capturado
        if not target_failed:
            if fabric_client is not None and job_ref.get("job_instance_id"):
                try:
                    from dlctl.core.execution import poll_job_status
                    wait_result = poll_job_status(
                        fabric_client, job_ref["item_id"], job_ref["job_instance_id"],
                        wait=True, poll_seconds=target.wait_poll_seconds, timeout_seconds=target.wait_timeout_seconds,
                    )
                    status = "success" if wait_result["status"] == "Completed" else "failed"
                    emit(name, "wait", status, f"status={wait_result['status']} tentativas={wait_result['attempts']}")
                    if status == "failed":
                        target_failed, target_detail = True, f"Job terminou com status={wait_result['status']}"
                except Exception as exc:  # pragma: no cover - depende de rede/credenciais reais
                    emit(name, "wait", "failed", str(exc))
                    target_failed, target_detail = True, str(exc)
            elif fabric_client is not None:
                emit(name, "wait", "skipped", "manual_required: job_instance_id não capturado na fase execute (item/job type sem Location header).")
            else:
                emit(name, "wait", "skipped", "Sem Fabric client configurado (ou desabilitado nesta sessão por segurança).")

        # 5) logs + 6) classify — classificação offline se log_text foi fornecido no manifesto
        if not target_failed:
            if target.log_text:
                outcome = classify_log(target.log_text)
                emit(name, "logs", "success", f"{outcome.total_lines} linhas analisadas.")
                classify_status = "success" if outcome.overall == "PASS" else ("blocked" if outcome.overall == "NEVER_PASS" else "failed")
                emit(name, "classify", classify_status,
                     f"overall={outcome.overall}, unknown_lines={len(outcome.unknown_lines)}")
                if classify_status != "success":
                    target_failed, target_detail = True, f"Classificação de log: {outcome.overall}"
            else:
                emit(name, "logs", "skipped", "Nenhum log_text fornecido no manifesto para esta sessão.")
                emit(name, "classify", "skipped", "Sem logs para classificar.")

        # 7) delta — checagem de tabelas Delta só com client real
        if not target_failed:
            emit(name, "delta", "skipped", "manual_required: checagem de tabela Delta requer Fabric client (não usado nesta sessão).")

        # 8) sql_endpoint — refresh só com client real
        if not target_failed:
            if target.sql_endpoint_tables and fabric_client is not None:
                emit(name, "sql_endpoint", "skipped", "manual_required: refresh real requer client autenticado (não usado nesta sessão).")
            else:
                emit(name, "sql_endpoint", "skipped", f"Tabelas alvo: {target.sql_endpoint_tables or '(nenhuma)'}")

        # 9) seal — registra ownership/ledger local, independente de client
        if not target_failed:
            register_ownership(profile, resource_type="CampaignTarget", resource_id=name,
                                display_name=name, owner="dlctl-campaign")
            emit(name, "seal", "success", "Selado localmente (ownership registrado).")
            results[name] = {"status": "success"}
        else:
            blocked_targets[name] = target_detail
            results[name] = {"status": "failed", "reason": target_detail}

    any_failed = any(r["status"] in {"failed", "blocked"} for r in results.values())
    overall_status = "failed" if any_failed else "success"
    summary = f"{sum(1 for r in results.values() if r['status']=='success')}/{len(results)} alvos concluídos com sucesso."
    finish_campaign(profile, campaign_id, overall_status, summary)
    return {"campaign_id": campaign_id, "status": overall_status, "summary": summary, "targets": results}
