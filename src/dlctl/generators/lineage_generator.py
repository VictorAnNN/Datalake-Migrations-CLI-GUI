"""dlctl.generators.lineage_generator

Gera os artefatos de Linhagem do Lakehouse (feature portada do
Skill-LineageFabric) a partir de:

1. Notebooks locais de `input/lakehouse-dev` (parse de `notebook-content.py`)
   -> aba "Linhagem Tabelas" (18 colunas, com expansão transitiva) e aba
   "Tabelas" (30 colunas). A camada semântica de Materialized Lake Views
   (MLV) é tratada separadamente de Gold.
2. JSONs do Fabric Scanner API (`input/Workspaces` ou um .zip) -> trilha de
   dependência até fontes SharePoint (dataset/dashboard -> tabela -> fonte),
   com validação de existência.

Os resultados são persistidos em `dlctl.core.state` (LineageDependency,
LineageTableCatalog, LineageSharePointDependency) para consumo pelo CLI e
pelo dashboard, e opcionalmente exportados para Excel em
`manifests/lineage/`.
"""
from __future__ import annotations

import ast
import json
import re
import zipfile
from pathlib import Path
from typing import Optional

import pandas as pd

from dlctl.config import Profile
from dlctl.config import PROJECT_ROOT
from dlctl.core import state as state_db

# ---------------------------------------------------------------------------
# Estrutura exata das abas do artefato "Linhagem Tabelas" / "Tabelas"
# (mesma nomenclatura do fabric-migrate-plan do Skill-LineageFabric).
# ---------------------------------------------------------------------------
COLS_LINHAGEM_TABELAS = [
    "ID", "TIPO_DEPENDENCIA", "CAMADA_ORIGEM", "LAKEHOUSE_ORIGEM",
    "SCHEMA_ORIGEM", "TABELA_ORIGEM", "STATUS_ORIGEM",
    "ORIGEM_PUBLICADA_DEV", "ORIGEM_MATERIALIZADA_DEV",
    "CAMADA_DESTINO", "LAKEHOUSE_DESTINO", "SCHEMA_DESTINO",
    "TABELA_DESTINO", "STATUS_DESTINO", "DESTINO_PUBLICADO_DEV",
    "DESTINO_MATERIALIZADO_DEV", "EXECUCAO_DESTINO_DEV", "OBSERVACAO",
]
COLS_LINEAGE_TABLES = COLS_LINHAGEM_TABELAS + ["Workspace", "Domínio"]

COLS_TABELAS = [
    "Domínio", "Conexão Gateway", "Fonte", "Tipo", "Sistema",
    "Schema Dev", "Schema Origem", "Tabela Origem", "Mapeamento Inicial?",
    "Colunas Chave", "Coluna Incremental", "Método de Leitura",
    "Método de Gravação", "Frequência de Atualização", "Ferramenta de Extração",
    "Lakehouse Destino", "Camada Destino", "Tabela Destino", "Mascaramento",
    "RLS", "Status DEV Construção", "Status DEV Pipeline",
    "Status DEV Governança", "Status DEV (Aprovação)", "Status HML",
    "Status HML (Aprovação)", "Status PRD", "Status PRD (Aprovação)",
    "Observações", "Responsável Desbloqueio",
]

_DEPENDENCY_FIELD_MAP = {
    "ID": None,  # gerado pelo banco
    "TIPO_DEPENDENCIA": "dependency_type",
    "CAMADA_ORIGEM": "source_layer",
    "LAKEHOUSE_ORIGEM": "source_lakehouse",
    "SCHEMA_ORIGEM": "source_schema",
    "TABELA_ORIGEM": "source_table",
    "STATUS_ORIGEM": "source_status",
    "ORIGEM_PUBLICADA_DEV": "source_published_dev",
    "ORIGEM_MATERIALIZADA_DEV": "source_materialized_dev",
    "CAMADA_DESTINO": "target_layer",
    "LAKEHOUSE_DESTINO": "target_lakehouse",
    "SCHEMA_DESTINO": "target_schema",
    "TABELA_DESTINO": "target_table",
    "STATUS_DESTINO": "target_status",
    "DESTINO_PUBLICADO_DEV": "target_published_dev",
    "DESTINO_MATERIALIZADO_DEV": "target_materialized_dev",
    "EXECUCAO_DESTINO_DEV": "target_executed_dev",
    "OBSERVACAO": "note",
    "Workspace": "workspace",
    "Domínio": "domain",
}

_CATALOG_FIELD_MAP = {
    "Domínio": "domain",
    "Conexão Gateway": "connection_gateway",
    "Fonte": "source",
    "Tipo": "source_type",
    "Sistema": "system",
    "Schema Dev": "schema_dev",
    "Schema Origem": "schema_source",
    "Tabela Origem": "source_table",
    "Mapeamento Inicial?": "initial_mapping",
    "Colunas Chave": "key_columns",
    "Coluna Incremental": "incremental_column",
    "Método de Leitura": "read_method",
    "Método de Gravação": "write_method",
    "Frequência de Atualização": "refresh_frequency",
    "Ferramenta de Extração": "extraction_tool",
    "Lakehouse Destino": "target_lakehouse",
    "Camada Destino": "target_layer",
    "Tabela Destino": "target_table",
    "Mascaramento": "masking",
    "RLS": "rls",
    "Status DEV Construção": "status_dev_build",
    "Status DEV Pipeline": "status_dev_pipeline",
    "Status DEV Governança": "status_dev_governance",
    "Status DEV (Aprovação)": "status_dev_approval",
    "Status HML": "status_hml",
    "Status HML (Aprovação)": "status_hml_approval",
    "Status PRD": "status_prd",
    "Status PRD (Aprovação)": "status_prd_approval",
    "Observações": "note",
    "Responsável Desbloqueio": "unblock_owner",
}


class LineageGeneratorError(RuntimeError):
    pass


# ===========================================================================
# 1. PARSING DE NOTEBOOKS DO LAKEHOUSE-DEV (portado de migration_control_generator.py)
# ===========================================================================

def find_notebooks(lakehouse_dev_path: str) -> list[Path]:
    root = Path(lakehouse_dev_path)
    if not root.exists():
        return []
    return sorted(
        [*root.rglob("notebook-content.py"), *root.rglob("notebook-content.sql")],
        key=lambda path: str(path).lower(),
    )


def detect_domain(nb_path: Path) -> str:
    parts = nb_path.parts
    lakehouse_idx = None
    for i, p in enumerate(parts):
        if p.lower() in ("lakehouse-dev",):
            lakehouse_idx = i
            break
    if lakehouse_idx is not None and lakehouse_idx + 1 < len(parts):
        return parts[lakehouse_idx + 1].upper()
    return "DESCONHECIDO"


def parse_config_notebook(content: str, domain: str) -> list[dict]:
    rows = []
    match = re.search(r'TABLE_CONFIG_ROWS_JSON\s*=\s*r?"""(.*?)"""', content, re.DOTALL)
    if not match:
        return rows
    try:
        config_list = json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return rows

    for cfg in config_list:
        if not isinstance(cfg, dict):
            continue
        pk = cfg.get("primary_keys", "[]")
        if isinstance(pk, str):
            try:
                pk_list = json.loads(pk)
                pk = ", ".join(pk_list) if isinstance(pk_list, list) else pk
            except Exception:
                pass
        rows.append({
            "Domínio": domain, "Conexão Gateway": "", "Fonte": cfg.get("source_system", ""),
            "Tipo": cfg.get("source_type", ""), "Sistema": cfg.get("source_system", ""),
            "Schema Dev": cfg.get("target_layer", ""), "Schema Origem": cfg.get("source_schema", ""),
            "Tabela Origem": cfg.get("source_table", ""),
            "Mapeamento Inicial?": "Sim" if cfg.get("enabled") else "Não",
            "Colunas Chave": pk, "Coluna Incremental": cfg.get("incremental_column", ""),
            "Método de Leitura": cfg.get("read_mode", ""), "Método de Gravação": cfg.get("write_mode", ""),
            "Frequência de Atualização": cfg.get("frequency", ""),
            "Ferramenta de Extração": "BI Publisher" if cfg.get("source_type") == "bipublisher" else cfg.get("source_type", ""),
            "Lakehouse Destino": cfg.get("target_lakehouse", ""), "Camada Destino": cfg.get("target_layer", ""),
            "Tabela Destino": cfg.get("target_table", ""), "Mascaramento": "", "RLS": "",
            "Status DEV Construção": "Concluída" if cfg.get("enabled") else "Backlog",
            "Status DEV Pipeline": "Concluída" if cfg.get("enabled") else "Backlog",
            "Status DEV Governança": "", "Status DEV (Aprovação)": "", "Status HML": "",
            "Status HML (Aprovação)": "", "Status PRD": "", "Status PRD (Aprovação)": "",
            "Observações": "", "Responsável Desbloqueio": "",
        })
    return rows


def extract_list_assignment(content: str, variable_name: str) -> list:
    match = re.search(rf"(?m)^\s*{re.escape(variable_name)}\s*=\s*(\[)", content)
    if not match:
        return []
    start = match.start(1)
    depth = 0
    quote = None
    escaped = False
    for position in range(start, len(content)):
        char = content[position]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                try:
                    value = ast.literal_eval(content[start:position + 1])
                except (SyntaxError, ValueError):
                    return []
                return value if isinstance(value, list) else []
    return []


def extract_explicit_table_references(content: str, excluded_tables: Optional[set[str]] = None) -> list[dict]:
    excluded = {table.casefold() for table in (excluded_tables or set())}
    references = []
    patterns = (
        r'table_ref\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*\)',
        r'spark\.table\(\s*["\']([^"\']+)\.([^"\']+)\.([^"\']+)["\']\s*\)',
        r'(?i)(?:FROM|JOIN)\s+([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)',
    )
    seen = set()
    for pattern in patterns:
        for match in re.finditer(pattern, content):
            lakehouse, schema, table = (part.strip() for part in match.groups())
            key = (lakehouse.casefold(), schema.casefold(), table.casefold())
            if lakehouse.casefold() in {"pyspark", "spark", "python"}:
                continue
            if not table or table.casefold() in excluded or key in seen:
                continue
            seen.add(key)
            layer = schema.lower() if schema.lower() in {"bronze", "silver", "gold"} else ""
            references.append({
                "lakehouse": lakehouse, "schema": schema, "table": table,
                "layer": layer, "evidence": "notebook code namespace",
            })
    return references


_SQL_QUALIFIED_REFERENCE = re.compile(
    r"(?i)\b(?:FROM|JOIN)\s+((?:`[^`]+`|[A-Za-z0-9_-]+)"
    r"(?:\.(?:`[^`]+`|[A-Za-z0-9_-]+)){2,3})"
)
_MLV_TARGET = re.compile(
    r"(?i)CREATE\s+OR\s+REPLACE\s+MATERIALIZED\s+LAKE\s+VIEW\s+"
    r"((?:`[^`]+`|[A-Za-z0-9_-]+)(?:\.(?:`[^`]+`|[A-Za-z0-9_-]+)){1,3})"
)


def _unquote_sql_identifier(value: str) -> str:
    value = str(value).strip()
    if len(value) >= 2 and value[0] == "`" and value[-1] == "`":
        return value[1:-1].replace("``", "`")
    return value


def _split_sql_qualified_reference(value: str) -> list[str]:
    """Divide uma referência SQL qualificada sem perder backticks internos."""
    parts: list[str] = []
    current: list[str] = []
    quoted = False
    for char in str(value):
        if char == "`":
            quoted = not quoted
            current.append(char)
        elif char == "." and not quoted:
            parts.append(_unquote_sql_identifier("".join(current)))
            current = []
        else:
            current.append(char)
    if current:
        parts.append(_unquote_sql_identifier("".join(current)))
    return [part.strip() for part in parts if part.strip()]


def parse_semantic_mlv_notebook(content: str, domain: str) -> dict:
    """Extrai uma MLV semântica e suas fontes físicas do SQL do notebook.

    Fabric aceita referências com três partes (lakehouse.schema.tabela) e,
    em payloads exportados, com quatro partes (ambiente.lakehouse.schema.tabela).
    Na segunda forma, o ambiente fica na observação e o lakehouse continua no
    campo próprio.
    """
    result = {
        "type": "semantic_mlv", "domain": domain, "target_lakehouse": "",
        "target_schema": "semantic", "target_table": "", "dependencies": [],
    }
    target_match = _MLV_TARGET.search(content)
    if not target_match:
        return result

    target_parts = _split_sql_qualified_reference(target_match.group(1))
    if len(target_parts) >= 2:
        result["target_schema"] = target_parts[-2]
        result["target_table"] = target_parts[-1]
        if len(target_parts) >= 3:
            result["target_lakehouse"] = target_parts[-3]

    dependencies: list[dict] = []
    seen: set[tuple[str, ...]] = set()
    for match in _SQL_QUALIFIED_REFERENCE.finditer(content):
        parts = _split_sql_qualified_reference(match.group(1))
        environment = ""
        if len(parts) == 4:
            environment, lakehouse, schema, table = parts
        elif len(parts) == 3:
            lakehouse, schema, table = parts
        else:
            continue
        if table.casefold() == str(result["target_table"]).casefold():
            continue
        key = tuple(part.casefold() for part in (lakehouse, schema, table))
        if key in seen:
            continue
        seen.add(key)
        layer = schema.casefold() if schema.casefold() in {"bronze", "silver", "gold"} else ""
        dependencies.append({
            "layer": layer, "lakehouse": lakehouse, "schema": schema,
            "table": table, "environment": environment,
            "relation": "Fonte de MLV semântica",
        })
        if not result["target_lakehouse"]:
            result["target_lakehouse"] = lakehouse
    result["dependencies"] = dependencies
    return result


def parse_silver_notebook(content: str, domain: str) -> dict:
    result = {"type": "silver", "domain": domain}
    m = re.search(r'TARGET_LAKEHOUSE_LOGICAL\s*=\s*["\']([^"\']+)["\']', content)
    if not m:
        m = re.search(r'TARGET_LAKEHOUSE\s*=\s*["\']([^"\']+)["\']', content)
    result["target_lakehouse"] = m.group(1) if m else ""

    m = re.search(r'TARGET_SCHEMA\s*=\s*["\']([^"\']+)["\']', content)
    result["target_schema"] = m.group(1) if m else "silver"

    m = re.search(r'SILVER_TABLE\s*=\s*["\']([^"\']+)["\']', content)
    result["silver_table"] = m.group(1) if m else ""

    m = re.search(r'WRITE_MODE\s*=\s*["\']([^"\']+)["\']', content)
    result["write_mode"] = m.group(1) if m else ""

    m = re.search(r'BRONZE_SOURCES\s*=\s*\[(.*?)\]', content, re.DOTALL)
    sources = []
    if m:
        try:
            src_text = "[" + m.group(1) + "]"
            src_text = re.sub(r'#[^\n]*', '', src_text)
            sources = eval(src_text, {"__builtins__": {}}, {})
        except Exception:
            pass
    result["bronze_sources"] = sources

    if not sources:
        m = re.search(r'BRONZE_TABLES\s*=\s*\[(.*?)\]', content, re.DOTALL)
        if m:
            try:
                tables_text = "[" + m.group(1) + "]"
                tables_text = re.sub(r'#[^\n]*', '', tables_text)
                tables_list = eval(tables_text, {"__builtins__": {}}, {})
                for t in tables_list:
                    if isinstance(t, str):
                        sources.append({"lakehouse": result["target_lakehouse"], "schema": "bronze", "table": t})
            except Exception:
                pass
        result["bronze_sources"] = sources

    if not sources:
        result["bronze_sources"] = extract_explicit_table_references(content, {result.get("silver_table", "")})

    return result


def parse_gold_notebook(content: str, domain: str) -> dict:
    result = {"type": "gold", "domain": domain}
    m = re.search(r'GOLD_LAKEHOUSE_LOGICAL\s*=\s*["\']([^"\']+)["\']', content)
    if not m:
        m = re.search(r'GOLD_LAKEHOUSE\s*=\s*["\']([^"\']+)["\']', content)
    if not m:
        m = re.search(r'(?im)^\s*(?:#\s*)?(?:Tabela Destino|Destino)\s*:\s*([^\.\s]+)\.(?:silver|gold)\.', content)
    result["gold_lakehouse"] = m.group(1) if m else ""

    m = re.search(r'GOLD_SCHEMA\s*=\s*["\']([^"\']+)["\']', content)
    result["gold_schema"] = m.group(1) if m else "gold"

    m = re.search(r'GOLD_TABLE\s*=\s*["\']([^"\']+)["\']', content)
    result["gold_table"] = m.group(1) if m else ""

    m = re.search(r'GOLD_LOGICAL_TABLE\s*=\s*["\']([^"\']+)["\']', content)
    result["gold_logical_table"] = m.group(1) if m else result["gold_table"].upper()

    deps = []
    for variable_name in ("DEPENDENCIES", "SILVER_SOURCES", "SOURCES", "GOLD_SOURCES", "OURO_SOURCES"):
        for dependency in extract_list_assignment(content, variable_name):
            if not isinstance(dependency, dict):
                continue
            normalized = dict(dependency)
            layer = str(normalized.get("layer") or normalized.get("kind") or normalized.get("schema") or "").strip().lower()
            if not layer and variable_name in {"GOLD_SOURCES", "OURO_SOURCES"}:
                layer = "gold"
            if layer not in {"bronze", "silver", "gold"}:
                layer = ""
            if layer:
                normalized["layer"] = layer
            deps.append(normalized)

    declared_tables = {str(dep.get("table", "")).strip() for dep in deps if dep.get("table")}
    deps.extend(extract_explicit_table_references(content, declared_tables | {result["gold_table"]}))

    unique_deps: dict[tuple, dict] = {}
    for dependency in deps:
        key = tuple(str(dependency.get(field, "")).strip().casefold() for field in ("layer", "lakehouse", "schema", "table"))
        if key not in unique_deps:
            unique_deps[key] = dependency
        else:
            unique_deps[key].update({k: v for k, v in dependency.items() if v not in (None, "")})
    result["dependencies"] = list(unique_deps.values())
    return result


def parse_operacao_notebook(content: str, domain: str) -> dict:
    result = {"type": "operacao_silver", "domain": domain}
    m = re.search(r"PAR_SOURCE_TABLE\s*=\s*['\"]([^'\"]+)['\"]", content)
    result["source_table"] = m.group(1) if m else ""
    m = re.search(r"PAR_TARGET_TABLE\s*=\s*['\"]([^'\"]+)['\"]", content)
    result["target_table"] = m.group(1) if m else ""
    m = re.search(r"SOURCE_TABLE\s*=\s*f?['\"]([^'\"]+)['\"]", content)
    result["source_full"] = m.group(1) if m else ""
    m = re.search(r"TARGET_TABLE\s*=\s*f?['\"]([^'\"]+)['\"]", content)
    result["target_full"] = m.group(1) if m else ""
    return result


def extract_notebook_workspace(content: str) -> str:
    match = re.search(r'(?m)^\s*WORKSPACE_NAME\s*=\s*["\']([^"\']+)["\']', content)
    return match.group(1).strip() if match and match.group(1).strip() else ""


def classify_notebook(content: str) -> str:
    if "TABLE_CONFIG_ROWS_JSON" in content:
        return "config"
    if _MLV_TARGET.search(content) and re.search(r"(?i)\bsemantic\.", content):
        return "semantic_mlv"
    if "# G1_HEADER_METADATA" in content or "GOLD_LAKEHOUSE_LOGICAL" in content:
        return "gold"
    if "# C1_HEADER_METADATA" in content and "BRONZE -> SILVER" in content:
        return "silver"
    if "BRONZE_SOURCES" in content or "SILVER_TABLE" in content:
        return "silver"
    if "PAR_SOURCE_TABLE" in content and "PAR_TARGET_TABLE" in content:
        return "operacao"
    return "other"


def process_lakehouse_dev(lakehouse_dev_path: str) -> dict:
    """Processa todos os notebooks de lakehouse-dev e retorna as linhas
    para as abas Linhagem Tabelas ("linhagem") e Tabelas ("tabelas")."""
    notebooks = find_notebooks(lakehouse_dev_path)
    tabelas_rows: list[dict] = []
    linhagem_rows: list[dict] = []
    line_id = 0

    for nb_path in notebooks:
        try:
            content = nb_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        domain = detect_domain(nb_path)
        nb_type = classify_notebook(content)
        notebook_workspace = extract_notebook_workspace(content)
        lineage_start = len(linhagem_rows)

        try:
            if nb_type == "config":
                tabelas_rows.extend(parse_config_notebook(content, domain))

            elif nb_type == "silver":
                parsed = parse_silver_notebook(content, domain)
                if parsed.get("silver_table") and parsed.get("bronze_sources"):
                    for src in parsed["bronze_sources"]:
                        line_id += 1
                        linhagem_rows.append({
                            "ID": line_id, "TIPO_DEPENDENCIA": "BRONZE -> SILVER", "CAMADA_ORIGEM": "bronze",
                            "LAKEHOUSE_ORIGEM": src.get("lakehouse", parsed.get("target_lakehouse", "")),
                            "SCHEMA_ORIGEM": src.get("schema", "bronze"),
                            "TABELA_ORIGEM": src.get("table", src.get("ref", "")),
                            "STATUS_ORIGEM": "", "ORIGEM_PUBLICADA_DEV": "", "ORIGEM_MATERIALIZADA_DEV": "",
                            "CAMADA_DESTINO": parsed.get("target_schema", "silver"),
                            "LAKEHOUSE_DESTINO": parsed.get("target_lakehouse", ""),
                            "SCHEMA_DESTINO": parsed.get("target_schema", "silver"),
                            "TABELA_DESTINO": parsed.get("silver_table", ""),
                            "STATUS_DESTINO": "", "DESTINO_PUBLICADO_DEV": "", "DESTINO_MATERIALIZADO_DEV": "",
                            "EXECUCAO_DESTINO_DEV": "", "OBSERVACAO": "",
                        })

            elif nb_type == "gold":
                parsed = parse_gold_notebook(content, domain)
                for dep in parsed.get("dependencies", []):
                    line_id += 1
                    source_layer = str(dep.get("layer") or dep.get("schema") or "").strip().lower()
                    if source_layer not in {"bronze", "silver", "gold"}:
                        source_layer = ""
                    target_layer = str(parsed.get("gold_schema") or "gold").strip().lower()
                    linhagem_rows.append({
                        "ID": line_id,
                        "TIPO_DEPENDENCIA": f"{source_layer.upper() or 'DESCONHECIDA'} -> {target_layer.upper()}",
                        "CAMADA_ORIGEM": source_layer, "LAKEHOUSE_ORIGEM": dep.get("lakehouse", ""),
                        "SCHEMA_ORIGEM": dep.get("schema", ""), "TABELA_ORIGEM": dep.get("table", ""),
                        "STATUS_ORIGEM": dep.get("observed_status", ""),
                        "ORIGEM_PUBLICADA_DEV": "Sim" if dep.get("live_present") else "Não",
                        "ORIGEM_MATERIALIZADA_DEV": "", "CAMADA_DESTINO": target_layer,
                        "LAKEHOUSE_DESTINO": parsed.get("gold_lakehouse", ""), "SCHEMA_DESTINO": target_layer,
                        "TABELA_DESTINO": parsed.get("gold_table", ""), "STATUS_DESTINO": dep.get("required_status", ""),
                        "DESTINO_PUBLICADO_DEV": "", "DESTINO_MATERIALIZADO_DEV": "", "EXECUCAO_DESTINO_DEV": "",
                        "OBSERVACAO": dep.get("relation", ""),
                    })

            elif nb_type == "semantic_mlv":
                parsed = parse_semantic_mlv_notebook(content, domain)
                target_table = parsed.get("target_table", "")
                if target_table and parsed.get("dependencies"):
                    for dep in parsed["dependencies"]:
                        line_id += 1
                        source_layer = str(dep.get("layer", "")).strip().lower()
                        target_layer = str(parsed.get("target_schema") or "semantic").strip().lower()
                        environment = str(dep.get("environment", "")).strip()
                        note = str(dep.get("relation", ""))
                        if environment:
                            note += f"; ambiente={environment}"
                        linhagem_rows.append({
                            "ID": line_id,
                            "TIPO_DEPENDENCIA": f"{source_layer.upper() or 'FONTE'} -> SEMANTIC MLV",
                            "CAMADA_ORIGEM": source_layer,
                            "LAKEHOUSE_ORIGEM": dep.get("lakehouse", ""),
                            "SCHEMA_ORIGEM": dep.get("schema", ""),
                            "TABELA_ORIGEM": dep.get("table", ""),
                            "STATUS_ORIGEM": "",
                            "ORIGEM_PUBLICADA_DEV": "",
                            "ORIGEM_MATERIALIZADA_DEV": "",
                            "CAMADA_DESTINO": target_layer,
                            "LAKEHOUSE_DESTINO": parsed.get("target_lakehouse", ""),
                            "SCHEMA_DESTINO": target_layer,
                            "TABELA_DESTINO": target_table,
                            "STATUS_DESTINO": "",
                            "DESTINO_PUBLICADO_DEV": "",
                            "DESTINO_MATERIALIZADO_DEV": "Sim",
                            "EXECUCAO_DESTINO_DEV": "",
                            "OBSERVACAO": note,
                        })

            elif nb_type == "operacao":
                parsed = parse_operacao_notebook(content, domain)
                if parsed.get("source_table") and parsed.get("target_table"):
                    line_id += 1
                    source_full = parsed.get("source_full", "")
                    parts = source_full.replace("f'", "").replace("'", "").split(".")
                    src_lh = parts[0] if len(parts) > 0 else "LH_OPERACAO"
                    src_schema = parts[1] if len(parts) > 1 else "MAXIMOOFFSHORE"
                    src_table = parts[2] if len(parts) > 2 else parsed["source_table"]

                    target_full = parsed.get("target_full", "")
                    tgt_parts = target_full.replace("f'", "").replace("'", "").split(".")
                    tgt_lh = tgt_parts[0] if len(tgt_parts) > 0 else "LH_OPERACAO"
                    tgt_schema = tgt_parts[1] if len(tgt_parts) > 1 else "silver"
                    tgt_table = tgt_parts[2] if len(tgt_parts) > 2 else parsed["target_table"]

                    linhagem_rows.append({
                        "ID": line_id, "TIPO_DEPENDENCIA": "BRONZE -> SILVER", "CAMADA_ORIGEM": "bronze",
                        "LAKEHOUSE_ORIGEM": src_lh, "SCHEMA_ORIGEM": src_schema, "TABELA_ORIGEM": src_table,
                        "STATUS_ORIGEM": "", "ORIGEM_PUBLICADA_DEV": "", "ORIGEM_MATERIALIZADA_DEV": "",
                        "CAMADA_DESTINO": tgt_schema.lower(), "LAKEHOUSE_DESTINO": tgt_lh, "SCHEMA_DESTINO": tgt_schema,
                        "TABELA_DESTINO": tgt_table, "STATUS_DESTINO": "", "DESTINO_PUBLICADO_DEV": "",
                        "DESTINO_MATERIALIZADO_DEV": "", "EXECUCAO_DESTINO_DEV": "", "OBSERVACAO": "",
                    })
                    tabelas_rows.append({
                        "Domínio": domain, "Conexão Gateway": "", "Fonte": "Maximo", "Tipo": "database",
                        "Sistema": "Maximo", "Schema Dev": tgt_schema, "Schema Origem": src_schema,
                        "Tabela Origem": src_table, "Mapeamento Inicial?": "Sim", "Colunas Chave": "",
                        "Coluna Incremental": "", "Método de Leitura": "full", "Método de Gravação": "overwrite",
                        "Frequência de Atualização": "", "Ferramenta de Extração": "Spark",
                        "Lakehouse Destino": tgt_lh, "Camada Destino": tgt_schema, "Tabela Destino": tgt_table,
                        "Mascaramento": "", "RLS": "", "Status DEV Construção": "Concluída",
                        "Status DEV Pipeline": "Concluída", "Status DEV Governança": "",
                        "Status DEV (Aprovação)": "", "Status HML": "", "Status HML (Aprovação)": "",
                        "Status PRD": "", "Status PRD (Aprovação)": "", "Observações": "",
                        "Responsável Desbloqueio": "",
                    })
        except Exception:
            continue

        for row in linhagem_rows[lineage_start:]:
            row["Workspace"] = notebook_workspace
            row["Domínio"] = domain

    return {"tabelas": tabelas_rows, "linhagem": linhagem_rows}


# ===========================================================================
# 2. EXPANSÃO TRANSITIVA (portado de migration_control_generator.py)
# ===========================================================================

def _lineage_table_keys(row: dict) -> set[tuple]:
    lakehouse = str(row.get("LAKEHOUSE_DESTINO", "")).strip().casefold()
    schema = str(row.get("SCHEMA_DESTINO", "")).strip().casefold()
    table = str(row.get("TABELA_DESTINO", "")).strip().casefold()
    keys = set()
    if schema and table:
        keys.add((schema, table))
    if lakehouse and schema and table:
        keys.add((lakehouse, schema, table))
    return keys


def _lineage_source_keys(row: dict) -> set[tuple]:
    lakehouse = str(row.get("LAKEHOUSE_ORIGEM", "")).strip().casefold()
    schema = str(row.get("SCHEMA_ORIGEM", "")).strip().casefold()
    table = str(row.get("TABELA_ORIGEM", "")).strip().casefold()
    keys = set()
    if schema and table:
        keys.add((schema, table))
    if lakehouse and schema and table:
        keys.add((lakehouse, schema, table))
    return keys


def expand_transitive_lineage(linhagem_rows: list[dict]) -> list[dict]:
    """Expande ancestrais conhecidos para cada destino final (mesma regra do
    Skill-LineageFabric): as relações diretas permanecem intactas; cada
    ancestral descoberto é reprojetado para o destino final da relação
    inicial, evitando duplicatas."""
    if not linhagem_rows:
        return []

    direct_rows = [dict(row) for row in linhagem_rows]
    producers: dict[tuple, list[dict]] = {}
    for row in direct_rows:
        for key in _lineage_table_keys(row):
            producers.setdefault(key, []).append(row)

    expanded = list(direct_rows)
    seen = {
        tuple(str(row.get(column, "")).strip().casefold() for column in COLS_LINEAGE_TABLES if column != "ID")
        for row in direct_rows
    }

    for root in direct_rows:
        final_layer = str(root.get("CAMADA_DESTINO", "")).strip().lower()
        final_lakehouse = root.get("LAKEHOUSE_DESTINO", "")
        final_schema = root.get("SCHEMA_DESTINO", "")
        final_table = root.get("TABELA_DESTINO", "")
        pending = [(root, 0)]
        visited = set()

        while pending:
            current, depth = pending.pop()
            current_keys = _lineage_source_keys(current)
            current_identity = tuple(sorted(current_keys))
            if current_identity in visited:
                continue
            visited.add(current_identity)

            matching_producers = {
                id(producer): producer
                for key in current_keys
                for producer in producers.get(key, [])
            }
            for producer in matching_producers.values():
                if depth == 0 and producer is root:
                    continue
                source_layer = str(producer.get("CAMADA_ORIGEM", "")).strip().lower()
                if not source_layer:
                    continue
                relation = dict(producer)
                relation["ID"] = None
                relation["TIPO_DEPENDENCIA"] = f"{source_layer.upper()} -> {final_layer.upper() or 'DESCONHECIDA'}"
                relation["CAMADA_DESTINO"] = final_layer
                relation["LAKEHOUSE_DESTINO"] = final_lakehouse
                relation["SCHEMA_DESTINO"] = final_schema
                relation["TABELA_DESTINO"] = final_table
                relation["OBSERVACAO"] = "[TRANSITIVA] " + str(producer.get("OBSERVACAO", ""))
                relation["Workspace"] = root.get("Workspace", "")
                relation["Domínio"] = root.get("Domínio", "")
                identity = tuple(str(relation.get(column, "")).strip().casefold() for column in COLS_LINEAGE_TABLES if column != "ID")
                if identity not in seen:
                    expanded.append(relation)
                    seen.add(identity)
                pending.append((producer, depth + 1))

    for index, row in enumerate(expanded, start=1):
        row["ID"] = index
        row["_is_transitive"] = "[TRANSITIVA]" in str(row.get("OBSERVACAO", ""))
    return expanded


# ===========================================================================
# 3. TRILHA DE DEPENDÊNCIAS ATÉ SHAREPOINT (a partir dos JSONs do Fabric Scanner)
# ===========================================================================
def _load_json_files(root: str) -> list[Path]:
    path = Path(root)
    if path.is_file() and path.suffix.lower() == ".zip":
        extract_to = path.parent / f"_extracted_{path.stem}"
        if not extract_to.exists():
            with zipfile.ZipFile(path, "r") as zf:
                zf.extractall(extract_to)
        path = extract_to
    if not path.exists():
        return []
    return sorted(path.rglob("*.json"))


def _read_json(path: Path) -> dict:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return json.loads(path.read_text(encoding=enc))
        except Exception:
            continue
    return {}


# ===========================================================================
# 2.5. INVENTÁRIO PESQUISÁVEL DOS JSONS (Workspaces Power BI/Fabric)
# ===========================================================================

def build_workspace_inventory(workspaces_input: str) -> list[dict]:
    """Varre os JSONs do Fabric Scanner API e monta um inventário achatado e
    pesquisável de tudo que existe nos workspaces exportados: o próprio
    Workspace, Datasets (com contagem de tabelas), Dataset Tables, Dataflows
    Gen1/Gen2 e Reports/Dashboards — para responder perguntas do tipo "em
    qual workspace está o dataset X?" ou "quais relatórios existem no
    workspace Y?" sem precisar abrir os JSONs manualmente.

    Cada linha tem: workspace, workspace_id, item_type (Workspace | Dataset |
    Dataset Table | Dataflow | Report), item_name, item_id, parent_name
    (ex.: dataset dono de uma tabela/relatório), detail (texto livre com
    metadados relevantes: table_count, generation, storage_mode, etc.) e
    source_file (nome do JSON de origem, útil para auditoria)."""
    json_files = _load_json_files(workspaces_input)
    rows: list[dict] = []

    for jf in json_files:
        data = _read_json(jf)
        if not data:
            continue
        source_file = jf.name

        for ws in data.get("workspaces", []):
            ws_id = str(ws.get("id", ""))
            ws_name = ws.get("name", ws_id or "unknown")

            rows.append({
                "workspace": ws_name, "workspace_id": ws_id, "item_type": "Workspace",
                "item_name": ws_name, "item_id": ws_id, "parent_name": "",
                "detail": f"datasets={len(ws.get('datasets', []))}, "
                          f"dataflows={len(ws.get('dataflows', []))}, "
                          f"reports={len(ws.get('reports', []))}",
                "source_file": source_file,
            })

            for ds in ws.get("datasets", []):
                ds_id = str(ds.get("id", ""))
                ds_name = ds.get("name", ds_id)
                tables = ds.get("tables", [])
                rows.append({
                    "workspace": ws_name, "workspace_id": ws_id, "item_type": "Dataset",
                    "item_name": ds_name, "item_id": ds_id, "parent_name": "",
                    "detail": f"table_count={len(tables)}, storage_mode={ds.get('targetStorageMode', '')}, "
                              f"configured_by={ds.get('configuredBy', '')}",
                    "source_file": source_file,
                })
                for tbl in tables:
                    tbl_name = tbl.get("name", "")
                    rows.append({
                        "workspace": ws_name, "workspace_id": ws_id, "item_type": "Dataset Table",
                        "item_name": tbl_name, "item_id": "", "parent_name": ds_name,
                        # Preserve the canonical parent identifier. Dataset names are
                        # not globally unique and may repeat in different workspaces.
                        "detail": f"dataset_id={ds_id}, storage_mode={tbl.get('storageMode', '')}",
                        "source_file": source_file,
                    })

            for df in ws.get("dataflows", []):
                df_id = str(df.get("objectId") or df.get("id", ""))
                df_name = df.get("name", df_id)
                rows.append({
                    "workspace": ws_name, "workspace_id": ws_id, "item_type": "Dataflow",
                    "item_name": df_name, "item_id": df_id, "parent_name": "",
                    "detail": f"generation={df.get('generation', 1)}, configured_by={df.get('configuredBy', '')}",
                    "source_file": source_file,
                })

            for report in ws.get("reports", []):
                report_id = str(report.get("id", ""))
                report_name = report.get("name", report_id)
                dataset_id = str(report.get("datasetId", ""))
                rows.append({
                    "workspace": ws_name, "workspace_id": ws_id, "item_type": "Report",
                    "item_name": report_name, "item_id": report_id, "parent_name": dataset_id,
                    "detail": f"dataset_id={dataset_id or '(não informado)'}",
                    "source_file": source_file,
                })

    return rows


# ===========================================================================
# 3. TRILHA DE DEPENDÊNCIAS ATÉ SHAREPOINT (a partir dos JSONs do Fabric Scanner)
# ===========================================================================

_SHAREPOINT_PATTERN = re.compile(r'SharePoint\.\w+\s*\(\s*"([^"]+)"', re.IGNORECASE)
_SHAREPOINT_DATASOURCE_TYPES = {"sharepointlist", "sharepoint", "sharepointonlinelist"}

# Passos comuns de navegação/filtro após a conexão SharePoint.Contents/Files/Tables(site_url, ...):
# a URL do site é sempre o 1º argumento (capturado por _SHAREPOINT_PATTERN); a pasta/biblioteca/
# arquivo específico só aparece em passos seguintes da expressão M (Table.SelectRows por
# [Folder Path]/[Name], ou navegação {[Name="..."]}[Content]).
_FOLDER_PATH_PATTERN = re.compile(r'\[Folder Path\]\s*(?:=|,\s*)\s*"([^"]+)"', re.IGNORECASE)
_NAME_FILTER_PATTERN = re.compile(r'\[Name\]\s*=\s*"([^"]+)"', re.IGNORECASE)
_NAME_NAV_PATTERN = re.compile(r'\{\s*\[Name\s*=\s*"([^"]+)"\s*\]\s*\}', re.IGNORECASE)


def _extract_sharepoint_full_path(expr: str, base_url: str) -> str:
    """Tenta resolver a pasta/arquivo real navegado a partir da URL do site
    (best-effort: parseia padrões comuns de Table.SelectRows/[Folder Path]/
    [Name] e navegação {[Name="..."]}[Content] nos passos seguintes da
    expressão M). Se nada for encontrado, retorna a própria URL do site
    (mesma coisa que `sharepoint_reference`) — nunca fica vazio se houver base_url."""
    if not expr:
        return base_url
    expr_clean = expr.replace("#(lf)", "\n")

    folder_match = _FOLDER_PATH_PATTERN.search(expr_clean)
    name_matches = _NAME_NAV_PATTERN.findall(expr_clean) + _NAME_FILTER_PATTERN.findall(expr_clean)

    if folder_match:
        full_path = folder_match.group(1).rstrip("/")
        if name_matches and not full_path.endswith(name_matches[-1]):
            full_path = f"{full_path}/{name_matches[-1]}"
        return full_path
    if name_matches:
        return base_url.rstrip("/") + "/" + "/".join(name_matches)
    return base_url


def build_sharepoint_dependency_trail(workspaces_input: str) -> list[dict]:
    """Varre os JSONs do Fabric Scanner API e monta a trilha:
    dashboard/relatório -> dataset -> tabela do dataset -> fonte SharePoint,
    com uma marcação de existência (`exists_check`) por linha:
      - "existe": a expressão Power Query resolveu uma URL/site concreto;
      - "nao_encontrado": a função SharePoint.* foi detectada mas sem URL
        resolvível, ou o relatório aponta para um dataset ausente do scan;
      - "desconhecido": não há evidência suficiente (fallback, não deveria
        ocorrer para linhas realmente emitidas por esta função).
    """
    json_files = _load_json_files(workspaces_input)
    rows: list[dict] = []

    for jf in json_files:
        data = _read_json(jf)
        if not data:
            continue

        datasource_map: dict[str, dict] = {}
        for ds_inst in data.get("datasourceInstances", []):
            did = ds_inst.get("datasourceId", "")
            conn = ds_inst.get("connectionDetails", {}) or {}
            datasource_map[did] = {
                "type": str(ds_inst.get("datasourceType", "")).lower(),
                "url": conn.get("url", "") or conn.get("sharePointSiteUrl", ""),
            }

        for ws in data.get("workspaces", []):
            ws_name = ws.get("name", ws.get("id", "unknown"))
            datasets_by_id: dict[str, dict] = {}

            for ds in ws.get("datasets", []):
                ds_id = str(ds.get("id", "")).lower()
                ds_name = ds.get("name", ds_id)
                datasets_by_id[ds_id] = ds

                for tbl in ds.get("tables", []):
                    tbl_name = tbl.get("name", "")
                    src_list = tbl.get("source", [])
                    expr = ""
                    if isinstance(src_list, list) and src_list:
                        expr = src_list[0].get("expression", "") or ""
                    elif isinstance(src_list, str):
                        expr = src_list
                    if not expr:
                        continue

                    for match in _SHAREPOINT_PATTERN.finditer(expr.replace("#(lf)", "\n")):
                        url = match.group(1)
                        rows.append({
                            "workspace": ws_name, "report_name": "", "dataset_name": ds_name,
                            "dataset_id": ds_id, "dataset_table": tbl_name,
                            "sharepoint_reference": url,
                            "sharepoint_full_path": _extract_sharepoint_full_path(expr, url) if url else "",
                            "chain_depth": 0,
                            "exists_check": "existe" if url else "nao_encontrado",
                            "validation_note": "Detectado via expressão Power Query (SharePoint.*).",
                        })

                # Também considera datasources declarados nos usages da tabela,
                # quando o tipo do datasource resolvido é SharePoint mas a expressão
                # não permitiu extrair a URL diretamente (ex.: parametrizada).
                for usage in tbl.get("datasourceUsages", []) if isinstance(tbl, dict) else []:
                    inst = datasource_map.get(usage.get("datasourceInstanceId", ""))
                    if inst and inst["type"] in _SHAREPOINT_DATASOURCE_TYPES:
                        already = any(
                            r["dataset_name"] == ds_name and r["dataset_table"] == tbl.get("name", "")
                            for r in rows
                        )
                        if not already:
                            rows.append({
                                "workspace": ws_name, "report_name": "", "dataset_name": ds_name,
                                "dataset_id": ds_id, "dataset_table": tbl.get("name", ""),
                                "sharepoint_reference": inst.get("url", ""),
                                "sharepoint_full_path": inst.get("url", ""),  # sem expressão M disponível p/ aprofundar
                                "chain_depth": 0,
                                "exists_check": "existe" if inst.get("url") else "nao_encontrado",
                                "validation_note": "Detectado via datasourceInstances (tipo SharePoint).",
                            })

            # Camada de relatório/dashboard (quando o Scanner API expõe "reports").
            for report in ws.get("reports", []):
                report_name = report.get("name", report.get("id", ""))
                dataset_id = str(report.get("datasetId", "")).lower()
                if not dataset_id:
                    continue
                matching_rows = [r for r in rows if r["dataset_id"] == dataset_id and r["workspace"] == ws_name]
                if matching_rows:
                    for base_row in matching_rows:
                        rows.append({
                            **{k: v for k, v in base_row.items() if k not in {"report_name", "chain_depth"}},
                            "report_name": report_name,
                            "chain_depth": base_row["chain_depth"] + 1,
                        })
                elif dataset_id not in datasets_by_id:
                    rows.append({
                        "workspace": ws_name, "report_name": report_name, "dataset_name": "",
                        "dataset_id": dataset_id, "dataset_table": "", "sharepoint_reference": "",
                        "sharepoint_full_path": "",
                        "chain_depth": 1, "exists_check": "nao_encontrado",
                        "validation_note": "Relatório referencia um dataset que não aparece no scan atual "
                                            "(possível dataset removido, movido ou fora do escopo exportado).",
                    })

    return rows


# ===========================================================================
# 4. ORQUESTRAÇÃO / PERSISTÊNCIA
# ===========================================================================

def _dependency_row_to_kwargs(row: dict) -> dict:
    kwargs = {}
    for pt_col, field in _DEPENDENCY_FIELD_MAP.items():
        if field is None:
            continue
        value = row.get(pt_col, "")
        kwargs[field] = "" if value is None else str(value)
    if "_is_transitive" in row:
        kwargs["is_transitive"] = bool(row.get("_is_transitive", False))
    else:
        # Ao reler um Excel já exportado (sem a flag interna), reconhece a
        # relação transitiva pela tag gravada em OBSERVACAO por
        # expand_transitive_lineage().
        kwargs["is_transitive"] = "[TRANSITIVA]" in str(row.get("OBSERVACAO", ""))
    return kwargs


def dependency_rows_from_dataframe(df: pd.DataFrame) -> list[dict]:
    """Converte um DataFrame no formato exato da aba `Linhagem Tabelas`
    (mesmas 18+2 colunas em português exportadas por `export_lineage_excel`)
    para os dicts consumidos por `dlctl.core.lineage_graph.build_dependency_graph`.

    Usado pela página de dashboard "Grafo Isolado" para carregar o grafo
    diretamente de um Excel `lineage_tables_*.xlsx` (gerado por
    `dlctl lineage generate` ou enviado manualmente pelo usuário), sem
    depender de uma geração (batch) específica no `state.db`."""
    if df.empty:
        return []
    rows = df.fillna("").to_dict("records")
    return [_dependency_row_to_kwargs(row) for row in rows]


def _catalog_row_to_kwargs(row: dict) -> dict:
    return {field: ("" if row.get(pt_col) is None else str(row.get(pt_col, ""))) for pt_col, field in _CATALOG_FIELD_MAP.items()}


def export_lineage_excel(dependency_rows: list[dict], catalog_rows: list[dict], output_path: Path) -> Path:
    """Exporta as abas Linhagem Tabelas / Tabelas para um Excel simples
    (mesma estrutura de colunas do fabric-migrate-plan original)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lineage_df = pd.DataFrame(dependency_rows, columns=COLS_LINEAGE_TABLES) if dependency_rows else pd.DataFrame(columns=COLS_LINEAGE_TABLES)
    tabelas_df = pd.DataFrame(catalog_rows, columns=COLS_TABELAS) if catalog_rows else pd.DataFrame(columns=COLS_TABELAS)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        lineage_df.to_excel(writer, sheet_name="Linhagem Tabelas", index=False)
        tabelas_df.to_excel(writer, sheet_name="Tabelas", index=False)
    return output_path


LINEAGE_EXCEL_GLOB_PATTERNS = ("lineage_tables_*.xlsx", "fabric-migrate-plan_*.xlsx")


def find_latest_lineage_excel(profile: Profile) -> Optional[Path]:
    """Localiza o Excel de linhagem mais recente em `manifests/lineage/`
    (gerado por `dlctl lineage generate`), para a página de dashboard do
    Grafo Isolado carregar automaticamente sem exigir seleção manual de
    uma "geração/batch". Aceita tanto `lineage_tables_*.xlsx` quanto o
    formato legado `fabric-migrate-plan_*.xlsx` (mesma aba `Linhagem Tabelas`)."""
    lineage_dir = profile.paths.manifests_root / "lineage"
    if not lineage_dir.exists():
        return None
    candidates: list[Path] = []
    for pattern in LINEAGE_EXCEL_GLOB_PATTERNS:
        candidates.extend(lineage_dir.glob(pattern))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _resolve_input_path(path_str: str) -> str:
    """Resolve um caminho relativo informado pelo usuário (CLI ou dashboard)
    contra o diretório atual primeiro e, se não existir, contra a raiz do
    projeto -- evita que `input/Workspaces` "desapareça" silenciosamente só
    porque o processo do Streamlit/CLI foi iniciado de outra pasta."""
    if not path_str:
        return path_str
    p = Path(path_str)
    if p.is_absolute() or p.exists():
        return path_str
    candidate = PROJECT_ROOT / path_str
    return str(candidate) if candidate.exists() else path_str


def generate_lineage_artifacts(
    profile: Profile,
    lakehouse_dev_input: str = "input/lakehouse-dev",
    workspaces_input: Optional[str] = None,
    export_excel: bool = True,
) -> dict:
    """Ponto de entrada único da feature de Linhagem: parseia notebooks +
    (opcionalmente) JSONs do Fabric Scanner, persiste tudo em `state.py` sob
    um novo `LineageBatch` e (opcionalmente) exporta um Excel de
    conferência em `manifests/lineage/`."""
    lakehouse_dev_input = _resolve_input_path(lakehouse_dev_input)
    workspaces_input = _resolve_input_path(workspaces_input) if workspaces_input else workspaces_input
    batch_id = state_db.start_lineage_batch(
        profile, workspaces_input=workspaces_input or "", lakehouse_dev_input=lakehouse_dev_input,
    )
    try:
        processed = process_lakehouse_dev(lakehouse_dev_input)
        expanded = expand_transitive_lineage(processed["linhagem"])

        dependency_kwargs = [_dependency_row_to_kwargs(row) for row in expanded]
        catalog_kwargs = [_catalog_row_to_kwargs(row) for row in processed["tabelas"]]

        sharepoint_rows: list[dict] = []
        workspace_inventory_rows: list[dict] = []
        workspaces_input_not_found = bool(workspaces_input) and not Path(workspaces_input).exists()
        if workspaces_input and Path(workspaces_input).exists():
            sharepoint_rows = build_sharepoint_dependency_trail(workspaces_input)
            workspace_inventory_rows = build_workspace_inventory(workspaces_input)

        dep_count = state_db.save_lineage_dependencies(profile, batch_id, dependency_kwargs)
        cat_count = state_db.save_lineage_catalog(profile, batch_id, catalog_kwargs)
        sp_count = state_db.save_lineage_sharepoint(profile, batch_id, sharepoint_rows)
        wi_count = state_db.save_lineage_workspace_items(profile, batch_id, workspace_inventory_rows)

        excel_path = None
        fabric_lineage_full_path = None
        simplified_migration_path = None
        powerquery_detailed_path = None
        if export_excel:
            output_dir = profile.paths.manifests_root / "lineage"
            excel_path = export_lineage_excel(
                expanded, processed["tabelas"], output_dir / f"lineage_tables_{batch_id}.xlsx",
            )
            if workspaces_input and Path(workspaces_input).exists():
                # Demais artefatos do projeto de referência Skill-LineageFabric
                # (extrato bruto completo + simplified migration + powerquery detailed).
                from dlctl.generators.fabric_lineage_export import generate_all_fabric_lineage_formats
                extra_paths = generate_all_fabric_lineage_formats(workspaces_input, output_dir, batch_id)
                fabric_lineage_full_path = extra_paths["fabric_lineage_full_path"]
                simplified_migration_path = extra_paths["simplified_migration_path"]
                powerquery_detailed_path = extra_paths["powerquery_detailed_path"]

        summary = (
            f"{dep_count} dependência(s), {cat_count} tabela(s) de catálogo, "
            f"{sp_count} trilha(s) SharePoint, {wi_count} item(ns) no inventário de workspaces."
        )
        state_db.finish_lineage_batch(
            profile, batch_id, status="success", summary=summary,
            dependency_rows=dep_count, catalog_rows=cat_count, sharepoint_rows=sp_count,
            workspace_item_rows=wi_count,
        )
        return {
            "batch_id": batch_id, "dependency_rows": dep_count, "catalog_rows": cat_count,
            "sharepoint_rows": sp_count, "workspace_item_rows": wi_count,
            "excel_path": str(excel_path) if excel_path else None,
            "fabric_lineage_full_path": fabric_lineage_full_path,
            "simplified_migration_path": simplified_migration_path,
            "powerquery_detailed_path": powerquery_detailed_path,
            "workspaces_input_not_found": workspaces_input_not_found,
        }
    except Exception as exc:
        state_db.finish_lineage_batch(profile, batch_id, status="failed", summary=str(exc))
        raise LineageGeneratorError(f"Falha ao gerar artefatos de linhagem: {exc}") from exc
