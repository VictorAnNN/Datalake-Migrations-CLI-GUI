"""dlctl leases ... — lock leve entre agentes/execuções (Incid. 1, P0)."""
from __future__ import annotations

import typer

from dlctl.commands.common import console, get_profile, print_table
from dlctl.core.state import acquire_lease, list_leases, release_lease

app = typer.Typer(help="Leases: lock leve entre agentes sobre itens/tabelas (evita conflito de escrita concorrente).")


@app.command("acquire")
def acquire_cmd(
    owner: str = typer.Option(..., "--owner"),
    workspace: str = typer.Option("", "--workspace"),
    item_ids: str = typer.Option("", "--item-ids", help="CSV de item IDs"),
    tables: str = typer.Option("", "--tables", help="CSV de nomes de tabela"),
    ttl: int = typer.Option(3600, "--ttl", help="TTL em segundos"),
    profile: str = typer.Option(None, "--profile"),
):
    p = get_profile(profile)
    result = acquire_lease(
        p, workspace=workspace,
        item_ids=[i for i in item_ids.split(",") if i], tables=[t for t in tables.split(",") if t],
        owner=owner, ttl_seconds=ttl,
    )
    if result["ok"]:
        console.print(f"[green]Lease adquirida:[/green] {result['lease_id']}")
    else:
        console.print(f"[yellow]BLOCKED[/yellow]: {result['message']}")
        raise typer.Exit(code=3)


@app.command("list")
def list_cmd(active_only: bool = typer.Option(True, "--active-only/--all"), profile: str = typer.Option(None, "--profile")):
    p = get_profile(profile)
    leases = list_leases(p, active_only=active_only)
    print_table("Leases", ["lease_id", "owner", "workspace", "item_ids", "tables", "status", "acquired_at"],
                [[l["lease_id"], l["owner"], l["workspace"], l["item_ids"], l["tables"], l["status"], l["acquired_at"]] for l in leases])


@app.command("release")
def release_cmd(lease_id: str = typer.Option(..., "--lease-id"), owner: str = typer.Option(..., "--owner"),
                 profile: str = typer.Option(None, "--profile")):
    p = get_profile(profile)
    result = release_lease(p, lease_id, owner)
    if result["ok"]:
        console.print(f"[green]Lease liberada:[/green] {lease_id}")
    else:
        console.print(f"[red]{result['message']}[/red]")
        raise typer.Exit(code=1)
