"""dlctl etl-silver ... — geração/validação de notebooks Bronze->Silver (etl-oracle-fabric)."""
from __future__ import annotations

from pathlib import Path

import typer

from dlctl.commands.common import console, get_profile
from dlctl.core.mapping import load_mapping
from dlctl.core.state import log_activity
from dlctl.generators.silver_generator import generate_silver_notebook, write_notebook
from dlctl.generators.validators import validate_silver_notebook

app = typer.Typer(help="Geração e validação de notebooks Silver (Bronze -> Silver).")

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
    bronze_base_path: str = typer.Option("Files/Bronze", "--bronze-base-path"),
    silver_base_path: str = typer.Option("Tables/silver", "--silver-base-path"),
    write: bool = typer.Option(False, "--write", help="Grava o notebook em disco; sem isso é apenas dry preview."),
    profile: str = typer.Option(None, "--profile"),
):
    """Gera um notebook Silver para uma tabela específica (pilot)."""
    p = get_profile(profile)
    entries = load_mapping(p, layer="bronze_to_silver", domain=domain)
    entry = _find_entry(entries, table)
    if not entry:
        console.print(f"[red]Tabela '{table}' não encontrada no mapeamento bronze_to_silver.csv[/red]")
        raise typer.Exit(code=1)
    if entry.status not in GO_STATUSES:
        console.print(f"[yellow]STOP[/yellow]: status='{entry.status}' não permite geração (Status Gates).")
        raise typer.Exit(code=1)

    nb = generate_silver_notebook(entry, bronze_base_path, silver_base_path, project_root=Path.cwd())
    out_path = p.paths.notebooks_silver_root / f"{table}.ipynb"
    if write:
        write_notebook(nb, out_path)
        console.print(f"[green]Notebook gravado:[/green] {out_path}")
        log_activity(p, f"Notebook Silver gerado: {table}", source="etl-oracle-fabric")
    else:
        console.print(f"[cyan]Dry preview OK[/cyan] (use --write para gravar em {out_path})")


@app.command("generate-all")
def generate_all(
    domain: str = typer.Option(None, "--domain"),
    bronze_base_path: str = typer.Option("Files/Bronze", "--bronze-base-path"),
    silver_base_path: str = typer.Option("Tables/silver", "--silver-base-path"),
    write: bool = typer.Option(False, "--write"),
    approved: bool = typer.Option(False, "--approved", help="Confirma aprovação explícita do usuário para gerar todos."),
    profile: str = typer.Option(None, "--profile"),
):
    """Gera notebooks para todas as tabelas GO do domínio — requer --approved
    (equivalente à 'aprovação explícita do usuário' exigida pela skill)."""
    if not approved:
        console.print("[yellow]BLOCKED[/yellow]: generate-all requer --approved (aprovação explícita do usuário).")
        raise typer.Exit(code=3)
    p = get_profile(profile)
    entries = load_mapping(p, layer="bronze_to_silver", domain=domain)
    generated, blocked = [], []
    for entry in entries:
        if entry.status in GO_STATUSES:
            nb = generate_silver_notebook(entry, bronze_base_path, silver_base_path, project_root=Path.cwd())
            out_path = p.paths.notebooks_silver_root / f"{entry.target_table}.ipynb"
            if write:
                write_notebook(nb, out_path)
            generated.append(entry.target_table)
        else:
            blocked.append((entry.target_table, entry.status))
    console.print(f"[green]Gerados:[/green] {generated}")
    if blocked:
        console.print(f"[yellow]Bloqueados:[/yellow] {blocked}")
    log_activity(p, f"generate-all: {len(generated)} gerados, {len(blocked)} bloqueados", source="etl-oracle-fabric")


@app.command("validate")
def validate(notebook_path: str = typer.Argument(...)):
    """Valida um notebook Silver contra o Notebook Contract."""
    outcome = validate_silver_notebook(notebook_path)
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
