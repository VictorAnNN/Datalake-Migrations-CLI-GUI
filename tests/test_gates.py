"""Testes do Central Write Gate (dlctl.core.gates)."""
from __future__ import annotations

import pytest

from dlctl.config import PERMISSION_SCOPE_CONTRIBUTOR, PERMISSION_SCOPE_READ_ONLY
from dlctl.core.gates import GateContext, SecurityError


def test_write_blocked_when_profile_disallows(tmp_profile):
    tmp_profile.microsoft.allow_write = False
    tmp_profile.microsoft.permission_scope = PERMISSION_SCOPE_CONTRIBUTOR
    gate = GateContext(profile=tmp_profile)
    with pytest.raises(SecurityError, match="allow_write=false"):
        gate.authorize_write(confirm_write=True)


def test_write_blocked_without_confirm_flag(tmp_profile):
    tmp_profile.microsoft.allow_write = True
    tmp_profile.microsoft.permission_scope = PERMISSION_SCOPE_CONTRIBUTOR
    gate = GateContext(profile=tmp_profile)
    with pytest.raises(SecurityError, match="confirm-write"):
        gate.authorize_write(confirm_write=False)


def test_write_allowed_with_both_conditions(tmp_profile):
    tmp_profile.microsoft.allow_write = True
    tmp_profile.microsoft.permission_scope = PERMISSION_SCOPE_CONTRIBUTOR
    gate = GateContext(profile=tmp_profile)
    gate.authorize_write(confirm_write=True)  # não deve levantar


def test_prd_requires_confirm_production(tmp_profile):
    tmp_profile.microsoft.allow_write = True
    tmp_profile.microsoft.permission_scope = PERMISSION_SCOPE_CONTRIBUTOR
    tmp_profile.environment = "PRD"
    gate = GateContext(profile=tmp_profile)
    with pytest.raises(SecurityError, match="PRD"):
        gate.authorize_write(confirm_write=True, confirm_production=False)
    gate.authorize_write(confirm_write=True, confirm_production=True)  # não deve levantar


def test_read_only_blocks_write(tmp_profile):
    tmp_profile.microsoft.allow_write = True
    tmp_profile.microsoft.permission_scope = PERMISSION_SCOPE_READ_ONLY
    gate = GateContext(profile=tmp_profile)
    with pytest.raises(SecurityError, match="read_only"):
        gate.authorize_write(confirm_write=True)


def test_read_only_blocks_execute(tmp_profile):
    tmp_profile.microsoft.permission_scope = PERMISSION_SCOPE_READ_ONLY
    gate = GateContext(profile=tmp_profile)
    with pytest.raises(SecurityError, match="read_only"):
        gate.authorize_execute(confirm_execute=True)


def test_contributor_allows_execute(tmp_profile):
    tmp_profile.microsoft.permission_scope = PERMISSION_SCOPE_CONTRIBUTOR
    gate = GateContext(profile=tmp_profile)
    gate.authorize_execute(confirm_execute=True)  # não deve levantar


def test_execute_requires_confirm_execute(tmp_profile):
    tmp_profile.microsoft.permission_scope = PERMISSION_SCOPE_CONTRIBUTOR
    gate = GateContext(profile=tmp_profile)
    with pytest.raises(SecurityError, match="confirm-execute"):
        gate.authorize_execute(confirm_execute=False)
    gate.authorize_execute(confirm_execute=True)


def test_delete_requires_confirm_delete(tmp_profile):
    tmp_profile.microsoft.permission_scope = PERMISSION_SCOPE_CONTRIBUTOR
    gate = GateContext(profile=tmp_profile)
    with pytest.raises(SecurityError):
        gate.authorize_delete(confirm_delete=False)
    gate.authorize_delete(confirm_delete=True)


def test_move_requires_manifest_flag_and_confirm(tmp_profile):
    tmp_profile.microsoft.permission_scope = PERMISSION_SCOPE_CONTRIBUTOR
    gate = GateContext(profile=tmp_profile)
    with pytest.raises(SecurityError):
        gate.authorize_move(allow_move_existing=False, confirm_move=True)
    with pytest.raises(SecurityError):
        gate.authorize_move(allow_move_existing=True, confirm_move=False)
    gate.authorize_move(allow_move_existing=True, confirm_move=True)
