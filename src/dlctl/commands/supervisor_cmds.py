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
from dlctl.core.dashboard_lineage import build_dashboard_lineage, export_dashboard_lineage_report
from dlctl.core.fabric_lineage import enrich_dashboard_lineage_with_fabric
from dlctl.core.global_scope import compute_global_scope, export_global_scope_report
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
    sharedpoint_input: str = typer.Option("input/sharedpoint", "--sharedpoint-input", help="Pasta com o Excel 'Projeto Lakehouse - Tabelas e Pipelines.xlsx' + x_Estrutura/ (fonte do escopo TOTAL do projeto: quantas tabelas precisam ser migradas ao todo, por camada). Sem essa pasta, cai para uma estimativa via mappings/linhagem."),
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
        lakehouse_hml_input=lakehouse_hml_input, sharedpoint_input=sharedpoint_input,
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
    if result["global_scope"].get("excel_found"):
        console.print(f"\n[bold]Escopo TOTAL do projeto[/bold] (input/sharedpoint, {result['global_scope']['total_tabelas']} tabela(s)):")
        for c in result["global_scope"]["camadas"]:
            extra = f" (+{c['descobertas_sql']} via SQL)" if c["descobertas_sql"] else ""
            console.print(f"  - {c['camada']}: {c['total']}{extra}")
        dashboard_target = result["global_scope"].get("dashboard_target")
        if dashboard_target:
            console.print(f"  - Dashboards/BI: {dashboard_target['total']} (fonte: \"{dashboard_target['fonte_texto']}\")")
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


@app.command("scope-export")
def scope_export(
    profile: str = typer.Option(None, "--profile"),
    sharedpoint_input: str = typer.Option("input/sharedpoint", "--sharedpoint-input", help="Pasta com o Excel 'Projeto Lakehouse - Tabelas e Pipelines.xlsx' + x_Estrutura/."),
    extended: bool = typer.Option(False, "--extended", help="Também vasculha .tab/.vw/.dsx (além de .sql/.prc) e as pastas '2. Camada Bronze'/'6. Camada Gold' — gera o artefato 'estendido' em vez do original."),
):
    """Calcula o escopo TOTAL do projeto (quantas tabelas precisam ser
    migradas ao todo, por camada — Bronze/Silver/Gold/outras), a partir do
    Excel do cliente em `input/sharedpoint` + tabelas descobertas via SQL
    (FROM/JOIN) que não estão mapeadas no Excel, e exporta o artefato
    (Excel com abas Resumo/Tabelas/Descobertas via SQL) para
    `manifests/dashboard/`. Com `--extended`, gera o artefato estendido
    (também .tab/.vw/.dsx) em vez do original."""
    p = get_profile(profile)
    scope = compute_global_scope(sharedpoint_input, extended=extended)
    if not scope["excel_found"]:
        console.print(f"[bold red]Falha:[/bold red] Excel não encontrado em {scope['excel_path']}")
        raise typer.Exit(code=1)

    print_table(
        f"Escopo {'ESTENDIDO' if extended else 'TOTAL'} do projeto (input/sharedpoint)",
        ["camada", "existente no excel", "descobertas via sql", "total"],
        [[c["camada"], c["existente_excel"], c["descobertas_sql"], c["total"]] for c in scope["camadas"]],
    )
    console.print(f"\n[bold]Total geral:[/bold] {scope['total_tabelas']} tabela(s)")
    if scope.get("dashboard_target"):
        dt = scope["dashboard_target"]
        console.print(f"[bold]Dashboards a migrar (total):[/bold] {dt['total']} (fonte: \"{dt['fonte_texto']}\")")
    if scope["descobertas_sql"]:
        console.print(f"[yellow]{len(scope['descobertas_sql'])} tabela(s) descoberta(s) via SQL[/yellow] (não estavam no Excel) — ver aba 'Descobertas via SQL' no artefato exportado.")

    batch_id = f"escopo_{datetime.now():%Y%m%d_%H%M%S}"
    paths = export_global_scope_report(scope, p.paths.manifests_root / "dashboard", batch_id)
    console.print(f"\n[green]OK[/green]: artefato exportado (batch [bold]{batch_id}[/bold])")
    console.print(f"Excel: {paths['excel_path']}")


@app.command("dashboard-lineage-export")
def dashboard_lineage_export(
    profile: str = typer.Option(None, "--profile"),
    workspaces_input: str = typer.Option("input/Workspaces", "--workspaces-input", help="Pasta ou .zip com os JSONs do Fabric Scanner API (Report -> Dataset -> Dataflow)."),
    scan_input: str = typer.Option("input/scan", "--scan-input", help="Pasta com os exports brutos de Dataflow (código M/Power Query embutido, usado para achar as tabelas físicas reais)."),
    sharedpoint_input: str = typer.Option("input/sharedpoint", "--sharedpoint-input", help="Pasta com o Excel 'Projeto Lakehouse - Tabelas e Pipelines.xlsx' + scripts .sql/.prc/.tab/.vw/.dsx, usada só de apoio para classificar camada/domínio."),
    fabric_snapshot: str = typer.Option(None, "--fabric-snapshot", help="Snapshot imutável de inventory-snapshot para cruzamento nominal somente leitura."),
    fabric_onelake_evidence_root: str = typer.Option(None, "--fabric-onelake-evidence-root", help="Raiz contendo as listagens OneLake coletadas junto ao snapshot."),
    fabric_workspace: str = typer.Option("LAKEHOUSE-DEV", "--fabric-workspace", help="Workspace esperado nas evidências OneLake."),
    fabric_evidence_window_minutes: int = typer.Option(10, "--fabric-evidence-window-minutes", min=1, help="Janela, após o snapshot, aceita para listagens OneLake."),
):
    """Descobre a linhagem de TODOS os dashboards/relatórios do tenant:
    Dashboard -> Dataset -> (Dataflow, quando existir) -> referência de
    tabela -> camada/domínio. Exporta um Excel
    com as abas 'Resumo' (total de dashboards, total de tabelas distintas,
    total por camada), 'Linhagem Dashboards' e 'Dataset e Dataflows'
    (agregado, no estilo da aba homônima usada como referência).

    As referências de Dataflow, M-query interna e entidades do modelo são
    combinadas, com confiança separada. Dataflows sem export correspondente
    em `--scan-input` permanecem sem referências M próprias."""
    if bool(fabric_snapshot) != bool(fabric_onelake_evidence_root):
        raise typer.BadParameter(
            "--fabric-snapshot e --fabric-onelake-evidence-root devem ser informados juntos."
        )

    result = build_dashboard_lineage(workspaces_input, scan_input, sharedpoint_input)
    if fabric_snapshot:
        result = enrich_dashboard_lineage_with_fabric(
            result,
            snapshot_path=fabric_snapshot,
            onelake_evidence_root=fabric_onelake_evidence_root,
            workspace_name=fabric_workspace,
            evidence_window_minutes=fabric_evidence_window_minutes,
        )
    summary = result["summary"]

    console.print(f"[bold]Total de dashboards/relatórios:[/bold] {summary['total_dashboards']}")
    console.print(
        "[bold]Referências distintas (inclui candidatas do modelo):[/bold] "
        f"{summary['total_tabelas_distintas']}"
    )
    console.print(
        "[bold]Referências estáticas via M/SQL/mapping:[/bold] "
        f"{summary.get('total_referencias_alta_confianca', 0)}"
    )
    console.print(
        "[yellow]Nomes somente do modelo semântico (baixa confiança):[/yellow] "
        f"{summary.get('total_candidatas_modelo_baixa_confianca', 0)}"
    )
    print_table(
        "Tabelas por camada",
        ["camada", "total"],
        [[camada, total] for camada, total in sorted(summary["tabelas_por_camada"].items())],
    )
    if result.get("fabric"):
        fabric = result["fabric"]
        print_table(
            f"Presença observada no Fabric ({fabric['workspace']})",
            ["métrica", "resultado"],
            [
                ["Tabelas físicas", f"{fabric['physical_found']}/{fabric['canonical_tables']}"],
                ["Local esperado", fabric["expected_location"]],
                ["Outro domínio/camada", fabric["cross_domain_or_layer"]],
                ["Não encontradas", fabric["not_found"]],
                ["Origens E2E materializadas", f"{fabric['e2e_origins_materialized']}/{fabric['e2e_origins_total']}"],
                ["Reports por nome", fabric["report_names_matched"]],
                ["Modelos semânticos por nome", fabric["semantic_model_names_matched"]],
                ["Tabelas com notebook candidato", fabric["tables_with_notebook_candidate"]],
            ],
        )

    p = get_profile(profile)
    batch_id = f"linhagem_{datetime.now():%Y%m%d_%H%M%S}"
    paths = export_dashboard_lineage_report(result, p.paths.manifests_root / "dashboard", batch_id)
    console.print(f"\n[green]OK[/green]: Excel exportado em {paths['excel_path']}")
    console.print(f"HTML: {paths['html_path']}")
