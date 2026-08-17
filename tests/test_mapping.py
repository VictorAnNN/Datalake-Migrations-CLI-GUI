"""Testes do registry de mapeamento Bronze/Silver/Gold (dlctl.core.mapping)."""
from __future__ import annotations

from dlctl.core.mapping import build_inventory, load_mapping, reconcile_scope


def test_load_mapping_reads_example_csv(tmp_profile):
    entries = load_mapping(tmp_profile, layer="bronze_to_silver", domain="ORDER_TRACKING")
    assert len(entries) > 0
    assert all(e.domain == "ORDER_TRACKING" for e in entries)


def test_build_inventory_counts_statuses(tmp_profile):
    inv = build_inventory(tmp_profile, layer="bronze_to_silver", domain="ORDER_TRACKING")
    assert inv["total"] == len(inv["entries"])
    assert inv["go_count"] + inv["blocked_count"] == inv["total"]


def test_reconcile_scope_blocks_manual_review_and_missing_sql(tmp_profile):
    result = reconcile_scope(tmp_profile, layer="bronze_to_silver", domain="ORDER_TRACKING")
    blocked_reasons = {b["reason"] for b in result["blocked"]}
    assert "manual_review" in blocked_reasons
    assert "missing_sql" in blocked_reasons
    assert result["verdict"] in {"partial_go", "no_go"}


def test_reconcile_scope_restricts_to_allowed_source_tables(tmp_profile):
    result = reconcile_scope(
        tmp_profile, layer="bronze_to_silver", domain="ORDER_TRACKING",
        allowed_source_tables={"BRZ_PO_HEADERS_ALL"},
    )
    reasons = [b["reason"] for b in result["blocked"]]
    assert any("fora do escopo" in r for r in reasons)
