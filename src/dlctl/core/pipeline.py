"""dlctl.core.pipeline

Lógica pura (sem dependência de Typer) do router de pipeline
constellation-order-tracking-etl. Extraída para cá para que tanto o CLI
(`dlctl pipeline run-order-tracking`) quanto o dashboard Streamlit (botão
"Rodar pipeline") chamem exatamente o mesmo código — uma única fonte de
verdade para os 10 passos do workflow.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from dlctl.config import Profile
from dlctl.core.gates import GateContext, SecurityError
from dlctl.core.mapping import build_inventory, load_mapping, reconcile_scope
from dlctl.core.state import finish_run, record_step, start_run
from dlctl.generators.gold_generator import generate_gold_notebook
from dlctl.generators.gold_generator import write_notebook as write_gold_notebook
from dlctl.generators.silver_generator import generate_silver_notebook
from dlctl.generators.silver_generator import write_notebook as write_silver_notebook
from dlctl.generators.validators import validate_gold_notebook, validate_silver_notebook

GO_STATUSES = {"spark_ready", "needs_rewrite"}

StepCallback = Optional[Callable[[int, str, str, str], None]]


def run_order_tracking(
    profile: Profile,
    domain: str = "ORDER_TRACKING",
    bronze_base_path: str = "Files/Bronze",
    silver_base_path: str = "Tables/silver",
    gold_base_path: str = "Tables/gold",
    write: bool = False,
    publish: bool = False,
    confirm_write: bool = False,
    confirm_execute: bool = False,
    on_step: StepCallback = None,
) -> dict:
    """Executa o workflow do router de ponta a ponta, parando (Stop Condition)
    sempre que um gate de negócio ou de segurança não estiver satisfeito.

    Retorna um dict {run_id, status, summary} e nunca levanta exceção para
    fluxo de negócio esperado (bloqueios são reportados via status='blocked').
    `on_step(index, name, status, detail)` é chamado a cada passo, útil para
    o dashboard atualizar a UI em tempo real.
    """
    run_id = start_run(profile, domain)
    step = 0

    def emit(name: str, status: str, skill: str, detail: str = "") -> None:
        nonlocal step
        step += 1
        record_step(profile, run_id, step, name, status, skill=skill, detail=detail)
        if on_step:
            on_step(step, name, status, detail)

    try:
        # 1) Identificar targets Silver
        inv = build_inventory(profile, layer="bronze_to_silver", domain=domain)
        emit("Identificar targets Silver", "success", "etl-oracle-fabric",
             f"{inv['total']} targets, {inv['go_count']} GO")

        # 2) Reconciliar escopo (somente Bronze permitido)
        reconciliation = reconcile_scope(profile, layer="bronze_to_silver", domain=domain)
        if reconciliation["verdict"] == "no_go":
            emit("Reconciliar escopo Bronze permitido", "blocked", "etl-oracle-fabric",
                 "Nenhum target Silver está GO; revise o mapeamento.")
            finish_run(profile, run_id, "blocked", "Nenhum target Silver GO.")
            return {"run_id": run_id, "status": "blocked", "summary": "Nenhum target Silver GO."}
        emit("Reconciliar escopo Bronze permitido", "success", "etl-oracle-fabric",
             f"verdict={reconciliation['verdict']}, go={len(reconciliation['go_targets'])}")

        # 3) Gerar um pilot Silver local
        entries = load_mapping(profile, layer="bronze_to_silver", domain=domain)
        pilot = next((e for e in entries if e.status in GO_STATUSES), None)
        if not pilot:
            emit("Gerar pilot Silver", "blocked", "etl-oracle-fabric", "Nenhuma entrada GO disponível para pilot.")
            finish_run(profile, run_id, "blocked", "Nenhuma entrada GO disponível para pilot.")
            return {"run_id": run_id, "status": "blocked", "summary": "Nenhuma entrada GO disponível para pilot."}
        nb_silver = generate_silver_notebook(pilot, bronze_base_path, silver_base_path, project_root=Path.cwd())
        silver_nb_path = profile.paths.notebooks_silver_root / f"{pilot.target_table}.ipynb"
        write_silver_notebook(nb_silver, silver_nb_path)  # necessário em disco para validação local
        emit("Gerar pilot Silver", "success", "etl-oracle-fabric", f"pilot={pilot.target_table} -> {silver_nb_path}")

        # 4) Validar notebook Silver localmente
        outcome = validate_silver_notebook(silver_nb_path)
        if not outcome.ok:
            emit("Validar notebook Silver", "blocked", "etl-oracle-fabric", "; ".join(outcome.errors))
            finish_run(profile, run_id, "blocked", "; ".join(outcome.errors))
            return {"run_id": run_id, "status": "blocked", "summary": "; ".join(outcome.errors)}
        emit("Validar notebook Silver", "success", "etl-oracle-fabric", "válido (Notebook Contract OK)")

        # 5) Publicar Silver via manifest (fabric-full-agent) — apenas se autorizado
        if publish and confirm_write:
            emit("Publicar Silver (manifest apply)", "success", "fabric-full-agent",
                 "Publicação delegada a 'manifest apply --confirm-write' (gere e revise o manifest correspondente).")
        else:
            emit("Publicar Silver (manifest apply)", "skipped", "fabric-full-agent",
                 "Sem publish/confirm_write; gere e revise o manifest antes de publicar.")

        # 6) Executar somente com autorização explícita do turno atual
        if confirm_execute:
            emit("Executar Silver (gated)", "success", "fabric-full-agent",
                 "Execução delegada a 'execute apply --confirm-execute'.")
        else:
            emit("Executar Silver (gated)", "skipped", "fabric-full-agent",
                 "confirm_execute não fornecido nesta chamada; execução NÃO realizada.")

        # 7) Validação de negócio manual
        emit("Validação de negócio (Suprimentos focal point)", "blocked", "manual",
             "manual_required: validar contagens/schema/PK/quarentena com o time de negócio antes do Gold.")

        # 8) Gerar Gold somente a partir de Silver validado
        gold_entries = load_mapping(profile, layer="silver_to_gold", domain=domain)
        gold_pilot = next(
            (e for e in gold_entries if e.status in GO_STATUSES and e.source_table == pilot.target_table), None
        )
        if not gold_pilot:
            emit("Gerar pilot Gold", "skipped", "etl-oracle-fabric-gold",
                 f"Nenhum Gold GO depende diretamente de {pilot.target_table} ainda.")
        else:
            nb_gold = generate_gold_notebook(gold_pilot, silver_base_path, gold_base_path, project_root=Path.cwd())
            gold_nb_path = profile.paths.notebooks_gold_root / f"{gold_pilot.target_table}.ipynb"
            write_gold_notebook(nb_gold, gold_nb_path)
            gold_outcome = validate_gold_notebook(gold_nb_path)
            if not gold_outcome.ok:
                emit("Gerar pilot Gold", "blocked", "etl-oracle-fabric-gold", "; ".join(gold_outcome.errors))
                finish_run(profile, run_id, "blocked", "; ".join(gold_outcome.errors))
                return {"run_id": run_id, "status": "blocked", "summary": "; ".join(gold_outcome.errors)}
            emit("Gerar pilot Gold", "success", "etl-oracle-fabric-gold",
                 f"pilot={gold_pilot.target_table} -> {gold_nb_path}")

        # 9) Publicar/executar Gold — mesma regra de gates do passo 5/6
        emit("Publicar/Executar Gold (gated)", "skipped", "fabric-full-agent",
             "Use 'manifest apply' / 'execute apply' com os gates apropriados.")

        # 10) Conectar semantic model/report — manual
        emit("Conectar semantic model/report", "blocked", "manual",
             "manual_required: só após validação de Gold pelo negócio.")

        finish_run(profile, run_id, "success", "Pipeline concluído até os limites de autorização/validação manual.")
        return {"run_id": run_id, "status": "success",
                "summary": "Pipeline concluído até os limites de autorização/validação manual."}
    except SecurityError as exc:
        finish_run(profile, run_id, "blocked", str(exc))
        return {"run_id": run_id, "status": "blocked", "summary": str(exc)}
    except Exception as exc:
        finish_run(profile, run_id, "failed", str(exc))
        return {"run_id": run_id, "status": "failed", "summary": str(exc)}
