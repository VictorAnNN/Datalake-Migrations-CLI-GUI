"""dlctl.core.definitions_inspect

Resolve a ambiguidade de hash de definição levantada no Incidente 1 (P2):
"Os hashes de definição são ambíguos: agregado, payload Base64 e conteúdo
decodificado."

Dado um payload de definição Fabric local (o mesmo formato retornado por
`GET .../items/{id}/getDefinition`, com `definition.parts[]` contendo
`path`, `payload` (Base64) e `payloadType`), calcula os 3 hashes de forma
inequívoca e nomeada, além de um resumo semântico simples (atividades,
parâmetros, schedules) quando aplicável a um DataPipeline.

100% offline — opera sobre um arquivo JSON local (ex.: salvo por
`definitions get --save-payload` no passado, ou o export de um manifest).
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Optional


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def part_inspect(definition_payload_path: str | Path) -> dict:
    """Retorna, por parte da definição:
    - `aggregateDefinitionSha256`: hash do payload de definição inteiro (todas as partes, como está).
    - `encodedPayloadSha256`: hash do payload Base64 bruto (string, antes de decodificar) daquela parte.
    - `decodedContentSha256`: hash do conteúdo já decodificado (bytes reais) daquela parte.
    """
    raw_text = Path(definition_payload_path).read_text(encoding="utf-8-sig")
    data = json.loads(raw_text)

    aggregate_hash = _sha256(raw_text.encode("utf-8"))

    definition = data.get("definition", data)
    parts = definition.get("parts", [])
    part_hashes = []
    activities_summary: Optional[dict] = None

    for part in parts:
        path = part.get("path", "?")
        payload_b64 = part.get("payload", "")
        payload_type = part.get("payloadType", "InlineBase64")
        encoded_hash = _sha256(payload_b64.encode("utf-8"))
        decoded_bytes = b""
        decode_error = None
        try:
            if payload_type == "InlineBase64":
                decoded_bytes = base64.b64decode(payload_b64)
            else:
                decoded_bytes = payload_b64.encode("utf-8")
        except Exception as exc:  # pragma: no cover - payload corrompido
            decode_error = str(exc)
        decoded_hash = _sha256(decoded_bytes) if not decode_error else None

        part_hashes.append({
            "path": path,
            "payloadType": payload_type,
            "encodedPayloadSha256": encoded_hash,
            "decodedContentSha256": decoded_hash,
            "decodeError": decode_error,
        })

        if path.endswith("pipeline-content.json") and not decode_error:
            try:
                content = json.loads(decoded_bytes.decode("utf-8"))
                props = content.get("properties", content)
                activities = props.get("activities", [])
                activities_summary = {
                    "activity_count": len(activities),
                    "activity_names": [a.get("name") for a in activities],
                    "has_triggers": bool(props.get("triggers")),
                    "parameters": list(props.get("parameters", {}).keys()) if isinstance(props.get("parameters"), dict) else [],
                }
            except Exception:  # pragma: no cover
                pass

    return {
        "aggregateDefinitionSha256": aggregate_hash,
        "parts": part_hashes,
        "semantic_summary": activities_summary,
    }
