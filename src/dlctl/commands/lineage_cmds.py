"""dlctl lineage ... — extração de linhagem Fabric para Excel."""
from __future__ import annotations

from pathlib import Path

import typer

from dlctl.commands.common import console, get_profile
from dlctl.core.lineage import generate_lineage_artifacts

app = typer.Typer(help="Extrator de linhagem Fabric (JSON/ZIP -> Excel + formatos).")


@app.command("generate")
def generate_cmd(
    input_path: str = typer.Option(..., "--input", help="Pasta com JSONs ou arquivo .zip exportado do Fabric."),
    output_dir: str = typer.Option(None, "--output-dir", help="Diretório de saída dos arquivos .xlsx."),
    profile: str = typer.Option(None, "--profile"),
):
    p = get_profile(profile)
    out_dir = Path(output_dir) if output_dir else (p.paths.state_root / "lineage")
    artifacts = generate_lineage_artifacts(Path(input_path), out_dir)
    console.print("[green]Arquivos gerados com sucesso:[/green]")
    console.print(f"- Original (7 abas): {artifacts.original_excel}")
    console.print(f"- Simplified Migration (4 abas): {artifacts.simplified_excel}")
    console.print(f"- PowerQuery Detailed (5 abas): {artifacts.detailed_excel}")

