"""dlctl definitions ... — part-inspect: resolve a ambiguidade de hash de
definição (agregado vs. payload Base64 vs. conteúdo decodificado), Incid. 1 P2."""
from __future__ import annotations

import typer

from dlctl.commands.common import console
from dlctl.core.definitions_inspect import part_inspect

app = typer.Typer(help="Inspeção de definições Fabric (hash triad + resumo semântico), 100% offline.")


@app.command("part-inspect")
def part_inspect_cmd(definition_payload_file: str = typer.Option(..., "--file")):
    """Recebe um JSON local no formato de `getDefinition` e calcula os 3
    hashes nomeados (aggregate/encoded/decoded), sem ambiguidade."""
    result = part_inspect(definition_payload_file)
    console.print(f"aggregateDefinitionSha256: {result['aggregateDefinitionSha256']}")
    for part in result["parts"]:
        console.print(f"  - {part['path']} ({part['payloadType']})")
        console.print(f"      encodedPayloadSha256: {part['encodedPayloadSha256']}")
        console.print(f"      decodedContentSha256: {part['decodedContentSha256']}")
        if part["decodeError"]:
            console.print(f"      [red]decodeError:[/red] {part['decodeError']}")
    if result["semantic_summary"]:
        console.print(f"Resumo semântico (pipeline): {result['semantic_summary']}")
