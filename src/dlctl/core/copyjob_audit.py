"""dlctl.core.copyjob_audit

Auditoria semântica de mappings de Copy Job (Incid. 1, P0):
"Não existe auditor semântico de mappings do Copy Job. A identificação das
970 colunas foi feita por script específico do projeto."

Implementa:
- `mappings_inspect`: lista as colunas mapeadas em um `copyjob-content.json`
  (definição oficial: https://learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/copyjob-definition)
  e falha em coluna/tabela presente na origem mas ausente do mapping.
- `oracle_number_audit`: destaca colunas Oracle `NUMBER` sem precisão/escala
  — que o conector Fabric materializa como `Decimal(256,130)` por padrão
  (https://learn.microsoft.com/en-us/fabric/data-factory/connector-oracle-database-copy-activity)
  — e verifica se existe um cast explícito no mapping para evitar o tipo
  "genérico" gigante.

100% offline: opera sobre arquivos JSON locais (definição do Copy Job e,
opcionalmente, um export de `ALL_TAB_COLUMNS`/schema Oracle). Nenhuma
chamada de rede é feita.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

NUMBER_WITH_PRECISION = re.compile(r"^\s*NUMBER\s*\(\s*\d+\s*(,\s*-?\d+\s*)?\)\s*$", re.IGNORECASE)
NUMBER_BARE = re.compile(r"^\s*NUMBER\s*$", re.IGNORECASE)


@dataclass
class ColumnAuditIssue:
    table: str
    column: str
    source_type: str
    reason: str
    severity: str = "error"  # error | warning


@dataclass
class AuditOutcome:
    ok: bool
    total_columns_checked: int
    issues: list[ColumnAuditIssue] = field(default_factory=list)
    unmapped_tables: list[str] = field(default_factory=list)
    unmapped_columns: list[dict] = field(default_factory=list)


def _iter_copyjob_table_mappings(copyjob_definition: dict):
    """Percorre `source.typeProperties`/`typeProperties.tableMappings` (ou
    variações) de um copyjob-content.json de forma tolerante a schema, já
    que o formato oficial não é fixo em todos os connectors."""
    props = copyjob_definition.get("properties", copyjob_definition)
    mappings = (
        props.get("tableMappings")
        or props.get("typeProperties", {}).get("tableMappings")
        or props.get("source", {}).get("tableMappings")
        or []
    )
    for mapping in mappings:
        yield mapping


def mappings_inspect(copyjob_definition_path: str | Path) -> dict:
    """Lista as tabelas/colunas mapeadas em um copyjob-content.json local."""
    data = json.loads(Path(copyjob_definition_path).read_text(encoding="utf-8-sig"))
    tables = []
    for mapping in _iter_copyjob_table_mappings(data):
        source_table = mapping.get("sourceTableName") or mapping.get("source", {}).get("table") or "?"
        columns = mapping.get("columnMappings") or mapping.get("columns") or []
        tables.append({
            "source_table": source_table,
            "column_count": len(columns),
            "columns": columns,
        })
    return {"table_count": len(tables), "tables": tables}


def oracle_number_audit(
    copyjob_definition_path: str | Path,
    oracle_schema_export_path: Optional[str | Path] = None,
) -> AuditOutcome:
    """Audita colunas Oracle NUMBER (sem precisão/escala) presentes no schema
    exportado mas sem cast explícito no mapping do Copy Job.

    `oracle_schema_export_path` é um JSON no formato:
    `[{"table": "AP_INVOICES_ALL", "column": "INVOICE_ID", "data_type": "NUMBER"}, ...]`
    (equivalente a um export de `ALL_TAB_COLUMNS`, já que não há endpoint
    Fabric comprovado para consultar isso ao vivo via conexão — ver
    Incidente 1, seção "Limitações do Fabric, não da CLI").

    Sem esse export, a auditoria roda apenas sobre o que já está no mapping
    (menos precisa, mas ainda detecta colunas mapeadas como NUMBER puro).
    """
    inspect_result = mappings_inspect(copyjob_definition_path)
    issues: list[ColumnAuditIssue] = []
    unmapped_tables: list[str] = []
    unmapped_columns: list[dict] = []
    total_checked = 0

    mapped_by_table: dict[str, dict[str, dict]] = {}
    for t in inspect_result["tables"]:
        col_index = {}
        for c in t["columns"]:
            col_name = c.get("sourceColumnName") or c.get("source") or c.get("name")
            if col_name:
                col_index[col_name.upper()] = c
        mapped_by_table[t["source_table"].upper()] = col_index

    if oracle_schema_export_path:
        schema = json.loads(Path(oracle_schema_export_path).read_text(encoding="utf-8-sig"))
        for row in schema:
            table = str(row.get("table", "")).upper()
            column = str(row.get("column", "")).upper()
            data_type = str(row.get("data_type", ""))
            total_checked += 1
            if table not in mapped_by_table:
                if table not in unmapped_tables:
                    unmapped_tables.append(table)
                continue
            mapped_col = mapped_by_table[table].get(column)
            if mapped_col is None:
                unmapped_columns.append({"table": table, "column": column, "data_type": data_type})
                continue
            if NUMBER_BARE.match(data_type):
                # 'cast'/'targetType' são indicações explícitas de mitigação; a mera
                # presença de 'sourceType' repetindo "NUMBER" NÃO conta como cast —
                # é justamente o sintoma do problema (bug corrigido: antes contava).
                has_cast = bool(mapped_col.get("cast") or mapped_col.get("targetType"))
                if not has_cast:
                    issues.append(ColumnAuditIssue(
                        table=table, column=column, source_type=data_type,
                        reason="NUMBER sem precisão/escala e sem cast explícito no mapping "
                               "-> materializa como Decimal(256,130) por padrão no conector Fabric.",
                        severity="error",
                    ))
    else:
        # Fallback: audita apenas o que já está descrito no próprio mapping.
        for t in inspect_result["tables"]:
            for c in t["columns"]:
                total_checked += 1
                declared_type = str(c.get("sourceType", ""))
                if NUMBER_BARE.match(declared_type):
                    issues.append(ColumnAuditIssue(
                        table=t["source_table"], column=c.get("sourceColumnName", "?"),
                        source_type=declared_type,
                        reason="NUMBER sem precisão/escala declarada no próprio mapping.",
                        severity="warning",
                    ))

    ok = not any(i.severity == "error" for i in issues) and not unmapped_columns
    return AuditOutcome(
        ok=ok, total_columns_checked=total_checked, issues=issues,
        unmapped_tables=unmapped_tables, unmapped_columns=unmapped_columns,
    )
