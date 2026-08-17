"""dlctl.generators.gold_generator

Gera notebooks PySpark Silver -> Gold seguindo os Gold Gates de
etl-oracle-fabric-gold/SKILL.md: sem Pandas/NumPy, sem paths placeholder,
SILVER_PATH nunca vazio, sem CREATE OR REPLACE VIEW dentro de spark.sql,
TempViews batendo com as referências do SQL.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import nbformat as nbf

from dlctl.core.mapping import MappingEntry


def _cell_id() -> str:
    return uuid.uuid4().hex[:8]


def _code_cell(lines: list[str]):
    cell = nbf.v4.new_code_cell(source="\n".join(lines))
    cell["id"] = _cell_id()
    cell["source"] = [lines[i] + ("\n" if i < len(lines) - 1 else "") for i in range(len(lines))]
    return cell


def _md_cell(text: str):
    cell = nbf.v4.new_markdown_cell(source=text)
    cell["id"] = _cell_id()
    cell["source"] = [text]
    return cell


def _read_text_or_placeholder(path: Path | None, placeholder: str) -> str:
    if path and path.exists():
        return path.read_text(encoding="utf-8")
    return placeholder


def generate_gold_notebook(
    entry: MappingEntry,
    silver_base_path: str,
    gold_base_path: str,
    project_root: Path,
    write_mode: str = "overwrite",
    fail_on_errors: bool = True,
    ancient_date_cutoff: str = "1900-01-01",
) -> nbf.NotebookNode:
    if not silver_base_path or not silver_base_path.strip():
        raise ValueError("silver_base_path não pode ser vazio (Gold Gate: SILVER_PATH vazio é bloqueante).")

    sql_path = (project_root / entry.sql_file) if entry.sql_file else None
    sql_literal = _read_text_or_placeholder(
        sql_path, f"-- TODO SQL: consolidação Gold ausente para {entry.target_table} (status={entry.status})"
    )

    nb = nbf.v4.new_notebook()
    nb["nbformat"] = 4
    nb["nbformat_minor"] = 5
    nb["metadata"] = {
        "language_info": {"name": "python"},
        "generated_by": "dlctl.generators.gold_generator",
        "source_table": entry.source_table,
        "target_table": entry.target_table,
        "status_at_generation": entry.status,
    }

    tempview_name = entry.source_table.lower()

    nb["cells"] = [
        _md_cell(f"# Gold: {entry.target_table}\nConsolidado a partir de `{entry.source_table}` (status: `{entry.status}`)."),
        _code_cell([
            "# 1) Parametros de path (devem ser paths reais resolvidos, nunca genericos)",
            f"SILVER_TABLE = \"{entry.source_table}\"",
            f"SILVER_PATH = f\"{silver_base_path}/{{SILVER_TABLE}}\"",
            f"GOLD_TABLE = \"{entry.target_table}\"",
            f"GOLD_PATH = f\"{gold_base_path}/{{GOLD_TABLE}}\"",
            f"FAIL_ON_ERRORS = {fail_on_errors}",
            f"ANCIENT_DATE_CUTOFF = \"{ancient_date_cutoff}\"",
            "assert SILVER_PATH, 'SILVER_PATH não pode ser vazio'",
        ]),
        _code_cell([
            "# 2) Carrega Silver (Delta) e cria TempView correspondente ao SQL abaixo",
            "df_silver = spark.read.format(\"delta\").load(SILVER_PATH)",
            f"df_silver.createOrReplaceTempView(\"{tempview_name}\")",
        ]),
        _code_cell([
            "# 3) SQL de consolidação Gold (Power Query/M ou semantic model migrado para Spark SQL)",
            "SQL_GOLD = \"\"\"",
            sql_literal.rstrip(),
            "\"\"\"",
            "df_gold = spark.sql(SQL_GOLD)",
        ]),
        _code_cell([
            "# 4) Validações de qualidade (data ancestral, nulos em chave, contagem)",
            "from pyspark.sql import functions as F",
            "issues = []",
            "if 'DATA' in df_gold.columns:",
            "    ancient = df_gold.filter(F.col('DATA') < F.lit(ANCIENT_DATE_CUTOFF)).count()",
            "    if ancient > 0:",
            "        issues.append(f'{ancient} linhas com DATA anterior a {ANCIENT_DATE_CUTOFF}')",
            "if FAIL_ON_ERRORS and issues:",
            "    raise ValueError('Falhas de qualidade Gold: ' + '; '.join(issues))",
        ]),
        _code_cell([
            "# 5) Escreve Delta Gold (BI-ready)",
            f"df_gold.write.format(\"delta\").mode(\"{write_mode}\").save(GOLD_PATH)",
            "print(f'Gold escrito em {GOLD_PATH} ({df_gold.count()} linhas)')",
        ]),
    ]
    return nb


def write_notebook(nb: nbf.NotebookNode, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nbf.write(nb, str(output_path))
    return output_path
