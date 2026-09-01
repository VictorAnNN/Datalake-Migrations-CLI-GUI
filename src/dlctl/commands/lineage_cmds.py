"""dlctl lineage ... — feature de Linhagem do Lakehouse (integração do
Skill-LineageFabric): sincroniza notebooks via Azure CLI, gera os artefatos
(Linhagem Tabelas / Tabelas / trilha SharePoint) e permite consultar o mapa
isolado de uma tabela/fonte diretamente pelo terminal.
"""
from __future__ import annotations

from typing import Optional

import typer

from dlctl.commands.common import console, get_profile, print_table
from dlctl.connectors.fabric_notebook_sync import NotebookSyncError, sync_workspace_notebooks
from dlctl.core import lineage_graph
from dlctl.core import state as state_db
from dlctl.generators.lineage_generator import LineageGeneratorError, generate_lineage_artifacts

app = typer.Typer(help="Feature de Linhagem do Lakehouse: sincronização, geração de artefatos e mapa isolado.")


@app.command("sync-notebooks")
def sync_notebooks(
    profile: str = typer.Option(None, "--profile"),
    output_dir: str = typer.Option(None, "--output-dir", help="Padrão: input/lakehouse-dev (ou FABRIC_SYNC_OUTPUT_DIR)."),
    max_workers: int = typer.Option(None, "--max-workers", min=1, max=8,
                                     help="Downloads simultâneos (1-8). Padrão: FABRIC_SYNC_MAX_WORKERS do .env (ou 4)."),
    workspace_id: str = typer.Option(None, "--workspace-id", help="Sobrepõe o workspace padrão do profile (FABRIC_WORKSPACE_ID). Ex.: para sincronizar outro ambiente sem trocar de profile."),
):
    """Baixa os notebooks do workspace configurado via Azure CLI (`az login`),
    forma padrão de conexão desta feature com o Fabric."""
    p = get_profile(profile)

    def _progress(index: int, total: int, name: str) -> None:
        console.print(f"[{index}/{total}] {name}")

    try:
        result = sync_workspace_notebooks(
            p, output_dir=output_dir, on_progress=_progress, max_workers=max_workers, workspace_id=workspace_id,
        )
    except NotebookSyncError as exc:
        console.print(f"[bold red]Falha ao sincronizar notebooks:[/bold red] {exc}")
        raise typer.Exit(code=1)

    console.print(
        f"[green]OK[/green]: {result['downloaded']}/{result['total']} notebook(s) em {result['output_dir']} "
        f"(paralelismo: {result['max_workers']} worker(s))"
    )
    if result["failures"]:
        console.print(f"[yellow]{len(result['failures'])} falha(s):[/yellow]")
        for failure in result["failures"]:
            console.print(f"  - {failure}")


@app.command("sync-notebooks-hml")
def sync_notebooks_hml(
    profile: str = typer.Option(None, "--profile"),
    output_dir: str = typer.Option("input/lakehouse-hml", "--output-dir", help="Padrão: input/lakehouse-hml."),
    max_workers: int = typer.Option(None, "--max-workers", min=1, max=8,
                                     help="Downloads simultâneos (1-8). Padrão: FABRIC_SYNC_MAX_WORKERS do .env (ou 4)."),
):
    """Baixa os notebooks do workspace de Homologação (`FABRIC_WORKSPACE_ID_HML`)
    via Azure CLI (`az login`) para `input/lakehouse-hml` — mesma lógica de
    `sync-notebooks`, mas para o ambiente HML, usada pelo Supervisor para medir
    o quanto do projeto já foi promovido de DEV para HML."""
    p = get_profile(profile)
    if not p.microsoft.hml_workspace_id:
        console.print(
            "[bold red]Falha:[/bold red] FABRIC_WORKSPACE_ID_HML não configurado no .env. "
            "Copie o GUID da URL do workspace HML no portal Fabric."
        )
        raise typer.Exit(code=1)

    def _progress(index: int, total: int, name: str) -> None:
        console.print(f"[{index}/{total}] {name}")

    try:
        result = sync_workspace_notebooks(
            p, output_dir=output_dir, on_progress=_progress, max_workers=max_workers,
            workspace_id=p.microsoft.hml_workspace_id,
        )
    except NotebookSyncError as exc:
        console.print(f"[bold red]Falha ao sincronizar notebooks:[/bold red] {exc}")
        raise typer.Exit(code=1)

    console.print(
        f"[green]OK[/green]: {result['downloaded']}/{result['total']} notebook(s) em {result['output_dir']} "
        f"(paralelismo: {result['max_workers']} worker(s))"
    )
    if result["failures"]:
        console.print(f"[yellow]{len(result['failures'])} falha(s):[/yellow]")
        for failure in result["failures"]:
            console.print(f"  - {failure}")



@app.command("generate")
def generate(
    profile: str = typer.Option(None, "--profile"),
    lakehouse_dev_input: str = typer.Option("input/lakehouse-dev", "--lakehouse-dev-input"),
    workspaces_input: str = typer.Option(None, "--workspaces-input", help="Pasta ou .zip com os JSONs do Fabric Scanner API (opcional, alimenta a trilha SharePoint e o inventário pesquisável de workspaces)."),
    no_excel: bool = typer.Option(False, "--no-excel", help="Não exportar o Excel de conferência (só persiste no state.db)."),
):
    """Gera os artefatos de Linhagem (Linhagem Tabelas / Tabelas / trilha
    SharePoint / inventário de workspaces) a partir dos notebooks e
    (opcionalmente) dos JSONs do Fabric Scanner, e persiste tudo para
    consumo do dashboard."""
    p = get_profile(profile)
    try:
        result = generate_lineage_artifacts(
            p, lakehouse_dev_input=lakehouse_dev_input, workspaces_input=workspaces_input,
            export_excel=not no_excel,
        )
    except LineageGeneratorError as exc:
        console.print(f"[bold red]Falha ao gerar artefatos de linhagem:[/bold red] {exc}")
        raise typer.Exit(code=1)

    console.print(f"[green]OK[/green]: batch [bold]{result['batch_id']}[/bold]")
    if result.get("workspaces_input_not_found"):
        console.print(
            f"[bold yellow]AVISO[/bold yellow]: --workspaces-input '{workspaces_input}' não foi encontrado "
            "(nem relativo ao diretório atual, nem à raiz do projeto) — trilha SharePoint, inventário de "
            "workspaces e os artefatos extras (fabric_lineage/simplified migration/powerquery detailed) "
            "foram pulados."
        )
    print_table(
        "Resumo da geração",
        ["artefato", "linhas"],
        [
            ["Linhagem Tabelas (com transitivas)", result["dependency_rows"]],
            ["Tabelas (catálogo)", result["catalog_rows"]],
            ["Trilha SharePoint", result["sharepoint_rows"]],
            ["Inventário de Workspaces PBI/Fabric", result["workspace_item_rows"]],
        ],
    )
    if result["excel_path"]:
        console.print(f"Excel de conferência (Tabelas + Linhagem Tabelas): {result['excel_path']}")
    if result.get("fabric_lineage_full_path"):
        console.print(f"Extrato bruto completo (7 abas): {result['fabric_lineage_full_path']}")
    if result.get("simplified_migration_path"):
        console.print(f"Simplified Migration (4 abas): {result['simplified_migration_path']}")
    if result.get("powerquery_detailed_path"):
        console.print(f"PowerQuery Detailed (5 abas): {result['powerquery_detailed_path']}")


def _resolve_batch_id(p, batch_id: Optional[str]) -> str:
    if batch_id:
        return batch_id
    latest = state_db.latest_lineage_batch(p)
    if not latest:
        console.print("[yellow]Nenhuma geração de linhagem encontrada ainda.[/yellow] Rode `dlctl lineage generate` primeiro.")
        raise typer.Exit(code=1)
    return latest.batch_id


@app.command("show")
def show(
    artifact: str = typer.Argument(..., help="dependencies | catalog | sharepoint | workspaces"),
    batch_id: str = typer.Option(None, "--batch-id", help="Padrão: última geração com sucesso."),
    profile: str = typer.Option(None, "--profile"),
    domain: str = typer.Option(None, "--domain"),
    search: str = typer.Option(None, "--search", help="Busca livre (usada por 'workspaces': nome de workspace, dataset, dataflow ou report)."),
    item_type: str = typer.Option(None, "--type", help="Filtra 'workspaces' por tipo: Workspace | Dataset | Dataset Table | Dataflow | Report."),
    limit: int = typer.Option(50, "--limit"),
):
    """Lista as linhas persistidas de um dos artefatos gerados por `dlctl lineage generate`."""
    p = get_profile(profile)
    resolved_batch = _resolve_batch_id(p, batch_id)

    if artifact == "dependencies":
        rows = state_db.get_lineage_dependencies(p, resolved_batch)
        if domain:
            rows = [r for r in rows if r.domain.casefold() == domain.casefold()]
        print_table(
            f"Linhagem Tabelas (batch={resolved_batch})",
            ["origem", "tabela_origem", "destino", "tabela_destino", "transitiva"],
            [[r.source_layer, r.source_table, r.target_layer, r.target_table, r.is_transitive] for r in rows[:limit]],
        )
    elif artifact == "catalog":
        rows = state_db.get_lineage_catalog(p, resolved_batch)
        if domain:
            rows = [r for r in rows if r.domain.casefold() == domain.casefold()]
        print_table(
            f"Tabelas (batch={resolved_batch})",
            ["domínio", "fonte", "camada_destino", "tabela_destino", "status_dev"],
            [[r.domain, r.source, r.target_layer, r.target_table, r.status_dev_build] for r in rows[:limit]],
        )
    elif artifact == "sharepoint":
        rows = state_db.get_lineage_sharepoint(p, resolved_batch)
        print_table(
            f"Trilha SharePoint (batch={resolved_batch})",
            ["workspace", "dashboard", "dataset", "tabela", "referência", "existe?"],
            [[r.workspace, r.report_name, r.dataset_name, r.dataset_table, r.sharepoint_reference, r.exists_check] for r in rows[:limit]],
        )
    elif artifact == "workspaces":
        rows = state_db.get_lineage_workspace_items(p, resolved_batch)
        if item_type:
            rows = [r for r in rows if r.item_type.casefold() == item_type.casefold()]
        if search:
            term = search.casefold()
            rows = [
                r for r in rows
                if term in r.workspace.casefold() or term in r.item_name.casefold() or term in r.parent_name.casefold()
            ]
        print_table(
            f"Inventário de Workspaces PBI/Fabric (batch={resolved_batch})",
            ["workspace", "tipo", "nome", "pai", "detalhe"],
            [[r.workspace, r.item_type, r.item_name, r.parent_name, r.detail] for r in rows[:limit]],
        )
    else:
        console.print("[red]artifact inválido.[/red] Use: dependencies | catalog | sharepoint | workspaces")
        raise typer.Exit(code=2)


@app.command("isolate")
def isolate(
    query: str = typer.Argument(..., help="Termo de busca (nome de tabela/schema/lakehouse)."),
    direction: str = typer.Option("Linhagem completa", "--direction", help="Downstream | Upstream | 'Linhagem completa'"),
    batch_id: str = typer.Option(None, "--batch-id"),
    profile: str = typer.Option(None, "--profile"),
):
    """Mostra o Mapa Isolado (upstream/downstream) de uma tabela/fonte em
    texto — equivalente ao relatório `docs/lineage-report.md` do projeto
    original, sem precisar abrir o dashboard."""
    p = get_profile(profile)
    resolved_batch = _resolve_batch_id(p, batch_id)
    dependencies = state_db.get_lineage_dependencies(p, resolved_batch)
    graph = lineage_graph.build_dependency_graph(dependencies)

    subgraph, matches = lineage_graph.isolate_by_term(graph, query, direction)
    if not matches:
        console.print(f"[yellow]Nenhum nó encontrado para '{query}'.[/yellow]")
        raise typer.Exit(code=1)

    console.print(f"Nó(s) selecionado(s): {', '.join(matches)}")
    summary = lineage_graph.summarize_by_layer(subgraph)
    for layer in lineage_graph.DATA_LAYER_ORDER:
        tables = summary.get(layer, [])
        label = lineage_graph.DATA_LAYER_LABELS[layer]
        console.print(f"\n[bold]{label}[/bold] ({len(tables)}):")
        for table in tables:
            console.print(f"  - {table}")
