"""dlctl manifest ... — Canonical Write Workflow: validate -> plan -> dry-run -> apply -> status."""
from __future__ import annotations

import json
from pathlib import Path

import typer
import yaml

from dlctl.commands.common import console, get_gate, get_profile, handle_security_error
from dlctl.connectors.fabric_api import FabricApiError, build_client_from_profile
from dlctl.core import manifest as manifest_engine
from dlctl.core.state import ManifestRecord, get_session

app = typer.Typer(help="Motor de manifests: validate/plan/dry-run/apply/status/templates/init.")


def _try_fabric_client(profile):
    try:
        return build_client_from_profile(profile)
    except Exception:
        return None


@app.command("validate")
def validate_cmd(manifest_path: str = typer.Option(..., "--manifest")):
    m = manifest_engine.load_manifest(manifest_path)
    result = manifest_engine.validate(m)
    if result.ok:
        console.print(f"[green]VÁLIDO[/green]: {m.manifest_id}")
    else:
        console.print(f"[red]INVÁLIDO[/red]: {m.manifest_id}")
    for issue in result.issues:
        color = "red" if issue.level == "error" else "yellow"
        console.print(f"  [{color}]{issue.level}[/{color}]: {issue.message}")
    if not result.ok:
        raise typer.Exit(code=1)


@app.command("plan")
def plan_cmd(
    manifest_path: str = typer.Option(..., "--manifest"),
    out_plan: str = typer.Option(None, "--out-plan"),
    profile: str = typer.Option(None, "--profile"),
):
    p = get_profile(profile)
    m = manifest_engine.load_manifest(manifest_path)
    client = _try_fabric_client(p)
    result = manifest_engine.plan(m, fabric_client=client)
    console.print(f"Ação planejada: [bold]{result.action}[/bold] — {result.diff_summary}")
    out_path = Path(out_plan) if out_plan else Path(manifest_path).with_suffix(".plan.json")
    out_path.write_text(json.dumps(result.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"Plano salvo em: {out_path}")


@app.command("dry-run")
def dry_run_cmd(
    manifest_path: str = typer.Option(..., "--manifest"),
    plan_path: str = typer.Option(None, "--plan"),
):
    m = manifest_engine.load_manifest(manifest_path)
    plan_file = Path(plan_path) if plan_path else Path(manifest_path).with_suffix(".plan.json")
    if not plan_file.exists():
        console.print(f"[red]Plano não encontrado[/red]: {plan_file}. Rode 'manifest plan' primeiro.")
        raise typer.Exit(code=1)
    plan_result = manifest_engine.PlanResult(**json.loads(plan_file.read_text(encoding="utf-8")))
    outcome = manifest_engine.dry_run(m, plan_result)
    if outcome.ok:
        console.print("[green]dry-run OK[/green]: nenhuma divergência de hash/definição.")
    else:
        for issue in outcome.issues:
            console.print(f"  [red]erro[/red]: {issue.message}")
        raise typer.Exit(code=1)


@app.command("apply")
@handle_security_error
def apply_cmd(
    manifest_path: str = typer.Option(..., "--manifest"),
    plan_path: str = typer.Option(None, "--plan"),
    confirm_write: bool = typer.Option(False, "--confirm-write"),
    confirm_production: bool = typer.Option(False, "--confirm-production"),
    confirm_move: bool = typer.Option(False, "--confirm-move"),
    run_id: str = typer.Option("", "--run-id"),
    profile: str = typer.Option(None, "--profile"),
):
    p = get_profile(profile)
    m = manifest_engine.load_manifest(manifest_path)
    plan_file = Path(plan_path) if plan_path else Path(manifest_path).with_suffix(".plan.json")
    if not plan_file.exists():
        console.print(f"[red]Plano não encontrado[/red]: {plan_file}. Rode 'manifest plan' primeiro.")
        raise typer.Exit(code=1)
    plan_result = manifest_engine.PlanResult(**json.loads(plan_file.read_text(encoding="utf-8")))

    gate = get_gate(p, run_id=run_id)
    client = _try_fabric_client(p)
    result = manifest_engine.apply(
        m, plan_result, gate,
        confirm_write=confirm_write, confirm_production=confirm_production, confirm_move=confirm_move,
        fabric_client=client, run_id=run_id,
    )
    color = {"applied": "green", "noop": "cyan", "manual_required": "yellow", "failed": "red"}.get(result["status"], "white")
    console.print(f"[{color}]{result['status']}[/{color}]: {result}")
    if result["status"] == "failed":
        raise typer.Exit(code=1)


@app.command("status")
def status_cmd(manifest_id: str = typer.Option(..., "--manifest-id"), profile: str = typer.Option(None, "--profile")):
    p = get_profile(profile)
    with get_session(p) as session:
        from sqlmodel import select
        rec = session.exec(select(ManifestRecord).where(ManifestRecord.manifest_id == manifest_id)).first()
    if not rec:
        console.print(f"[yellow]Nenhum registro encontrado para manifest_id={manifest_id}[/yellow]")
        raise typer.Exit(code=1)
    console.print(rec.model_dump())


@app.command("templates")
def templates_cmd():
    """Lista os templates de manifest disponíveis (DataPipeline, Notebook, Environment, CopyJob)."""
    console.print("Templates disponíveis: datapipeline, notebook, environment, copyjob, variablelibrary")
    console.print("Use 'dlctl manifest init --resource-type <tipo> --out <arquivo.yaml>'")


@app.command("init")
def init_cmd(
    resource_type: str = typer.Option(..., "--resource-type"),
    manifest_id: str = typer.Option(..., "--manifest-id"),
    display_name: str = typer.Option(..., "--display-name"),
    folder_path: str = typer.Option("pipelines", "--folder-path"),
    out: str = typer.Option(..., "--out"),
):
    """Gera um esqueleto de manifest YAML seguindo datapipeline_manifest_patterns.md."""
    skeleton = {
        "manifest_id": manifest_id,
        "environment": "DEV",
        "operation": "ensure",
        "owner": "dlctl-agent",
        "resource_type": resource_type,
        "displayName": display_name,
        "description": "",
        "safety": {"allow_write": True, "delete_allowed": False, "allow_move_existing": True},
        "desired_state": {
            "displayName": display_name,
            "description": "",
            "folderPath": folder_path,
            "definition_file": "../fabric_definitions/CHANGE_ME.definition.json",
            "parameters": {},
        },
    }
    Path(out).write_text(yaml.safe_dump(skeleton, sort_keys=False, allow_unicode=True), encoding="utf-8")
    console.print(f"[green]Manifest esqueleto criado em[/green] {out}")
