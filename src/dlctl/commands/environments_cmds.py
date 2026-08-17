"""dlctl environments ... — inspect/export/diff/publish (environment_workflow.md)."""
from __future__ import annotations

import json
from pathlib import Path

import typer

from dlctl.commands.common import console, get_gate, get_profile, handle_security_error
from dlctl.connectors.fabric_api import FabricApiError, build_client_from_profile

app = typer.Typer(help="Ambientes Fabric: inspect/export/diff/publish/rollback (gated).")


@app.command("inspect")
def inspect_cmd(
    workspace: str = typer.Option(..., "--workspace"),
    environment: str = typer.Option(..., "--environment"),
    profile: str = typer.Option(None, "--profile"),
):
    p = get_profile(profile)
    try:
        client = build_client_from_profile(p)
        client.workspace_id = client.resolve_workspace_id(workspace)
        env_item = client.find_item_by_name(environment, "Environment")
        if not env_item:
            console.print(f"[yellow]Environment '{environment}' não encontrado em '{workspace}'[/yellow]")
            raise typer.Exit(code=1)
        detail = client.get_environment(env_item["id"])
        console.print(detail)
    except FabricApiError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)


@app.command("export")
def export_cmd(
    workspace: str = typer.Option(..., "--workspace"),
    environment: str = typer.Option(..., "--environment"),
    out: str = typer.Option(..., "--out"),
    profile: str = typer.Option(None, "--profile"),
):
    p = get_profile(profile)
    client = build_client_from_profile(p)
    client.workspace_id = client.resolve_workspace_id(workspace)
    env_item = client.find_item_by_name(environment, "Environment")
    if not env_item:
        console.print(f"[yellow]Environment '{environment}' não encontrado[/yellow]")
        raise typer.Exit(code=1)
    detail = client.get_environment(env_item["id"])
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "environment_export.json").write_text(json.dumps(detail, indent=2), encoding="utf-8")
    import hashlib
    sha = hashlib.sha256(json.dumps(detail, sort_keys=True).encode()).hexdigest()
    (out_dir / "manifest.sha256").write_text(sha, encoding="utf-8")
    console.print(f"[green]Export salvo em[/green] {out_dir} (sha256={sha[:12]}...)")


@app.command("publish")
@handle_security_error
def publish_cmd(
    workspace: str = typer.Option(..., "--workspace"),
    environment_id: str = typer.Option(..., "--environment-id"),
    confirm_publish: bool = typer.Option(False, "--confirm-publish"),
    profile: str = typer.Option(None, "--profile"),
):
    p = get_profile(profile)
    gate = get_gate(p)
    gate.authorize_publish(confirm_publish=confirm_publish)
    client = build_client_from_profile(p)
    client.workspace_id = client.resolve_workspace_id(workspace)
    result = client.publish_environment(environment_id)
    console.print(f"[green]Publicação iniciada[/green]: {result}")
