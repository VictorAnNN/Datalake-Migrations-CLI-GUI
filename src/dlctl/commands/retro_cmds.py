"""dlctl retro ... — motor de "Improvement Proposals": analisa a telemetria
do próprio dlctl e gera propostas de melhoria categorizadas (repeated-failure,
throttling, gate-friction, prefer-resolver, skill-featured-unused,
permission-gap). Fluxo de aprovação manual (Stage B: manual_required)."""
from __future__ import annotations

from pathlib import Path

import typer

from dlctl.commands.common import console, get_profile, print_table
from dlctl.core.retro import analyze, approve_proposal, reject_proposal, render_markdown_report
from dlctl.core.state import list_retro_proposals

app = typer.Typer(help="Motor de retro: analisa telemetria própria e gera propostas de melhoria.")


@app.command("analyze")
def analyze_cmd(
    window_days: int = typer.Option(90, "--window-days"),
    min_count: int = typer.Option(3, "--min-count", help="Contagem mínima para considerar um sinal relevante."),
    profile: str = typer.Option(None, "--profile"),
):
    """Roda todos os detectores sobre o state.db local e persiste as propostas."""
    p = get_profile(profile)
    summary = analyze(p, window_days=window_days, min_count=min_count)
    console.print(
        f"Janela: {summary['window_start']} .. {summary['window_end']} | "
        f"eventos: {summary['event_count']} | propostas: {summary['proposal_count']}"
    )
    if summary["proposals"]:
        print_table("Propostas encontradas", ["category", "risk", "count", "key"],
                     [[pr["category"], pr["risk"], pr["count"], pr["key"]] for pr in summary["proposals"]])
    else:
        console.print("[green]Nenhum sinal relevante encontrado (ou dados insuficientes ainda).[/green]")


@app.command("list")
def list_cmd(
    category: str = typer.Option(None, "--category"),
    risk: str = typer.Option(None, "--risk"),
    status: str = typer.Option(None, "--status"),
    profile: str = typer.Option(None, "--profile"),
):
    p = get_profile(profile)
    proposals = list_retro_proposals(p, category=category, risk=risk, status=status)
    if not proposals:
        console.print("[yellow]Nenhuma proposta encontrada com esses filtros.[/yellow]")
        return
    print_table(
        "Retro Proposals", ["proposal_key", "category", "risk", "count", "status", "gate_change"],
        [[pr["proposal_key"], pr["category"], pr["risk"], pr["count"], pr["status"], pr["gate_change"]] for pr in proposals],
    )


@app.command("approve")
def approve_cmd(proposal_key: str = typer.Option(..., "--key"), profile: str = typer.Option(None, "--profile")):
    """Marca uma proposta como aprovada (Stage B: só aplique manualmente depois)."""
    p = get_profile(profile)
    if approve_proposal(p, proposal_key):
        console.print(f"[green]Aprovada:[/green] {proposal_key}")
    else:
        console.print(f"[red]Proposta não encontrada:[/red] {proposal_key}")
        raise typer.Exit(code=1)


@app.command("reject")
def reject_cmd(proposal_key: str = typer.Option(..., "--key"), profile: str = typer.Option(None, "--profile")):
    p = get_profile(profile)
    if reject_proposal(p, proposal_key):
        console.print(f"[yellow]Rejeitada:[/yellow] {proposal_key}")
    else:
        console.print(f"[red]Proposta não encontrada:[/red] {proposal_key}")
        raise typer.Exit(code=1)


@app.command("report")
def report_cmd(
    out: str = typer.Option(None, "--out", help="Caminho do arquivo markdown de saída."),
    window_days: int = typer.Option(90, "--window-days"),
    profile: str = typer.Option(None, "--profile"),
):
    """Gera o relatório markdown 'Improvement Proposals (retro)' a partir das
    propostas já analisadas (rode 'analyze' antes se ainda não rodou)."""
    p = get_profile(profile)
    summary = analyze(p, window_days=window_days)  # garante que está atualizado
    report = render_markdown_report(p, summary)
    if out:
        Path(out).write_text(report, encoding="utf-8")
        console.print(f"[green]Relatório salvo em[/green] {out}")
    else:
        console.print(report)
