"""dlctl supervisor ... — diagnóstico geral do projeto (Bronze/Silver/Gold/
Dashboards/Views), varrendo os artefatos reais em input/ e cruzando com
mappings/*.csv e config/project_targets.yaml. Nunca finge 100%: categorias
sem meta configurada ficam de fora do percentual geral."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import typer

from dlctl.commands.common import console, get_profile, print_table
from dlctl.core import state as state_db
from dlctl.core.project_scan import (
    export_supervisor_report,
    read_workspace_domain_prefixes,
    scan_project,
    write_project_targets,
    write_workspace_domain_prefixes,
)

app = typer.Typer(help="Supervisor: diagnóstico geral do andamento do projeto (Bronze/Silver/Gold/Dashboards/Views).")


@app.command("scan")
def scan(
    profile: str = typer.Option(None, "--profile"),
    lakehouse_dev_input: str = typer.Option("input/lakehouse-dev", "--lakehouse-dev-input"),
    lakehouse_hml_input: str = typer.Option(None, "--lakehouse-hml-input", help="Pasta com os notebooks sincronizados de HML (ex.: input/lakehouse-hml). Quando informada, 'existente' passa a considerar a união DEV+HML e mostra o % já promovido para HML."),
    workspaces_input: str = typer.Option("input/Workspaces", "--workspaces-input", help="Pasta/zip com os JSONs do Fabric Scanner API (opcional, alimenta a contagem de Dashboards/BI)."),
    only_referenced_workspaces: bool = typer.Option(False, "--only-referenced-workspaces", help="Considera só workspaces de input/Workspaces que têm alguma Dataset Table batendo com uma tabela conhecida em input/lakehouse-dev (Bronze/Silver/Gold) — descarta workspaces do tenant sem relação com este projeto."),
    filter_by_domain_prefix: bool = typer.Option(False, "--filter-by-domain-prefix", help="Considera só workspaces cujo nome começa com um dos prefixos configurados em `dlctl supervisor set-workspace-prefixes` (ex.: OPER-, FINAN-, MASTER-DATA, ORDER-TRACKING) — tem prioridade sobre --only-referenced-workspaces."),
    save: bool = typer.Option(False, "--save", help="Exporta o relatório (Excel + CSV) em manifests/dashboard/ e salva um snapshot no histórico."),
):
    """Roda o diagnóstico geral do projeto e imprime o percentual por
    categoria (Bronze/Silver/Gold/Dashboards/Views) e o percentual geral."""
    p = get_profile(profile)
    result = scan_project(
        p, lakehouse_dev_input=lakehouse_dev_input, workspaces_input=workspaces_input,
        only_referenced_workspaces=only_referenced_workspaces, filter_by_domain_prefix=filter_by_domain_prefix,
        lakehouse_hml_input=lakehouse_hml_input,
    )

    print_table(
        "Diagnóstico do projeto (Supervisor)",
        ["categoria", "existente", "esperado", "%", "fonte da meta"],
        [
            [c["categoria"], c["existente"], c["esperado"] if c["esperado"] else "(não configurado)",
             f"{c['percentual']}%" if c["percentual"] is not None else "-", c["fonte_meta"]]
            for c in result["categories"]
        ],
    )
    console.print(f"\n[bold]% geral do projeto:[/bold] {result['overall_percent']}%")
    if result["hml_enabled"]:
        et = result["env_totals"]
        pct_hml = et["pct_hml"] if et["pct_hml"] is not None else 0
        console.print(
            f"[cyan]DEV vs HML:[/cyan] {et['existente_dev']} notebook(s) em DEV, {et['existente_hml']} em HML "
            f"({pct_hml}% do existente já promovido para HML)"
        )
    if result["workspaces_referenciados"] is not None:
        modo = "--filter-by-domain-prefix" if result["workspace_filter_mode"] == "domain_prefix" else "--only-referenced-workspaces"
        console.print(
            f"[cyan]Workspaces considerados:[/cyan] {len(result['workspaces_referenciados'])} de "
            f"{result['workspaces_total']} em input/Workspaces ({modo} ativo)"
        )
    if result["excluded_from_overall"]:
        console.print(
            f"[yellow]Fora do % geral (sem meta configurada):[/yellow] {', '.join(result['excluded_from_overall'])} "
            "— use `dlctl supervisor set-targets` para configurar."
        )

    if save:
        batch_id = f"supervisor_{datetime.now():%Y%m%d_%H%M%S}"
        paths = export_supervisor_report(result, p.paths.manifests_root / "dashboard", batch_id)
        state_db.save_supervisor_snapshot(
            p, batch_id, result["overall_percent"], result["categories"],
            excel_path=paths["excel_path"], csv_path=paths["csv_path"],
        )
        console.print(f"\n[green]OK[/green]: visão salva (batch [bold]{batch_id}[/bold])")
        console.print(f"Excel: {paths['excel_path']}")
        console.print(f"CSV: {paths['csv_path']}")


@app.command("history")
def history(profile: str = typer.Option(None, "--profile")):
    """Lista as visões do Supervisor já salvas (`dlctl supervisor scan --save`)."""
    p = get_profile(profile)
    snapshots = state_db.list_supervisor_snapshots(p)
    if not snapshots:
        console.print("Nenhuma visão salva ainda. Use `dlctl supervisor scan --save`.")
        return
    print_table(
        "Histórico do Supervisor",
        ["batch_id", "criado em", "% geral", "excel"],
        [[s.batch_id, s.created_at, f"{s.overall_percent}%", s.excel_path] for s in snapshots],
    )


@app.command("set-targets")
def set_targets(
    intermediate: Optional[int] = typer.Option(None, "--intermediate", help="Meta de views/processos intermediários (notebooks de controle/qualidade) que deveriam existir no total."),
):
    """Configura a meta de Views/processos intermediários em
    config/project_targets.yaml (Bronze/Silver/Gold/Dashboards são sempre
    calculados a partir de input/ e não precisam de meta manual)."""
    write_project_targets(intermediate)
    console.print(f"[green]OK[/green]: meta salva em config/project_targets.yaml (intermediate={intermediate})")


@app.command("set-workspace-prefixes")
def set_workspace_prefixes(
    prefixes: Optional[str] = typer.Option(None, "--prefixes", help="Lista separada por vírgula dos prefixos de nome de workspace que definem os domínios deste projeto (ex.: 'OPER-,FINAN-,MASTER-DATA,ORDER-TRACKING'). Sem esta opção, só mostra os prefixos atuais."),
):
    """Configura (ou mostra) os prefixos de nome de workspace usados por
    `dlctl supervisor scan --filter-by-domain-prefix` para identificar quais
    workspaces de input/Workspaces pertencem aos domínios de negócio já
    migrados em input/lakehouse-dev."""
    if prefixes is None:
        current = read_workspace_domain_prefixes()
        console.print(f"Prefixos atuais: {', '.join(current)}")
        return
    prefix_list = [p.strip() for p in prefixes.split(",") if p.strip()]
    write_workspace_domain_prefixes(prefix_list)
    console.print(f"[green]OK[/green]: prefixos salvos em config/project_targets.yaml: {', '.join(prefix_list)}")
