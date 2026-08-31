"""Gera notebooks Bronze -> Silver no contrato canônico Constellation."""
from __future__ import annotations

import json
from pathlib import Path

import nbformat as nbf

from dlctl.core.mapping import MappingEntry


CELL_TITLES = [
    "C1_HEADER_METADATA", "C2_PARAMETERS", "C3_SPARK_SESSION",
    "C4_BRONZE_TEMPVIEWS", "C5_SPARK_SQL", "C6_SCHEMA_TAB",
    "C7_PK_QUARANTINE", "C8_DELTA_WRITE", "C9_OPTIMIZE", "C10_METRICS",
]


def _code_cell(source: str, cell_id: str):
    cell = nbf.v4.new_code_cell(source=source)
    cell["id"] = cell_id
    cell["source"] = source.rstrip().splitlines(keepends=True) + ["\n"]
    return cell


def _read_required(path: Path | None, artifact: str, table: str) -> str:
    if not path or not path.is_file():
        raise ValueError(f"{artifact} obrigatório não encontrado para {table}: {path}")
    return path.read_text(encoding="utf-8")


def generate_silver_notebook(
    entry: MappingEntry,
    bronze_base_path: str,
    silver_base_path: str,
    project_root: Path,
    write_mode: str = "overwrite",
) -> nbf.NotebookNode:
    if not bronze_base_path.strip() or not silver_base_path.strip():
        raise ValueError("bronze_base_path e silver_base_path são obrigatórios.")
    if write_mode != "overwrite":
        raise ValueError("O piloto suporta somente write_mode='overwrite'.")

    sql_path = (project_root / entry.sql_file) if entry.sql_file else None
    schema_path = (project_root / entry.schema_file) if entry.schema_file else None
    sql_literal = _read_required(sql_path, "SQL", entry.target_table)
    schema_contract = _read_required(schema_path, "contrato .tab", entry.target_table)

    source_table = entry.source_table
    target_table = entry.target_table
    source_view = source_table.lower()
    schema_literal = json.dumps(schema_contract, ensure_ascii=False)
    sql_string = json.dumps(sql_literal, ensure_ascii=False)

    cells = [
        _code_cell(
            f"""# {CELL_TITLES[0]}
# ETL: BRONZE -> SILVER
# Dominio: {entry.domain}
# Fonte: {source_table}
# Destino: {target_table}
# Status de geração: {entry.status}
# Gerado por: dlctl""",
            "c1-header-metadata",
        ),
        _code_cell(
            f"""# {CELL_TITLES[1]}
BRONZE_TABLE = {source_table!r}
SILVER_TABLE = {target_table!r}
BRONZE_PATH = f{(bronze_base_path.rstrip('/') + '/{BRONZE_TABLE}')!r}
SILVER_PATH = f{(silver_base_path.rstrip('/') + '/{SILVER_TABLE}')!r}
QUARANTINE_PATH = f{(silver_base_path.rstrip('/') + '/_quarantine/{SILVER_TABLE}')!r}
PRIMARY_KEYS = []
WRITE_MODE = {write_mode!r}""",
            "c2-parameters",
        ),
        _code_cell(
            f"""# {CELL_TITLES[2]}
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
import time

spark = SparkSession.builder.appName(f"ETL_{{SILVER_TABLE}}").getOrCreate()
spark.sparkContext.setLogLevel("WARN")
spark.conf.set("spark.sql.parquet.datetimeRebaseModeInWrite", "CORRECTED")
spark.conf.set("spark.sql.parquet.int96RebaseModeInWrite", "CORRECTED")
inicio_pipeline = time.time()""",
            "c3-spark-session",
        ),
        _code_cell(
            f"""# {CELL_TITLES[3]}
df_bronze = spark.read.format("parquet").load(BRONZE_PATH)
df_bronze.createOrReplaceTempView({source_view!r})
source_count = df_bronze.count()""",
            "c4-bronze-tempviews",
        ),
        _code_cell(
            f"""# {CELL_TITLES[4]}
SQL_TRANSFORMACAO = {sql_string}
df_silver_raw = spark.sql(SQL_TRANSFORMACAO)""",
            "c5-spark-sql",
        ),
        _code_cell(
            f"""# {CELL_TITLES[5]}
SCHEMA_CONTRACT = {schema_literal}
expected_cols = [line.split(":", 1)[0].strip() for line in SCHEMA_CONTRACT.splitlines() if ":" in line]
missing_cols = [column for column in expected_cols if column and column not in df_silver_raw.columns]
if missing_cols:
    raise ValueError(f"Colunas ausentes no Silver: {{missing_cols}}")
df_silver_conformado = df_silver_raw""",
            "c6-schema-tab",
        ),
        _code_cell(
            f"""# {CELL_TITLES[6]}
if PRIMARY_KEYS:
    null_condition = None
    for key in PRIMARY_KEYS:
        condition = F.col(key).isNull()
        null_condition = condition if null_condition is None else null_condition | condition
    df_quarentena = df_silver_conformado.filter(null_condition)
    df_silver_final = df_silver_conformado.filter(~null_condition)
    quarantine_count = df_quarentena.count()
    if quarantine_count:
        df_quarentena.write.format("delta").mode("append").save(QUARANTINE_PATH)
else:
    df_silver_final = df_silver_conformado
    quarantine_count = 0""",
            "c7-pk-quarantine",
        ),
        _code_cell(
            f"""# {CELL_TITLES[7]}
(
    df_silver_final.write
    .format("delta")
    .mode(WRITE_MODE)
    .option("overwriteSchema", "true")
    .save(SILVER_PATH)
)""",
            "c8-delta-write",
        ),
        _code_cell(
            f"""# {CELL_TITLES[8]}
try:
    spark.sql(f"OPTIMIZE delta.`{{SILVER_PATH}}`")
except Exception as exc:
    print(f"[WARN] OPTIMIZE não executado: {{type(exc).__name__}}")""",
            "c9-optimize",
        ),
        _code_cell(
            f"""# {CELL_TITLES[9]}
target_count = df_silver_final.count()
elapsed_seconds = round(time.time() - inicio_pipeline, 2)
print(
    "[METRICS] "
    f"table={{SILVER_TABLE}} source_count={{source_count}} target_count={{target_count}} "
    f"quarantine_count={{quarantine_count}} elapsed_seconds={{elapsed_seconds}}"
)""",
            "c10-metrics",
        ),
    ]

    nb = nbf.v4.new_notebook(cells=cells)
    nb["nbformat"] = 4
    nb["nbformat_minor"] = 5
    nb["metadata"] = {
        "kernelspec": {"display_name": "PySpark", "language": "python", "name": "synapse_pyspark"},
        "language_info": {"name": "python"},
        "generated_by": "dlctl.generators.silver_generator",
        "source_table": source_table,
        "target_table": target_table,
        "status_at_generation": entry.status,
    }
    return nb


def write_notebook(nb: nbf.NotebookNode, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nbf.write(nb, str(output_path))
    return output_path
