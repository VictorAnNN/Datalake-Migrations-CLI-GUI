"""Fixtures compartilhadas de teste: profile isolado em diretório temporário."""
from __future__ import annotations

from pathlib import Path

import pytest

from dlctl.config import MicrosoftConfig, OracleConfig, PathsConfig, Profile, load_profile

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def tmp_profile(tmp_path, monkeypatch):
    """Cria um profile de teste com paths isolados em tmp_path, copiando os
    mappings de exemplo do repositório."""
    load_profile.cache_clear()
    monkeypatch.setenv("DLCTL_PROFILE", "ms_client_constellation")
    monkeypatch.setenv("DLCTL_ALLOW_WRITE", "false")

    profile = load_profile("ms_client_constellation")
    # redireciona paths para tmp_path preservando os mappings de exemplo do repo
    profile.paths.state_root = tmp_path / "state"
    profile.paths.evidence_root = tmp_path / "state" / "evidence"
    profile.paths.mappings_root = PROJECT_ROOT / "mappings"
    profile.paths.notebooks_silver_root = tmp_path / "notebooks" / "silver"
    profile.paths.notebooks_gold_root = tmp_path / "notebooks" / "gold"
    for p in [profile.paths.state_root, profile.paths.evidence_root,
              profile.paths.notebooks_silver_root, profile.paths.notebooks_gold_root]:
        p.mkdir(parents=True, exist_ok=True)
    yield profile
    load_profile.cache_clear()
