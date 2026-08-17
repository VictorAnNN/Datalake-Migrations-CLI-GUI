"""dlctl pipeline ... — wrapper fino do CLI sobre dlctl.core.pipeline.run_order_tracking
(a lógica de negócio vive lá para ser compartilhada com o dashboard)."""
from __future__ import annotations

import typer

from dlctl.commands.common import console, get_profile
from dlctl.core.pipeline import run_order_tracking

app = typer.Typer(help="Router de pipeline Order Tracking (Bronze->Silver->Gold->Fabric).")


@app.command("run-order-tracking")
def run_order_tracking_cmd(
    domain: str = typer.Option("ORDER_TRACKING", "--domain"),
    bronze_base_path: str = typer.Option("Files/Bronze", "--bronze-base-path"),
    silver_base_path: str = typer.Option("Tables/silver", "--silver-base-path"),
    gold_base_path: str = typer.Option("Tables/gold", "--gold-base-path"),
    write: bool = typer.Option(False, "--write", help="Grava notebooks gerados em disco."),
    publish: bool = typer.Option(False, "--publish", help="Tenta publicar via Fabric API (requer credenciais + gates)."),
    confirm_write: bool = typer.Option(False, "--confirm-write"),
    confirm_execute: bool = typer.Option(False, "--confirm-execute"),
    profile: str = typer.Option(None, "--profile"),
):
    p = get_profile(profile)

    def on_step(index: int, name: str, status: str, detail: str) -> None:
        color = {"success": "green", "blocked": "yellow", "skipped": "cyan", "failed": "red"}.get(status, "white")
        console.print(f"[{color}][{index}] {name}: {status}[/{color}] — {detail}")

    result = run_order_tracking(
        p, domain=domain, bronze_base_path=bronze_base_path, silver_base_path=silver_base_path,
        gold_base_path=gold_base_path, write=write, publish=publish,
        confirm_write=confirm_write, confirm_execute=confirm_execute, on_step=on_step,
    )
    color = {"success": "green", "blocked": "yellow", "failed": "red"}.get(result["status"], "white")
    console.print(f"[{color}]Run {result['status']}[/{color}]: run_id={result['run_id']} — {result['summary']}")
    if result["status"] == "blocked":
        raise typer.Exit(code=3)
    if result["status"] == "failed":
        raise typer.Exit(code=1)
