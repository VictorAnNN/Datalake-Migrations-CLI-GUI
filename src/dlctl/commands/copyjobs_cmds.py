"""dlctl copyjobs ... — Copy Job item type (copyjob_surface.md) + auditoria
semântica de mappings (Incid. 1, P0) + bulk (Plan 39)."""
from __future__ import annotations

import json
from pathlib import Path

import typer

from dlctl.commands.common import console, get_gate, get_profile, handle_security_error, print_table
from dlctl.connectors.fabric_api import build_client_from_profile
from dlctl.core.copyjob_audit import mappings_inspect, oracle_number_audit
from dlctl.core import copyjob_bulk as bulk_engine

app = typer.Typer(help="Copy Jobs: list/resolve (leitura), run (gated), auditoria de mappings e bulk (Plan 39).")
bulk_app = typer.Typer(help="Bulk Copy Jobs: plan/dry-run/diff/apply/reconcile contra um diretório local de definições.")
app.add_typer(bulk_app, name="bulk")


@app.command("list")
def list_cmd(workspace: str = typer.Option(..., "--workspace"), profile: str = typer.Option(None, "--profile")):
    p = get_profile(profile)
    client = build_client_from_profile(p)
    client.workspace_id = client.resolve_workspace_id(workspace)
    for job in client.list_items(item_type="CopyJob"):
        console.print(f"- {job.get('displayName')} ({job.get('id')})")


@app.command("run")
@handle_security_error
def run_cmd(
    workspace: str = typer.Option(..., "--workspace"),
    name: str = typer.Option(..., "--name"),
    confirm_execute: bool = typer.Option(False, "--confirm-execute"),
    profile: str = typer.Option(None, "--profile"),
):
    p = get_profile(profile)
    gate = get_gate(p)
    gate.authorize_execute(confirm_execute=confirm_execute)
    client = build_client_from_profile(p)
    client.workspace_id = client.resolve_workspace_id(workspace)
    item = client.find_item_by_name(name, "CopyJob")
    if not item:
        console.print(f"[yellow]Copy Job '{name}' não encontrado[/yellow]")
        raise typer.Exit(code=1)
    result = client.run_item_job(item["id"], job_type="Execute")
    console.print(f"[green]Copy Job iniciado[/green]: {result}")


@app.command("mappings-inspect")
def mappings_inspect_cmd(definition_file: str = typer.Option(..., "--definition")):
    """Lista tabelas/colunas mapeadas em um copyjob-content.json local (offline)."""
    result = mappings_inspect(definition_file)
    console.print(f"Tabelas mapeadas: {result['table_count']}")
    for t in result["tables"]:
        console.print(f"  - {t['source_table']}: {t['column_count']} coluna(s)")


@app.command("oracle-number-audit")
def oracle_number_audit_cmd(
    definition_file: str = typer.Option(..., "--definition"),
    schema_export: str = typer.Option(None, "--schema-export",
                                       help="JSON [{table,column,data_type}] equivalente a um export de ALL_TAB_COLUMNS."),
):
    """Audita colunas Oracle NUMBER sem precisão/escala e mappings ausentes
    (Incid. 1, P0 — as 970 colunas identificadas por script ad hoc)."""
    outcome = oracle_number_audit(definition_file, schema_export)
    console.print(f"Colunas verificadas: {outcome.total_columns_checked}")
    if outcome.unmapped_tables:
        console.print(f"[red]Tabelas sem mapping:[/red] {outcome.unmapped_tables}")
    if outcome.unmapped_columns:
        console.print(f"[red]Colunas sem mapping ({len(outcome.unmapped_columns)}):[/red]")
        for c in outcome.unmapped_columns[:20]:
            console.print(f"  - {c['table']}.{c['column']} ({c['data_type']})")
        if len(outcome.unmapped_columns) > 20:
            console.print(f"  ... e mais {len(outcome.unmapped_columns) - 20}")
    for issue in outcome.issues:
        color = "red" if issue.severity == "error" else "yellow"
        console.print(f"  [{color}]{issue.severity}[/{color}]: {issue.table}.{issue.column} ({issue.source_type}) — {issue.reason}")
    if outcome.ok:
        console.print("[green]Auditoria OK[/green]: nenhum problema bloqueante encontrado.")
    else:
        console.print("[red]Auditoria com problemas bloqueantes.[/red]")
        raise typer.Exit(code=1)


def _try_client(profile):
    try:
        return build_client_from_profile(profile)
    except Exception:
        return None


@bulk_app.command("plan")
def bulk_plan_cmd(
    definitions_dir: str = typer.Option(..., "--definitions-dir"),
    out_plan: str = typer.Option(None, "--out-plan"),
    profile: str = typer.Option(None, "--profile"),
):
    """Somente leitura: compara o diretório local de definições (*.copyjob.yaml)
    contra o live (se houver client) por displayName + hash canônico."""
    p = get_profile(profile)
    client = _try_client(p)
    result = bulk_engine.bulk_plan(p, definitions_dir, fabric_client=client)
    if not result.live_compared:
        console.print("[yellow]Sem Fabric client configurado — todas as entradas aparecem como 'create' (sem comparação live).[/yellow]")
    print_table("Bulk Plan", ["display_name", "action", "folder_path"],
                [[e.display_name, e.action, e.folder_path or ""] for e in result.entries])
    if result.duplicates:
        console.print(f"[yellow]{len(result.duplicates)} grupo(s) de duplicata(s) detectado(s):[/yellow]")
        for d in result.duplicates:
            console.print(f"  - {d}")
    out_path = Path(out_plan) if out_plan else Path(definitions_dir) / "bulk.plan.json"
    out_path.write_text(json.dumps(result.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"Plano salvo em: {out_path}")


@bulk_app.command("diff")
def bulk_diff_cmd(definitions_dir: str = typer.Option(..., "--definitions-dir"), profile: str = typer.Option(None, "--profile")):
    """Alias de leitura para 'plan', focado só em mostrar as diferenças (sem salvar plano)."""
    p = get_profile(profile)
    client = _try_client(p)
    result = bulk_engine.bulk_plan(p, definitions_dir, fabric_client=client)
    changed = [e for e in result.entries if e.action != "noop"]
    if not changed:
        console.print("[green]Nenhuma diferença detectada.[/green]" if result.live_compared else
                       "[yellow]Sem client — não é possível provar 'sem diferenças'; todas aparecem como create.[/yellow]")
    print_table("Diferenças", ["display_name", "action", "local_hash", "live_hash"],
                [[e.display_name, e.action, e.local_hash[:12], (e.live_hash or "")[:12]] for e in changed])


@bulk_app.command("dry-run")
def bulk_dry_run_cmd(plan_path: str = typer.Option(..., "--plan")):
    """100% offline: reprova hash/definição local desde o plano."""
    plan_result = bulk_engine.BulkPlanResult(**json.loads(Path(plan_path).read_text(encoding="utf-8-sig")))
    issues = bulk_engine.bulk_dry_run(plan_result)
    errors = [i for i in issues if i.level == "error"]
    for i in issues:
        color = "red" if i.level == "error" else "yellow"
        console.print(f"  [{color}]{i.level}[/{color}]: {i.display_name} — {i.message}")
    if errors:
        raise typer.Exit(code=1)
    console.print("[green]dry-run OK[/green]: nenhum problema bloqueante.")


@bulk_app.command("apply")
@handle_security_error
def bulk_apply_cmd(
    plan_path: str = typer.Option(..., "--plan"),
    confirm_write: bool = typer.Option(False, "--confirm-write"),
    confirm_production: bool = typer.Option(False, "--confirm-production"),
    run_id: str = typer.Option("", "--run-id"),
    profile: str = typer.Option(None, "--profile"),
):
    """Aplica o plano (cria/atualiza definições de Copy Job). NUNCA roda os
    jobs — isso continua sendo `copyjobs run --confirm-execute`, por item."""
    p = get_profile(profile)
    plan_result = bulk_engine.BulkPlanResult(**json.loads(Path(plan_path).read_text(encoding="utf-8-sig")))
    gate = get_gate(p, run_id=run_id)
    client = _try_client(p)
    result = bulk_engine.bulk_apply(
        p, plan_result, gate, confirm_write=confirm_write, confirm_production=confirm_production,
        fabric_client=client, run_id=run_id,
    )
    for name, r in result["results"].items():
        color = {"applied": "green", "noop": "cyan", "manual_required": "yellow", "failed": "red"}.get(r["status"], "white")
        console.print(f"  [{color}]{r['status']}[/{color}]: {name} — {r}")


@bulk_app.command("reconcile")
def bulk_reconcile_cmd(definitions_dir: str = typer.Option(..., "--definitions-dir"), profile: str = typer.Option(None, "--profile")):
    """Comparação somente-leitura: missing_in_fabric / orphaned_in_fabric
    (nunca deleta nada automaticamente) + duplicatas."""
    p = get_profile(profile)
    client = _try_client(p)
    result = bulk_engine.bulk_reconcile(p, definitions_dir, fabric_client=client)
    console.print(result)


