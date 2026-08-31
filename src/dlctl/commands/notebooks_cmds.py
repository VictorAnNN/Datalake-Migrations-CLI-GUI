"""Criação controlada de Notebook Fabric: plano offline e apply gated."""
from __future__ import annotations

import json
from pathlib import Path

import typer

from dlctl.commands.common import console, get_gate, get_profile, handle_security_error
from dlctl.connectors.fabric_api import FabricApiError, build_client_from_profile
from dlctl.core.notebook_definition import (
    NotebookPlanError,
    build_definition,
    create_plan,
    load_and_verify_plan,
)
from dlctl.generators.validators import validate_gold_notebook, validate_silver_notebook


app = typer.Typer(help="Notebook Fabric: planejar e criar piloto com definição ipynb correta.")


def _validate_contract(path: Path, contract: str) -> None:
    if contract == "silver":
        outcome = validate_silver_notebook(path)
    elif contract == "gold":
        outcome = validate_gold_notebook(path)
    else:
        return
    if not outcome.ok:
        raise NotebookPlanError("; ".join(outcome.errors))


@app.command("plan-create")
def plan_create(
    notebook: str = typer.Option(..., "--notebook"),
    display_name: str = typer.Option(..., "--display-name"),
    contract: str = typer.Option(..., "--contract", help="silver | gold | generic"),
    folder_path: str = typer.Option(None, "--folder-path"),
    description: str = typer.Option("", "--description"),
    out_plan: str = typer.Option(..., "--out-plan"),
    profile: str = typer.Option(None, "--profile"),
):
    """Gera plano offline; não autentica e não chama Fabric."""
    if contract not in {"silver", "gold", "generic"}:
        raise typer.BadParameter("--contract deve ser silver, gold ou generic")
    p = get_profile(profile)
    notebook_path = Path(notebook).resolve()
    try:
        _validate_contract(notebook_path, contract)
        plan = create_plan(
            notebook_path=notebook_path,
            display_name=display_name,
            environment=p.environment,
            workspace_name=p.microsoft.default_workspace_name,
            workspace_id=p.microsoft.default_workspace_id,
            contract=contract,
            folder_path=folder_path,
            description=description,
        )
    except NotebookPlanError as exc:
        console.print(f"[red]Plano recusado:[/red] {exc}")
        raise typer.Exit(code=1)
    output = Path(out_plan)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(json.dumps({
        "status": "PLANNED_NOT_APPLIED",
        "plan": str(output),
        "planSha256": plan["planSha256"],
        "notebookSha256": plan["notebookSha256"],
        "target": f"{plan['workspaceName']}/{plan['displayName']}",
    }, indent=2, ensure_ascii=False))


@app.command("apply-create")
@handle_security_error
def apply_create(
    plan_path: str = typer.Option(..., "--plan"),
    confirm_write: bool = typer.Option(False, "--confirm-write"),
    profile: str = typer.Option(None, "--profile"),
):
    """Cria exatamente um Notebook; não executa e não atualiza item existente."""
    p = get_profile(profile)
    gate = get_gate(p)
    gate.authorize_write(confirm_write=confirm_write)
    try:
        plan = load_and_verify_plan(plan_path)
        if plan["environment"] != p.environment.upper():
            raise NotebookPlanError("Ambiente do plano diverge do profile.")
        if plan.get("workspaceName") != p.microsoft.default_workspace_name:
            raise NotebookPlanError("Workspace do plano diverge do profile.")
        if plan.get("workspaceId") and plan["workspaceId"] != p.microsoft.default_workspace_id:
            raise NotebookPlanError("Workspace ID do plano diverge do profile.")
        if not p.microsoft.default_workspace_id:
            raise NotebookPlanError("FABRIC_WORKSPACE_ID ausente.")

        client = build_client_from_profile(p)
        existing = client.find_item_by_name(plan["displayName"], "Notebook")
        if existing:
            raise NotebookPlanError(
                f"Notebook já existe ({existing.get('id')}); apply-create nunca sobrescreve."
            )
        folder_id = None
        if plan.get("folderPath"):
            folder_id = client.resolve_folder(plan["folderPath"])
            if not folder_id:
                raise NotebookPlanError(f"Pasta Fabric não encontrada: {plan['folderPath']}")
        result = client.create_notebook(
            display_name=plan["displayName"],
            definition=build_definition(plan["notebookPath"]),
            folder_id=folder_id,
            description=plan["description"],
        )
    except (NotebookPlanError, FabricApiError) as exc:
        console.print(f"[red]Criação recusada/falhou:[/red] {exc}")
        raise typer.Exit(code=1)
    console.print(json.dumps({
        "status": result.get("status", "UNKNOWN"),
        "item": result.get("item"),
        "operationId": result.get("operationId"),
        "rollback": "Excluir manualmente apenas o itemId retornado; nenhum notebook foi executado.",
    }, indent=2, ensure_ascii=False))
