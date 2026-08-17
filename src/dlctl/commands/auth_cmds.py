"""dlctl auth ... — espelha `accountctl profile show` / `fabric-fullctl auth doctor`."""
from __future__ import annotations

import typer

from dlctl.commands.common import console, get_profile, handle_security_error, print_table
from dlctl.connectors.fabric_api import FabricApiError, build_client_from_profile

app = typer.Typer(help="Autenticação e diagnóstico de perfil (equivalente a accountctl/auth doctor).")


@app.command("profile-show")
def profile_show(profile: str = typer.Option(None, "--profile")):
    """Mostra o profile ativo (tenant, workspace, flags de escrita) sem segredos."""
    p = get_profile(profile)
    print_table(
        f"Profile: {p.name}",
        ["campo", "valor"],
        [
            ["environment", p.environment],
            ["allow_write", p.microsoft.allow_write],
            ["allow_production", p.microsoft.allow_production],
            ["auth_mode", p.microsoft.auth_mode],
            ["workspace_name", p.microsoft.default_workspace_name],
            ["workspace_id", p.microsoft.default_workspace_id or "(não configurado)"],
            ["tenant_id_configurado", bool(p.microsoft.tenant_id)],
            ["client_id_configurado", bool(p.microsoft.client_id)],
        ],
    )


@app.command("doctor")
@handle_security_error
def doctor(profile: str = typer.Option(None, "--profile")):
    """Verifica credenciais Fabric configuradas e tenta uma chamada de leitura simples."""
    p = get_profile(profile)
    if not p.microsoft.tenant_id or not p.microsoft.client_id:
        console.print("[yellow]manual_required[/yellow]: FABRIC_TENANT_ID/FABRIC_CLIENT_ID ausentes no .env.")
        raise typer.Exit(code=1)
    try:
        client = build_client_from_profile(p)
        workspaces = client.list_workspaces()
        console.print(f"[green]OK[/green]: autenticado, {len(workspaces)} workspace(s) visível(eis).")
    except FabricApiError as exc:
        console.print(f"[red]Falha de autenticação/API:[/red] {exc}")
        raise typer.Exit(code=1)


@app.command("oracle-doctor")
def oracle_doctor(profile: str = typer.Option(None, "--profile")):
    """Testa a conexão com o banco Oracle configurado no profile."""
    from dlctl.connectors.oracle_connector import OracleConnectorError, OracleDbConnector

    p = get_profile(profile)
    try:
        conn = OracleDbConnector(p)
        result = conn.test_connection()
        console.print(f"[green]OK[/green]: {result}")
    except OracleConnectorError as exc:
        console.print(f"[yellow]manual_required[/yellow]: {exc}")
        raise typer.Exit(code=1)
