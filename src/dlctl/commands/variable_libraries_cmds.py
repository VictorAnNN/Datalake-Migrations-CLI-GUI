"""dlctl variable-libraries ... — leitura e escrita gated (variable_libraries_workflow.md)."""
from __future__ import annotations

import typer

from dlctl.commands.common import console, get_gate, get_profile, handle_security_error
from dlctl.connectors.fabric_api import FabricApiError, build_client_from_profile
from dlctl.core.secrets import assert_no_secret_like, redact

app = typer.Typer(help="Variable Libraries: list/get/definition (leitura) e create/update-definition (gated).")


@app.command("list")
def list_cmd(workspace: str = typer.Option(..., "--workspace"), profile: str = typer.Option(None, "--profile")):
    p = get_profile(profile)
    client = build_client_from_profile(p)
    client.workspace_id = client.resolve_workspace_id(workspace)
    for lib in client.list_variable_libraries():
        console.print(f"- {lib.get('displayName')} ({lib.get('id')})")


@app.command("definition")
def definition_cmd(
    workspace: str = typer.Option(..., "--workspace"),
    library: str = typer.Option(..., "--library"),
    profile: str = typer.Option(None, "--profile"),
):
    p = get_profile(profile)
    client = build_client_from_profile(p)
    client.workspace_id = client.resolve_workspace_id(workspace)
    lib_item = client.find_item_by_name(library, "VariableLibrary")
    if not lib_item:
        console.print(f"[yellow]Variable Library '{library}' não encontrada[/yellow]")
        raise typer.Exit(code=1)
    definition = client.get_variable_library_definition(lib_item["id"])
    console.print(redact(definition))  # nunca imprime valores sanitizados como texto puro


@app.command("create")
@handle_security_error
def create_cmd(
    workspace: str = typer.Option(..., "--workspace"),
    name: str = typer.Option(..., "--name"),
    description: str = typer.Option("", "--description"),
    confirm_create: bool = typer.Option(False, "--confirm-create"),
    profile: str = typer.Option(None, "--profile"),
):
    p = get_profile(profile)
    assert_no_secret_like(name)
    gate = get_gate(p)
    gate.authorize_write(confirm_write=confirm_create)
    client = build_client_from_profile(p)
    client.workspace_id = client.resolve_workspace_id(workspace)
    result = client.create_item(name, "VariableLibrary", folder_id=None, description=description)
    console.print(f"[green]Variable Library criada[/green]: {result.get('id')}")
