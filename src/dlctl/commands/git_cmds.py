"""dlctl git ... — Fabric Git: read-first, writes gated (git_workflow.md)."""
from __future__ import annotations

import typer

from dlctl.commands.common import console, get_gate, get_profile, handle_security_error
from dlctl.connectors.fabric_api import FabricApiError, build_client_from_profile

app = typer.Typer(help="Fabric Git: status/diff (leitura) e commit/update-from-git (gated).")


@app.command("status")
def status_cmd(workspace: str = typer.Option(..., "--workspace"), profile: str = typer.Option(None, "--profile")):
    p = get_profile(profile)
    try:
        client = build_client_from_profile(p)
        client.workspace_id = client.resolve_workspace_id(workspace)
        console.print(client.git_status())
    except FabricApiError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)


@app.command("diff-summary")
def diff_summary_cmd(workspace: str = typer.Option(..., "--workspace"), profile: str = typer.Option(None, "--profile")):
    p = get_profile(profile)
    client = build_client_from_profile(p)
    client.workspace_id = client.resolve_workspace_id(workspace)
    status = client.git_status()
    conflict_count = status.get("conflictCount", 0)
    console.print(f"workspaceHead={status.get('workspaceHead')} conflictCount={conflict_count}")


@app.command("plan-commit")
def plan_commit_cmd(
    workspace: str = typer.Option(..., "--workspace"),
    item_ids: str = typer.Option("", "--item-ids", help="CSV de object IDs; vazio = todos os itens alterados."),
    profile: str = typer.Option(None, "--profile"),
):
    """Planejamento de commit com seleção de itens (Incid. 1, P1: antes só
    `git commit` aceitava --item-ids; aqui o plano já mostra o delta filtrado)."""
    p = get_profile(profile)
    client = build_client_from_profile(p)
    client.workspace_id = client.resolve_workspace_id(workspace)
    ids = [i for i in item_ids.split(",") if i] or None
    plan = client.git_plan_commit(item_ids=ids)
    console.print(f"workspaceHead={plan['workspaceHead']} conflictCount={plan['conflictCount']} "
                  f"selectedCount={plan['selectedCount']}")
    for c in plan["selectedChanges"]:
        console.print(f"  - {c}")


@app.command("commit")
@handle_security_error
def commit_cmd(
    workspace: str = typer.Option(..., "--workspace"),
    message: str = typer.Option(..., "--message"),
    expect_head: str = typer.Option(..., "--expect-head"),
    item_ids: str = typer.Option("", "--item-ids", help="CSV de object IDs; vazio = todos os itens alterados."),
    confirm_git_commit: bool = typer.Option(False, "--confirm-git-commit"),
    profile: str = typer.Option(None, "--profile"),
):
    p = get_profile(profile)
    gate = get_gate(p)
    gate.authorize_git_commit(confirm_git_commit=confirm_git_commit)
    client = build_client_from_profile(p)
    client.workspace_id = client.resolve_workspace_id(workspace)
    status = client.git_status()
    if status.get("conflictCount", 0) > 0:
        console.print("[red]Abortado[/red]: conflictCount > 0.")
        raise typer.Exit(code=1)
    if status.get("workspaceHead") != expect_head:
        console.print(f"[red]Abortado[/red]: workspaceHead atual ({status.get('workspaceHead')}) != --expect-head.")
        raise typer.Exit(code=1)
    ids = [i for i in item_ids.split(",") if i] or None
    result = client.git_commit(message, item_ids=ids)
    console.print(f"[green]Commit realizado[/green]: {result}")


@app.command("update-from-git")
@handle_security_error
def update_from_git_cmd(
    workspace: str = typer.Option(..., "--workspace"),
    expect_head: str = typer.Option(..., "--expect-head"),
    confirm_git_update: bool = typer.Option(False, "--confirm-git-update"),
    profile: str = typer.Option(None, "--profile"),
):
    p = get_profile(profile)
    gate = get_gate(p)
    gate.authorize_git_update(confirm_git_update=confirm_git_update)
    client = build_client_from_profile(p)
    client.workspace_id = client.resolve_workspace_id(workspace)
    status = client.git_status()
    if status.get("conflictCount", 0) > 0 or status.get("workspaceHead") != expect_head:
        console.print("[red]Abortado[/red]: conflito ou workspaceHead divergente.")
        raise typer.Exit(code=1)
    result = client.git_update_from_git()
    console.print(f"[green]Atualizado a partir do Git[/green]: {result}")
