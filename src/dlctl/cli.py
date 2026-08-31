"""dlctl.cli — ponto de entrada do CLI unificado.

Agrupa todos os comandos, espelhando (e implementando de fato, localmente)
a superfície descrita nas skills: auth, inventory, manifest, environments,
git, variable-libraries, copyjobs, execute, etl-silver, etl-gold, pipeline.
"""
from __future__ import annotations

import sys

import typer
from rich.console import Console

from dlctl import __version__
from dlctl.commands import (
    auth_cmds,
    copyjobs_cmds,
    definitions_cmds,
    diagnostics_cmds,
    environments_cmds,
    etl_bronze_silver_cmds,
    etl_silver_gold_cmds,
    execute_cmds,
    git_cmds,
    inventory_cmds,
    jobs_cmds,
    leases_cmds,
    lineage_cmds,
    manifest_cmds,
    notebooks_cmds,
    pipeline_cmds,
    retro_cmds,
    variable_libraries_cmds,
)

console = Console()

app = typer.Typer(
    name="dlctl",
    help="CLI unificado de migração Constellation: Bronze -> Silver -> Gold -> Fabric, "
         "com gates de segurança e dashboard de controle (Streamlit).",
    no_args_is_help=True,
)

app.add_typer(auth_cmds.app, name="auth")
app.add_typer(inventory_cmds.app, name="inventory")
app.add_typer(manifest_cmds.app, name="manifest")
app.add_typer(environments_cmds.app, name="environments")
app.add_typer(git_cmds.app, name="git")
app.add_typer(variable_libraries_cmds.app, name="variable-libraries")
app.add_typer(copyjobs_cmds.app, name="copyjobs")
app.add_typer(execute_cmds.app, name="execute")
app.add_typer(etl_bronze_silver_cmds.app, name="etl-silver")
app.add_typer(etl_silver_gold_cmds.app, name="etl-gold")
app.add_typer(pipeline_cmds.app, name="pipeline")
app.add_typer(leases_cmds.app, name="leases")
app.add_typer(diagnostics_cmds.app, name="pipelines")
app.add_typer(definitions_cmds.app, name="definitions")
app.add_typer(jobs_cmds.app, name="jobs")
app.add_typer(retro_cmds.app, name="retro")
app.add_typer(lineage_cmds.app, name="lineage")
app.add_typer(notebooks_cmds.app, name="notebooks")

_FLAT_COMMANDS = {"version", "dashboard"}


@app.callback()
def _track_invocation() -> None:
    """Registra cada invocação de comando (grupo+subcomando) em
    CommandInvocation — alimenta o detector 'skill-featured-unused' do motor
    de retro (dlctl retro analyze). Roda uma vez por chamada de CLI, antes do
    comando real; nunca deve quebrar a execução (por isso o try/except amplo)."""
    try:
        from dlctl.config import load_profile
        from dlctl.core.state import log_command_invocation

        tokens = [t for t in sys.argv[1:] if not t.startswith("-")]
        if not tokens:
            return
        command_sig = tokens[0] if tokens[0] in _FLAT_COMMANDS else " ".join(tokens[:2])
        profile = load_profile()
        log_command_invocation(profile, command_sig, argv=" ".join(sys.argv[1:]))
    except Exception:
        pass  # rastreio de telemetria nunca pode quebrar o comando real


@app.command("version")
def version():
    console.print(f"dlctl v{__version__}")


@app.command("dashboard")
def dashboard(port: int = typer.Option(8501, "--port")):
    """Abre o dashboard de controle Streamlit (equivalente a `gui runbook`, mas real)."""
    import subprocess
    from pathlib import Path

    app_path = Path(__file__).parent / "dashboard" / "app.py"
    console.print(f"Iniciando dashboard em http://localhost:{port} ...")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path), "--server.port", str(port)])


if __name__ == "__main__":
    app()
