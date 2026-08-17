"""dlctl.core.gates

Replica o "Central Write Gate" descrito em fabric-full-agent/SKILL.md:
toda chamada mutante (create/update/delete/execute) é recusada com
SecurityError a menos que authorize_write()/authorize_execute() tenha
rodado antes, o que por sua vez reverifica microsoft.allow_write no
profile ativo E a flag de confirmação explícita passada no comando atual.

Nenhum caminho de código deste projeto muta um recurso (Fabric ou local)
sem os dois: profile com allow_write=true E --confirm-* explícito.

Toda recusa é logada em ActivityLog (level=BLOCKED, source=gates.<método>)
ANTES de levantar a exceção — isso alimenta o detector 'gate-friction' do
motor de retro (core/retro.py): recusas repetidas não significam que o gate
está errado (ele está funcionando), significam que a documentação/mensagem
de precondição precisa ficar mais visível. Nunca é uma proposta para
enfraquecer o gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from dlctl.config import Profile
from dlctl.core.state import log_activity


class SecurityError(RuntimeError):
    """Levantado quando uma operação mutante não está devidamente autorizada."""


@dataclass
class GateContext:
    profile: Profile
    run_id: str = ""

    def _refuse(self, method: str, message: str) -> None:
        log_activity(self.profile, message, level="BLOCKED", source=f"gates.{method}", run_id=self.run_id)
        raise SecurityError(message)

    def _grant(self, method: str) -> None:
        log_activity(self.profile, f"{method} concedido", source=f"gates.{method}", run_id=self.run_id)

    def authorize_write(self, confirm_write: bool, confirm_production: bool = False,
                         item_ids: Optional[list] = None, tables: Optional[list] = None, owner: str = "dlctl-agent") -> None:
        if not self.profile.microsoft.allow_write:
            self._refuse(
                "authorize_write",
                f"Profile '{self.profile.name}' está com microsoft.allow_write=false. "
                "Habilite explicitamente (config/profiles.yaml ou DLCTL_ALLOW_WRITE=true) antes de escrever.",
            )
        if not confirm_write:
            self._refuse("authorize_write", "Escrita recusada: passe --confirm-write explicitamente neste comando.")
        if self.profile.environment.upper() == "PRD" and not confirm_production:
            self._refuse("authorize_write", "Ambiente PRD requer --confirm-production além de --confirm-write.")
        if item_ids or tables:
            from dlctl.core.state import has_conflicting_lease
            conflict = has_conflicting_lease(self.profile, item_ids or [], tables or [], owner)
            if conflict:
                self._refuse(
                    "authorize_write",
                    f"Escrita recusada: lease ativa '{conflict}' de outro agente cobre um dos itens/tabelas "
                    "solicitados (Incid. 1 P0 'sem lock entre agentes'). Aguarde a liberação ou peça a lease.",
                )
        self._grant("authorize_write")

    def authorize_execute(self, confirm_execute: bool) -> None:
        if not confirm_execute:
            self._refuse(
                "authorize_execute",
                "Execução recusada: notebooks/pipelines/dataflows/copy jobs exigem "
                "--confirm-execute explícito na chamada atual (autorização do turno).",
            )
        self._grant("authorize_execute")

    def authorize_delete(self, confirm_delete: bool) -> None:
        if not confirm_delete:
            self._refuse("authorize_delete", "Delete recusado: passe --confirm-delete explicitamente.")
        self._grant("authorize_delete")

    def authorize_move(self, allow_move_existing: bool, confirm_move: bool) -> None:
        if not allow_move_existing:
            self._refuse("authorize_move", "Mover item existente requer safety.allow_move_existing=true no manifest.")
        if not confirm_move:
            self._refuse("authorize_move", "Mover item existente requer --confirm-move explícito.")
        self._grant("authorize_move")

    def authorize_publish(self, confirm_publish: bool) -> None:
        if not confirm_publish:
            self._refuse("authorize_publish", "Publicação de Environment requer --confirm-publish (não substitua por --confirm-execute).")
        self._grant("authorize_publish")

    def authorize_rollback(self, confirm_rollback: bool) -> None:
        if not confirm_rollback:
            self._refuse("authorize_rollback", "Rollback requer --confirm-rollback explícito.")
        self._grant("authorize_rollback")

    def authorize_security_change(self, confirm_security_change: bool) -> None:
        if not confirm_security_change:
            self._refuse("authorize_security_change", "Mudança de permissões/RBAC/RLS/masking requer --confirm-security-change.")
        self._grant("authorize_security_change")

    def authorize_git_commit(self, confirm_git_commit: bool) -> None:
        if not confirm_git_commit:
            self._refuse("authorize_git_commit", "Git commit requer --confirm-git-commit explícito.")
        self._grant("authorize_git_commit")

    def authorize_git_update(self, confirm_git_update: bool) -> None:
        if not confirm_git_update:
            self._refuse("authorize_git_update", "Git update-from-git requer --confirm-git-update explícito.")
        self._grant("authorize_git_update")

    def authorize_data_access(self, confirm_data_access: bool) -> None:
        if not confirm_data_access:
            self._refuse("authorize_data_access", "Leitura de linhas/dados requer --confirm-data-access explícito.")
        self._grant("authorize_data_access")
