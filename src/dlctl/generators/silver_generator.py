"""dlctl.generators.silver_generator

Gera notebooks PySpark Bronze -> Silver seguindo o Notebook Contract de
etl-oracle-fabric/SKILL.md:

- carrega Bronze como Parquet;
- cria TempView antes do spark.sql;
- embute o SQL legado como literal e roda spark.sql(SQL_TRANSFORMACAO);
- embute o contrato de schema (.tab) antes da escrita;
- evita Pandas/NumPy/Excel/leitura de arquivo local em runtime;
- grava saída em Delta;
- usa nbformat 4.5 com cell id e source como lista de linhas.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import nbformat as nbf

from dlctl.core.mapping import MappingEntry


def _cell_id() -> str:
    return uuid.uuid4().hex[:8]


def _code_cell(source_lines: list[str]):
    cell = nbf.v4.new_code_cell(source="\n".join(source_lines))
    cell["id"] = _cell_id()
    cell["source"] = [line + "\n" for line in source_lines[:-1]] + [source_lines[-1]] if source_lines else []
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


def generate_silver_notebook(
    entry: MappingEntry,
    bronze_base_path: str,
    silver_base_path: str,
    project_root: Path,
    write_mode: str = "overwrite",
) -> nbf.NotebookNode:
    """Gera um notebook Silver a partir de uma MappingEntry. Não grava em disco
    (chame nbformat.write separadamente) — isso corresponde ao modo dry (sem --write)
    do CLI original."""

    sql_path = (project_root / entry.sql_file) if entry.sql_file else None
    schema_path = (project_root / entry.schema_file) if entry.schema_file else None

    sql_literal = _read_text_or_placeholder(
        sql_path, f"-- TODO: SQL legado ausente para {entry.target_table} (status={entry.status})"
    )
    schema_contract = _read_text_or_placeholder(
        schema_path, f"# TODO: contrato .tab ausente para {entry.target_table}"
    )

    nb = nbf.v4.new_notebook()
    nb["nbformat"] = 4
    nb["nbformat_minor"] = 5
    nb["metadata"] = {
        "language_info": {"name": "python"},
        "generated_by": "dlctl.generators.silver_generator",
        "source_table": entry.source_table,
        "target_table": entry.target_table,
        "status_at_generation": entry.status,
    }

    nb["cells"] = [
        _md_cell(f"# Silver: {entry.target_table}\nGerado a partir de `{entry.source_table}` (status: `{entry.status}`)."),
        _code_cell([
            "# 1) Carrega Bronze como Parquet (nunca Pandas/NumPy)",
            f"BRONZE_TABLE = \"{entry.source_table}\"",
            f"BRONZE_PATH = f\"{bronze_base_path}/{{BRONZE_TABLE}}\"",
            "df_bronze = spark.read.format(\"parquet\").load(BRONZE_PATH)",
        ]),
        _code_cell([
            "# 2) Cria TempView ANTES de qualquer spark.sql",
            f"df_bronze.createOrReplaceTempView(\"{entry.source_table.lower()}\")",
        ]),
        _code_cell([
            "# 3) SQL legado (OTBI/Data Model) adaptado para Spark SQL, embutido como literal",
            "SQL_TRANSFORMACAO = \"\"\"",
            sql_literal.rstrip(),
            "\"\"\"",
            "df_silver = spark.sql(SQL_TRANSFORMACAO)",
        ]),
        _code_cell([
            "# 4) Contrato de schema (.tab) embutido antes da escrita",
            "SCHEMA_CONTRACT = \"\"\"",
            schema_contract.rstrip(),
            "\"\"\"",
            "# validação simples: todas as colunas do contrato devem existir no df_silver",
            "expected_cols = [l.split(':')[0].strip() for l in SCHEMA_CONTRACT.splitlines() if ':' in l]",
            "missing = [c for c in expected_cols if c and c not in df_silver.columns]",
            "assert not missing, f'Colunas ausentes no Silver: {missing}'",
        ]),
        _code_cell([
            "# 5) Escreve Delta Silver",
            f"SILVER_TABLE = \"{entry.target_table}\"",
            f"SILVER_PATH = f\"{silver_base_path}/{{SILVER_TABLE}}\"",
            f"df_silver.write.format(\"delta\").mode(\"{write_mode}\").save(SILVER_PATH)",
            "print(f'Silver escrito em {SILVER_PATH} ({df_silver.count()} linhas)')",
        ]),
    ]
    return nb


def write_notebook(nb: nbf.NotebookNode, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nbf.write(nb, str(output_path))
    return output_path
