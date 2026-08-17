"""dlctl execute ... — wrapper fino sobre dlctl.core.execution + campaign."""
from __future__ import annotations

import typer

from dlctl.commands.common import console, get_gate, get_profile, handle_security_error
from dlctl.connectors.fabric_api import build_client_from_profile
from dlctl.core.campaign import run_campaign
from dlctl.core.execution import apply_execution, dry_run_execution, load_execution_manifest, plan_execution, poll_job_status

app = typer.Typer(help="Execução gated de notebooks/pipelines/dataflows/copy jobs, campanhas multi-alvo e status polling.")


@app.command("plan")
def plan_cmd(manifest: str = typer.Option(..., "--manifest")):
    m = load_execution_manifest(manifest)
    result = plan_execution(m)
    console.print(f"Execução planejada: item='{result['item_display_name']}' type='{result['item_type']}' params={result['parameters']}")
    console.print(f"[cyan]{result['note']}[/cyan]")


@app.command("dry-run")
def dry_run_cmd(manifest: str = typer.Option(..., "--manifest")):
    m = load_execution_manifest(manifest)
    issues = dry_run_execution(m)
    if issues:
        for i in issues:
            console.print(f"[red]erro[/red]: {i}")
        raise typer.Exit(code=1)
    console.print("[green]dry-run OK[/green]")


@app.command("apply")
@handle_security_error
def apply_cmd(
    manifest: str = typer.Option(..., "--manifest"),
    confirm_execute: bool = typer.Option(False, "--confirm-execute"),
    run_id: str = typer.Option("", "--run-id"),
    profile: str = typer.Option(None, "--profile"),
):
    p = get_profile(profile)
    m = load_execution_manifest(manifest)
    gate = get_gate(p, run_id=run_id)
    try:
        client = build_client_from_profile(p)
    except Exception:
        client = None
    result = apply_execution(m, gate, confirm_execute=confirm_execute, fabric_client=client, run_id=run_id)
    color = {"started": "green", "manual_required": "yellow", "failed": "red"}.get(result["status"], "white")
    console.print(f"[{color}]{result['status']}[/{color}]: {result}")
    if result["status"] == "failed":
        raise typer.Exit(code=1)


@app.command("campaign")
@handle_security_error
def campaign_cmd(
    manifest: str = typer.Option(..., "--manifest", help="Manifesto multi-alvo (campaign_id + targets + depends_on)."),
    confirm_write: bool = typer.Option(False, "--confirm-write"),
    confirm_execute: bool = typer.Option(False, "--confirm-execute"),
    profile: str = typer.Option(None, "--profile"),
):
    """Orquestrador multi-alvo (Incid. 2, P0): preflight->publish->execute->
    wait->logs->classify->delta->sql_endpoint->seal, serial, isolamento de
    falha por DAG. Sem credenciais Fabric configuradas, as fases de rede
    reportam manual_required/skipped automaticamente (nenhuma chamada real
    é feita nesta sessão, por instrução explícita de segurança do DEV)."""
    p = get_profile(profile)
    try:
        client = build_client_from_profile(p)
    except Exception:
        client = None

    def on_step(target: str, phase: str, status: str, detail: str) -> None:
        color = {"success": "green", "blocked": "yellow", "skipped": "cyan", "failed": "red"}.get(status, "white")
        console.print(f"[{color}][{target}/{phase}] {status}[/{color}] — {detail}")

    result = run_campaign(p, manifest, confirm_write=confirm_write, confirm_execute=confirm_execute,
                           fabric_client=client, on_step=on_step)
    color = {"success": "green", "failed": "red"}.get(result["status"], "white")
    console.print(f"[{color}]Campaign {result['status']}[/{color}]: {result['campaign_id']} — {result['summary']}")
    if result["status"] == "failed":
        raise typer.Exit(code=1)


@app.command("status")
def status_cmd(
    item_id: str = typer.Option(..., "--item-id"),
    job_instance_id: str = typer.Option(..., "--job-instance-id"),
    wait: bool = typer.Option(False, "--wait", help="Faz polling até status terminal ou timeout."),
    poll_seconds: float = typer.Option(5.0, "--poll-seconds"),
    timeout_seconds: float = typer.Option(300.0, "--timeout-seconds"),
    profile: str = typer.Option(None, "--profile"),
):
    """Consulta (e opcionalmente aguarda) o status real de uma execução no
    Fabric — leitura pura (GET), não passa por nenhum gate de escrita.
    Requer Fabric client autenticado configurado no .env; sem isso, retorna
    manual_required explicitamente."""
    p = get_profile(profile)
    try:
        client = build_client_from_profile(p)
    except Exception as exc:
        console.print(f"[yellow]manual_required[/yellow]: Fabric client não configurado ({exc}).")
        raise typer.Exit(code=1)
    result = poll_job_status(client, item_id, job_instance_id, wait=wait,
                              poll_seconds=poll_seconds, timeout_seconds=timeout_seconds)
    color = {"Completed": "green", "Failed": "red", "Cancelled": "yellow", "TIMEOUT": "yellow"}.get(result["status"], "white")
    console.print(f"[{color}]{result['status']}[/{color}] (terminal={result['terminal']}, tentativas={result['attempts']})")
    if result["status"] not in {"Completed"}:
        raise typer.Exit(code=1)

