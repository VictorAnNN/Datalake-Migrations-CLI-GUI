"""dlctl etl-gold ... — geração/validação de notebooks Silver->Gold (etl-oracle-fabric-gold)."""
from __future__ import annotations

from pathlib import Path

import typer

from dlctl.commands.common import console, get_profile
from dlctl.core.mapping import load_mapping
from dlctl.core.state import log_activity
from dlctl.generators.gold_generator import generate_gold_notebook, write_notebook
from dlctl.generators.validators import validate_gold_notebook

app = typer.Typer(help="Geração e validação de notebooks Gold (Silver -> Gold).")

GO_STATUSES = {"spark_ready", "needs_rewrite"}


def _find_entry(entries, table: str):
    for e in entries:
        if e.target_table == table:
            return e
    return None


@app.command("generate")
def generate(
    table: str = typer.Option(..., "--table"),
    domain: str = typer.Option(None, "--domain"),
    silver_base_path: str = typer.Option(..., "--silver-base-path"),
    gold_base_path: str = typer.Option(..., "--gold-base-path"),
    write: bool = typer.Option(False, "--write"),
    profile: str = typer.Option(None, "--profile"),
):
    """Gera um notebook Gold pilot para uma tabela específica."""
    p = get_profile(profile)
    entries = load_mapping(p, layer="silver_to_gold", domain=domain)
    entry = _find_entry(entries, table)
    if not entry:
        console.print(f"[red]Tabela '{table}' não encontrada no mapeamento silver_to_gold.csv[/red]")
        raise typer.Exit(code=1)
    if entry.status not in GO_STATUSES:
        console.print(f"[yellow]STOP[/yellow]: status='{entry.status}' não permite geração (Gold Gates).")
        raise typer.Exit(code=1)

    nb = generate_gold_notebook(entry, silver_base_path, gold_base_path, project_root=Path.cwd())
    out_path = p.paths.notebooks_gold_root / f"{table}.ipynb"
    if write:
        write_notebook(nb, out_path)
        console.print(f"[green]Notebook gravado:[/green] {out_path}")
        log_activity(p, f"Notebook Gold gerado: {table}", source="etl-oracle-fabric-gold")
    else:
        console.print(f"[cyan]Dry preview OK[/cyan] (use --write para gravar em {out_path})")


@app.command("validate")
def validate(notebook_path: str = typer.Argument(...)):
    """Valida um notebook Gold contra os Gold Gates."""
    outcome = validate_gold_notebook(notebook_path)
    if outcome.ok:
        console.print(f"[green]VÁLIDO[/green]: {notebook_path}")
    else:
        console.print(f"[red]INVÁLIDO[/red]: {notebook_path}")
        for e in outcome.errors:
            console.print(f"  - erro: {e}")
    for w in outcome.warnings:
        console.print(f"  - aviso: {w}")
    if not outcome.ok:
        raise typer.Exit(code=1)


@app.command("reconcile-gold-scope")
def reconcile_gold_scope(domain: str = typer.Option(None, "--domain"), profile: str = typer.Option(None, "--profile")):
    """Verifica se os Golds dependem apenas de Silvers já validados (marcados go)."""
    from dlctl.core.mapping import reconcile_scope

    p = get_profile(profile)
    silver_entries = load_mapping(p, layer="bronze_to_silver", domain=domain)
    validated_silvers = {e.target_table for e in silver_entries if e.status in GO_STATUSES}
    result = reconcile_scope(p, layer="silver_to_gold", domain=domain, allowed_source_tables=validated_silvers)
    console.print(f"Veredito Gold: [bold]{result['verdict']}[/bold]")
    if result["blocked"]:
        for b in result["blocked"]:
            console.print(f"  - bloqueado: {b['target']} <- {b['source']} ({b['reason']})")
