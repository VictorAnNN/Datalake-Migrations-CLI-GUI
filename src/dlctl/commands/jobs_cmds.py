"""dlctl jobs ... — driver-log com wait/retry (Incid. 2, P0) e classify-log
(classificador phase-aware de logs, Incid. 2, P0)."""
from __future__ import annotations

from pathlib import Path

import typer

from dlctl.commands.common import console, get_profile
from dlctl.core.log_classifier import classify_log

app = typer.Typer(help="Logs de job: driver-log --wait (retry só em 404 exato) e classify-log (phase-aware).")


@app.command("driver-log")
def driver_log_cmd(
    item_id: str = typer.Option(None, "--item"),
    job_instance_id: str = typer.Option(None, "--job-instance-id"),
    wait: bool = typer.Option(False, "--wait"),
    max_attempts: int = typer.Option(10, "--max-attempts"),
    poll_seconds: float = typer.Option(3.0, "--poll-seconds"),
    profile: str = typer.Option(None, "--profile"),
):
    """Busca o driver-log com retry configurável, repetindo somente o 404
    exato 'unknown app'/'no available log' (nunca outra falha)."""
    if not (item_id and job_instance_id):
        console.print("[yellow]Informe --item e --job-instance-id.[/yellow]")
        raise typer.Exit(code=2)
    p = get_profile(profile)
    try:
        from dlctl.connectors.fabric_api import build_client_from_profile
        client = build_client_from_profile(p)
        if wait:
            result = client.driver_log_wait(item_id, job_instance_id, max_attempts=max_attempts, poll_seconds=poll_seconds)
        else:
            result = {"status": "ok", "log": client.get(
                f"/workspaces/{client.workspace_id}/items/{item_id}/jobs/instances/{job_instance_id}/driverLog"
            )}
        console.print(result)
    except Exception as exc:
        console.print(f"[yellow]manual_required[/yellow]: {exc} (requer Fabric client autenticado; não usado nesta sessão).")
        raise typer.Exit(code=1)


@app.command("classify-log")
def classify_log_cmd(
    log_file: str = typer.Option(..., "--file", help="Arquivo de log local a classificar."),
    extract_notebook_exit: bool = typer.Option(True, "--extract-notebook-exit/--no-extract-notebook-exit"),
):
    """Classificador phase-aware 100% offline. Assinatura desconhecida é
    sempre NEVER_PASS por padrão (nunca deixa passar silenciosamente)."""
    log_text = Path(log_file).read_text(encoding="utf-8-sig", errors="replace")
    outcome = classify_log(log_text, extract_notebook_exit=extract_notebook_exit)
    color = {"PASS": "green", "FAIL": "red", "NEVER_PASS": "yellow"}.get(outcome.overall, "white")
    console.print(f"[{color}]Veredito geral: {outcome.overall}[/{color}] ({outcome.total_lines} linhas)")
    if outcome.unknown_lines:
        console.print(f"[yellow]{len(outcome.unknown_lines)} linha(s) com assinatura desconhecida (NEVER_PASS):[/yellow]")
        for line in outcome.unknown_lines[:15]:
            console.print(f"    {line}")
        if len(outcome.unknown_lines) > 15:
            console.print(f"    ... e mais {len(outcome.unknown_lines) - 15}")
    if outcome.functional_exit:
        console.print("[cyan]Saída funcional (sem ruído de shutdown):[/cyan]")
        console.print(outcome.functional_exit)
    if outcome.overall != "PASS":
        raise typer.Exit(code=1)
