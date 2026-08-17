"""dlctl.commands.common

Utilitários compartilhados pelos módulos de comando: obtenção de profile,
GateContext e impressão padronizada (rich) para erros/sucesso/bloqueios.
"""
from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from dlctl.config import Profile, load_profile
from dlctl.core.gates import GateContext, SecurityError

console = Console()


def get_profile(profile_name: Optional[str] = None) -> Profile:
    try:
        return load_profile(profile_name)
    except Exception as exc:
        console.print(f"[bold red]Erro ao carregar profile:[/bold red] {exc}")
        raise typer.Exit(code=2)


def get_gate(profile: Profile, run_id: str = "") -> GateContext:
    return GateContext(profile=profile, run_id=run_id)


def handle_security_error(fn):
    """Decorator: converte SecurityError em saída limpa (exit code 3) em vez de traceback."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except SecurityError as exc:
            console.print(f"[bold yellow]BLOCKED:[/bold yellow] {exc}")
            raise typer.Exit(code=3)
    return wrapper


def print_table(title: str, columns: list[str], rows: list[list]) -> None:
    table = Table(title=title)
    for c in columns:
        table.add_column(c)
    for r in rows:
        table.add_row(*[str(x) for x in r])
    console.print(table)
