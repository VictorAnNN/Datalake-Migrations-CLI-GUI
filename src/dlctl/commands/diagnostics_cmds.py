"""dlctl pipelines ... — diagnose-run (Incid. 1, P0): agrega erros/atividades
de uma execução de pipeline sem despejar o payload bruto de queryactivityruns.

Modo offline (padrão, sem chamada real ao Fabric nesta sessão): opera sobre
um JSON de atividades já exportado (ex.: salvo por evidência anterior).
Modo online (requer client autenticado configurado pelo usuário) chama
`query_activity_runs` de verdade — não usado/testado nesta sessão.
"""
from __future__ import annotations

import json
from pathlib import Path

import typer

from dlctl.commands.common import console, get_profile
from dlctl.core.secrets import redact

app = typer.Typer(help="Diagnóstico de pipelines (diagnose-run) e espera de execução (wait).")


@app.command("diagnose-run")
def diagnose_run_cmd(
    run_export: str = typer.Option(None, "--run-export", help="JSON local com o export de queryactivityruns (modo offline)."),
    item_id: str = typer.Option(None, "--item"),
    run_id: str = typer.Option(None, "--run-id"),
    failed_only: bool = typer.Option(True, "--failed-only/--all"),
    profile: str = typer.Option(None, "--profile"),
):
    """Agrega erros/activityRunId/iterationHash/notebook run id/Copy output.
    Sem --run-export, tentaria consultar o Fabric ao vivo (não usado nesta
    sessão): exige credenciais reais e client configurado pelo usuário."""
    if run_export:
        raw = json.loads(Path(run_export).read_text(encoding="utf-8-sig"))
        activities = raw.get("value", raw.get("activityRuns", []))
        diagnosed = []
        for act in activities:
            status = act.get("status", "")
            if failed_only and status not in {"Failed", "Cancelled"}:
                continue
            diagnosed.append({
                "activityName": act.get("activityName"), "activityRunId": act.get("activityRunId"),
                "status": status, "error": redact(act.get("error", {})),
            })
        console.print(f"Total de atividades: {len(activities)} | Diagnosticadas: {len(diagnosed)}")
        for d in diagnosed:
            console.print(f"  - [{d['status']}] {d['activityName']} (activityRunId={d['activityRunId']}): {d['error']}")
        return

    p = get_profile(profile)
    if not (item_id and run_id):
        console.print("[yellow]Informe --run-export (offline) ou --item + --run-id (online).[/yellow]")
        raise typer.Exit(code=2)
    try:
        from dlctl.connectors.fabric_api import build_client_from_profile
        client = build_client_from_profile(p)
        result = client.diagnose_pipeline_run(item_id, run_id, failed_only=failed_only)
        console.print(result)
    except Exception as exc:
        console.print(f"[yellow]manual_required[/yellow]: {exc}")
        raise typer.Exit(code=1)


@app.command("wait")
def wait_cmd(
    run_id: str = typer.Option(..., "--run-id"),
    timeout: int = typer.Option(1800, "--timeout"),
    poll_interval: int = typer.Option(10, "--poll-interval"),
):
    """Estrutura de espera retomável por run-id (Incid. 1, P1). Requer client
    autenticado real para funcionar de fato; não executado nesta sessão."""
    console.print(
        f"[cyan]manual_required[/cyan]: espera por run_id={run_id} (timeout={timeout}s, "
        f"poll={poll_interval}s) requer Fabric client autenticado configurado no .env. "
        "Nenhuma chamada foi feita nesta sessão por segurança do ambiente DEV."
    )
