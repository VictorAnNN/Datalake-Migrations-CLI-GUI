"""Testes offline do motor de retro (dlctl.core.retro): normalização de erro,
detecção de cada categoria de sinal, geração de relatório e workflow
aprovar/rejeitar. Nenhum destes testes faz qualquer chamada de rede."""
from __future__ import annotations

from dlctl.core.gates import GateContext
from dlctl.core.retro import analyze, approve_proposal, normalize_error_shape, reject_proposal, render_markdown_report
from dlctl.core.state import get_session, list_retro_proposals, log_activity, log_command_invocation


def test_normalize_error_shape_strips_ids_and_numbers():
    msg = "HTTP 429 retry 2/4 after 8s for item 'abc123'"
    shape = normalize_error_shape(msg)
    assert "429" not in shape
    assert "2/4" not in shape or "<n>/<n>" in shape
    assert "<n>" in shape


def test_normalize_error_shape_strips_uuid():
    msg = "item 123e4567-e89b-12d3-a456-426614174000 not found"
    shape = normalize_error_shape(msg)
    assert "<uuid>" in shape
    assert "123e4567" not in shape


def test_analyze_detects_gate_friction_and_permission_gap(tmp_profile):
    tmp_profile.microsoft.allow_write = False
    gate = GateContext(profile=tmp_profile)
    for _ in range(4):
        try:
            gate.authorize_write(confirm_write=True)
        except Exception:
            pass

    summary = analyze(tmp_profile, window_days=365, min_count=3)
    proposals = list_retro_proposals(tmp_profile)
    categories = {p["category"] for p in proposals}
    assert "gate-friction" in categories
    assert "permission-gap" in categories
    gate_proposal = next(p for p in proposals if p["category"] == "gate-friction")
    assert gate_proposal["gate_change"] is True
    assert gate_proposal["risk"] == "gate-change"
    assert gate_proposal["count"] == 4


def test_analyze_does_not_flag_gate_friction_below_min_count(tmp_profile):
    tmp_profile.microsoft.allow_write = False
    gate = GateContext(profile=tmp_profile)
    for _ in range(2):  # abaixo do min_count=3
        try:
            gate.authorize_write(confirm_write=True)
        except Exception:
            pass

    analyze(tmp_profile, window_days=365, min_count=3)
    proposals = list_retro_proposals(tmp_profile)
    assert not any(p["category"] == "gate-friction" for p in proposals)


def test_analyze_detects_throttling(tmp_profile):
    for _ in range(4):
        log_activity(tmp_profile, "HTTP 429 retry 1/4 after 1s", level="WARN", source="fabric_api.retry")

    analyze(tmp_profile, window_days=365, min_count=3)
    proposals = list_retro_proposals(tmp_profile, category="throttling")
    assert len(proposals) == 1
    assert proposals[0]["count"] == 4


def test_analyze_detects_prefer_resolver(tmp_profile):
    for _ in range(5):
        log_activity(tmp_profile, "live lookup: Notebook/nb_x", source="fabric_api.cache")
    log_activity(tmp_profile, "cache hit: Notebook/nb_x", source="fabric_api.cache")

    analyze(tmp_profile, window_days=365, min_count=3)
    proposals = list_retro_proposals(tmp_profile)
    assert any(p["category"] == "prefer-resolver" for p in proposals)


def test_analyze_detects_skill_featured_unused(tmp_profile):
    summary = analyze(tmp_profile, window_days=365, min_count=1)
    proposals = list_retro_proposals(tmp_profile, category="skill-featured-unused")
    assert len(proposals) == 1
    assert proposals[0]["count"] > 0


def test_command_invocation_reduces_unused_count(tmp_profile):
    baseline = analyze(tmp_profile, window_days=365, min_count=1)
    unused_before = list_retro_proposals(tmp_profile, category="skill-featured-unused")[0]["count"]

    log_command_invocation(tmp_profile, "inventory silver")
    analyze(tmp_profile, window_days=365, min_count=1)
    unused_after = list_retro_proposals(tmp_profile, category="skill-featured-unused")[0]["count"]

    assert unused_after == unused_before - 1


def test_approve_and_reject_workflow(tmp_profile):
    tmp_profile.microsoft.allow_write = False
    gate = GateContext(profile=tmp_profile)
    for _ in range(3):
        try:
            gate.authorize_write(confirm_write=True)
        except Exception:
            pass
    analyze(tmp_profile, window_days=365, min_count=3)
    proposals = list_retro_proposals(tmp_profile, category="gate-friction")
    assert proposals
    key = proposals[0]["proposal_key"]

    assert approve_proposal(tmp_profile, key) is True
    approved = list_retro_proposals(tmp_profile, status="approved")
    assert any(p["proposal_key"] == key for p in approved)

    assert reject_proposal(tmp_profile, key) is True
    rejected = list_retro_proposals(tmp_profile, status="rejected")
    assert any(p["proposal_key"] == key for p in rejected)

    assert approve_proposal(tmp_profile, "does-not-exist") is False


def test_reanalyze_does_not_override_human_decision(tmp_profile):
    tmp_profile.microsoft.allow_write = False
    gate = GateContext(profile=tmp_profile)
    for _ in range(3):
        try:
            gate.authorize_write(confirm_write=True)
        except Exception:
            pass
    analyze(tmp_profile, window_days=365, min_count=3)
    proposals = list_retro_proposals(tmp_profile, category="gate-friction")
    key = proposals[0]["proposal_key"]
    approve_proposal(tmp_profile, key)

    # roda de novo (mais refusals) -- não deve reverter a aprovação humana
    for _ in range(2):
        try:
            gate.authorize_write(confirm_write=True)
        except Exception:
            pass
    analyze(tmp_profile, window_days=365, min_count=3)
    proposals_after = list_retro_proposals(tmp_profile, category="gate-friction")
    updated = next(p for p in proposals_after if p["proposal_key"] == key)
    assert updated["status"] == "approved"
    assert updated["count"] == 5  # contagem atualizada


def test_render_markdown_report_contains_gate_change_badge(tmp_profile):
    tmp_profile.microsoft.allow_write = False
    gate = GateContext(profile=tmp_profile)
    for _ in range(3):
        try:
            gate.authorize_write(confirm_write=True)
        except Exception:
            pass
    summary = analyze(tmp_profile, window_days=365, min_count=3)
    report = render_markdown_report(tmp_profile, summary)
    assert "# Improvement Proposals (retro)" in report
    assert "GATE-CHANGE" in report
    assert "Stage B: manual_required" in report
