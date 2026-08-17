"""dlctl inventory ... — inventário Bronze->Silver e Silver->Gold (etl-oracle-fabric / -gold)."""
from __future__ import annotations

import typer

from dlctl.commands.common import console, get_profile, print_table
from dlctl.core.mapping import build_inventory, reconcile_scope, write_inventory_report
from dlctl.core.state import list_cached_items

app = typer.Typer(help="Inventário e reconciliação de escopo Bronze/Silver/Gold.")

cache_app = typer.Typer(help="Cache local de resolução de itens Fabric (prefer-resolver).")
app.add_typer(cache_app, name="cache")


@cache_app.command("show")
def cache_show(profile: str = typer.Option(None, "--profile")):
    """Mostra todos os itens Fabric já resolvidos e guardados em cache local."""
    p = get_profile(profile)
    items = list_cached_items(p)
    if not items:
        console.print("[yellow]Cache vazio.[/yellow] Itens são cacheados automaticamente ao serem resolvidos via manifest/execute/campaign.")
        return
    print_table("Item Cache", ["workspace_id", "item_type", "display_name", "item_id", "cached_at"],
                [[i["workspace_id"], i["item_type"], i["display_name"], i["item_id"], i["cached_at"]] for i in items])


@cache_app.command("query")
def cache_query(item_type: str = typer.Option(None, "--type"), profile: str = typer.Option(None, "--profile")):
    """Filtra o cache por tipo de item (Notebook, DataPipeline, Lakehouse, ...)."""
    p = get_profile(profile)
    items = list_cached_items(p)
    if item_type:
        items = [i for i in items if i["item_type"] == item_type]
    print_table(f"Item Cache ({item_type or 'todos'})", ["display_name", "item_id", "cached_at"],
                [[i["display_name"], i["item_id"], i["cached_at"]] for i in items])


ORDER_TRACKING_BRONZE_24 = {
    "BRZ_PO_HEADERS_ALL", "BRZ_PO_LINES_ALL", "BRZ_PO_DISTRIBUTIONS_ALL",
    "BRZ_RCV_SHIPMENT_HEADERS", "BRZ_RCV_SHIPMENT_LINES", "BRZ_AP_INVOICES_ALL",
    "BRZ_AP_INVOICE_LINES_ALL",
    # ... completar com as 24 tabelas Bronze extraídas do cliente
}


@app.command("silver")
def inventory_silver(
    domain: str = typer.Option(None, "--domain"),
    profile: str = typer.Option(None, "--profile"),
):
    """Equivalente a `etl_oracle_fabric inventory` — Bronze->Silver."""
    p = get_profile(profile)
    inv = write_inventory_report(p, layer="bronze_to_silver", domain=domain)
    print_table(
        f"Inventário Bronze->Silver ({domain or 'ALL'})",
        ["status", "quantidade"],
        [[k, v] for k, v in inv["by_status"].items()],
    )
    console.print(f"JSON: {inv['json_path']}\nMarkdown: {inv['markdown_path']}")


@app.command("gold")
def inventory_gold(
    domain: str = typer.Option(None, "--domain"),
    profile: str = typer.Option(None, "--profile"),
):
    """Equivalente a `etl_oracle_fabric_gold inventory-gold`."""
    p = get_profile(profile)
    inv = write_inventory_report(p, layer="silver_to_gold", domain=domain)
    print_table(
        f"Inventário Silver->Gold ({domain or 'ALL'})",
        ["status", "quantidade"],
        [[k, v] for k, v in inv["by_status"].items()],
    )
    console.print(f"JSON: {inv['json_path']}\nMarkdown: {inv['markdown_path']}")


@app.command("reconcile-scope")
def reconcile(
    layer: str = typer.Option("bronze_to_silver", "--layer", help="bronze_to_silver | silver_to_gold"),
    domain: str = typer.Option(None, "--domain"),
    restrict_order_tracking_24: bool = typer.Option(False, "--restrict-order-tracking-24"),
    profile: str = typer.Option(None, "--profile"),
):
    """Equivalente a `reconcile-scope`: verifica se os targets dependem só das
    fontes permitidas (ex.: as 24 Bronze extraídas do Order Tracking)."""
    p = get_profile(profile)
    allowed = ORDER_TRACKING_BRONZE_24 if restrict_order_tracking_24 else None
    result = reconcile_scope(p, layer=layer, domain=domain, allowed_source_tables=allowed)
    console.print(f"Veredito: [bold]{result['verdict']}[/bold]")
    if result["blocked"]:
        print_table("Bloqueados", ["target", "source", "reason"],
                     [[b["target"], b["source"], b["reason"]] for b in result["blocked"]])
    if result["go_targets"]:
        console.print(f"GO: {', '.join(result['go_targets'])}")
