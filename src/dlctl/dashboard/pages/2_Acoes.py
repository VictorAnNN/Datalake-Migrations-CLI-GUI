"""Página de Ações do dashboard: aciona todos os fluxos (inventário, geração
de notebooks, manifests, execução, pipeline router) diretamente pelo
front-end, reaproveitando exatamente a mesma lógica core do CLI `dlctl` —
inclusive os mesmos gates de segurança (nada é aplicado sem os checkboxes de
confirmação equivalentes a --confirm-write/--confirm-execute).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[3]
PROJECT_ROOT = SRC_DIR.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import streamlit as st
import yaml

from dlctl.config import load_domains, load_profile
from dlctl.core import manifest as manifest_engine
from dlctl.core.execution import ExecutionManifest, apply_execution, dry_run_execution, plan_execution
from dlctl.core.gates import GateContext, SecurityError
from dlctl.core.mapping import build_inventory, load_mapping, reconcile_scope
from dlctl.core.pipeline import run_order_tracking
from dlctl.generators.gold_generator import generate_gold_notebook
from dlctl.generators.gold_generator import write_notebook as write_gold_notebook
from dlctl.generators.silver_generator import generate_silver_notebook
from dlctl.generators.silver_generator import write_notebook as write_silver_notebook
from dlctl.generators.validators import validate_gold_notebook, validate_silver_notebook

st.set_page_config(page_title="Ações — Constellation Migration Control", layout="wide", page_icon="🚀")
st.title("🚀 Ações — Acionar Fluxos")
st.caption(
    "Cada ação de escrita/execução exige os mesmos gates do CLI (allow_write no "
    "profile + confirmação explícita nesta página). Nada é aplicado silenciosamente."
)

profile_name = st.sidebar.text_input(
    "Profile",
    value="ms_client_constellation",
    key="act_profile_name",
    help="📄 Nome do profile em config/profiles.yaml. Usa o padrão se não tem múltiplos."
)
try:
    profile = load_profile(profile_name)
except Exception as exc:
    st.error(f"Não foi possível carregar o profile '{profile_name}': {exc}")
    st.stop()

st.sidebar.markdown(f"**Auth:** `az_cli`")
st.sidebar.markdown(f"**Escopo:** `{profile.microsoft.permission_scope}`")
if profile.microsoft.az_tenant_id:
    st.sidebar.markdown(f"**Tenant:** `{profile.microsoft.az_tenant_id}`")
st.sidebar.markdown(f"**allow_write:** `{profile.microsoft.allow_write}`")
if profile.microsoft.is_read_only:
    st.sidebar.warning("🔒 Escopo read_only: ações de escrita/execução no Fabric estão bloqueadas. Altere em Configuração > Microsoft Fabric.")
if not profile.microsoft.allow_write:
    st.sidebar.warning("Escrita desabilitada no profile. Ajuste em Configuração > Ambiente & Escrita.")

domains = load_domains()
domain = st.sidebar.selectbox(
    "Domínio",
    options=list(domains.keys()) or ["ORDER_TRACKING"],
    help="📊 Domínio de negócio (ex: ORDER_TRACKING, FINANCEIRO) que filtra dados e ações."
)

(
    tab_inventory,
    tab_gen_silver,
    tab_gen_gold,
    tab_manifest,
    tab_execute,
    tab_pipeline,
) = st.tabs(
    ["1. Inventário", "2. Gerar Silver", "3. Gerar Gold", "4. Manifest (Fabric)", "5. Execute (gated)", "6. Pipeline Router"]
)

# ==================== 1. Inventário ====================
with tab_inventory:
    st.subheader("Inventário e reconciliação de escopo")
    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "Rodar inventário Silver (Bronze->Silver)",
            type="primary",
            help="📋 Compara mapeamentos locais com schema Bronze/Silver. Mostra status GO/BLOQUEADO."
        ):
            inv = build_inventory(profile, layer="bronze_to_silver", domain=domain)
            st.session_state["inv_silver"] = inv
        if "inv_silver" in st.session_state:
            inv = st.session_state["inv_silver"]
            st.write(f"Total: {inv['total']} | GO: {inv['go_count']} | Bloqueados: {inv['blocked_count']}")
            st.dataframe(inv["entries"], use_container_width=True)
    with col2:
        if st.button(
            "Rodar inventário Gold (Silver->Gold)",
            type="primary",
            help="📋 Valida transformações Silver->Gold. Mostra status GO/BLOQUEADO."
        ):
            inv = build_inventory(profile, layer="silver_to_gold", domain=domain)
            st.session_state["inv_gold"] = inv
        if "inv_gold" in st.session_state:
            inv = st.session_state["inv_gold"]
            st.write(f"Total: {inv['total']} | GO: {inv['go_count']} | Bloqueados: {inv['blocked_count']}")
            st.dataframe(inv["entries"], use_container_width=True)

    st.divider()
    layer_pick = st.radio(
        "Camada para reconcile-scope",
        options=["bronze_to_silver", "silver_to_gold"],
        horizontal=True,
        help="🔍 Escolha qual camada verificar (validação de completude)"
    )
    if st.button(
        "Rodar reconcile-scope",
        help="🔍 Verifica se há missing/conflicting/orphaned items na camada"
    ):
        result = reconcile_scope(profile, layer=layer_pick, domain=domain)
        st.write(f"Veredito: **{result['verdict']}**")
        if result["blocked"]:
            st.dataframe(result["blocked"], use_container_width=True)
        if result["go_targets"]:
            st.success(f"GO: {', '.join(result['go_targets'])}")

# ==================== 2. Gerar Silver ====================
with tab_gen_silver:
    st.subheader("Gerar e validar notebook Silver (Bronze -> Silver)")
    entries = load_mapping(profile, layer="bronze_to_silver", domain=domain)
    go_entries = [e for e in entries if e.status in {"spark_ready", "needs_rewrite"}]
    if not go_entries:
        st.info("Nenhuma tabela GO disponível para este domínio.")
    else:
        table_pick = st.selectbox(
            "Tabela Silver (target_table)",
            options=[e.target_table for e in go_entries],
            help="📊 Tabela alvo Silver para gerar notebook"
        )
        bronze_base_path = st.text_input(
            "Bronze base path",
            value="Files/Bronze",
            key="silver_bronze_path",
            help="📁 Caminho base dos arquivos Bronze (ex: Files/Bronze)"
        )
        silver_base_path = st.text_input(
            "Silver base path",
            value="Tables/silver",
            key="silver_silver_path",
            help="📁 Caminho base da lakehouse Silver (ex: Tables/silver)"
        )
        write_to_disk = st.checkbox(
            "Gravar notebook em disco (--write)",
            value=True,
            key="silver_write",
            help="💾 Salva notebook gerado em disco (necessário para validação)"
        )
        if st.button(
            "Gerar notebook Silver",
            type="primary",
            help="🔧 Gera PySpark notebook para transformação Bronze->Silver"
        ):
            entry = next(e for e in go_entries if e.target_table == table_pick)
            nb = generate_silver_notebook(entry, bronze_base_path, silver_base_path, project_root=PROJECT_ROOT)
            out_path = profile.paths.notebooks_silver_root / f"{table_pick}.ipynb"
            write_silver_notebook(nb, out_path)  # necessário em disco para validar
            outcome = validate_silver_notebook(out_path)
            if outcome.ok:
                st.success(f"Notebook válido gerado em {out_path}")
            else:
                st.error("Notebook inválido (Notebook Contract):")
                for e in outcome.errors:
                    st.write(f"- {e}")
            for w in outcome.warnings:
                st.warning(w)
            if not write_to_disk:
                out_path.unlink(missing_ok=True)
                st.info("Notebook removido do disco (checkbox 'gravar' desmarcado; apenas preview).")

# ==================== 3. Gerar Gold ====================
with tab_gen_gold:
    st.subheader("Gerar e validar notebook Gold (Silver -> Gold)")
    gold_entries = load_mapping(profile, layer="silver_to_gold", domain=domain)
    go_gold = [e for e in gold_entries if e.status in {"spark_ready", "needs_rewrite"}]
    if not go_gold:
        st.info("Nenhuma tabela GO disponível para este domínio.")
    else:
        table_pick_g = st.selectbox(
            "Tabela Gold (target_table)",
            options=[e.target_table for e in go_gold],
            help="📊 Tabela alvo Gold para gerar notebook"
        )
        silver_base_path_g = st.text_input(
            "Silver base path",
            value="Tables/silver",
            key="gold_silver_path",
            help="📁 Caminho base da lakehouse Silver (origem)"
        )
        gold_base_path_g = st.text_input(
            "Gold base path",
            value="Tables/gold",
            key="gold_gold_path",
            help="📁 Caminho base da lakehouse Gold (destino)"
        )
        write_to_disk_g = st.checkbox(
            "Gravar notebook em disco (--write)",
            value=True,
            key="gold_write",
            help="💾 Salva notebook gerado em disco"
        )
        if st.button(
            "Gerar notebook Gold",
            type="primary",
            help="🔧 Gera PySpark notebook para transformação Silver->Gold"
        ):
            entry = next(e for e in go_gold if e.target_table == table_pick_g)
            try:
                nb = generate_gold_notebook(entry, silver_base_path_g, gold_base_path_g, project_root=PROJECT_ROOT)
                out_path = profile.paths.notebooks_gold_root / f"{table_pick_g}.ipynb"
                write_gold_notebook(nb, out_path)
                outcome = validate_gold_notebook(out_path)
                if outcome.ok:
                    st.success(f"Notebook válido gerado em {out_path}")
                else:
                    st.error("Notebook inválido (Gold Gates):")
                    for e in outcome.errors:
                        st.write(f"- {e}")
                for w in outcome.warnings:
                    st.warning(w)
                if not write_to_disk_g:
                    out_path.unlink(missing_ok=True)
                    st.info("Notebook removido do disco (checkbox 'gravar' desmarcado; apenas preview).")
            except ValueError as exc:
                st.error(f"Bloqueado: {exc}")

# ==================== 4. Manifest (Fabric) ====================
with tab_manifest:
    st.subheader("Manifest — Canonical Write Workflow (validate -> plan -> dry-run -> apply)")
    manifests_dir = profile.paths.manifests_root
    existing = sorted(manifests_dir.glob("**/*.yaml"))
    mode = st.radio(
        "Fonte do manifest",
        options=["Selecionar existente", "Criar/editar novo"],
        horizontal=True,
        help="📋 Escolha trabalhar com manifest existente ou criar um novo"
    )

    manifest_path: Path | None = None
    if mode == "Selecionar existente" and existing:
        rel_options = [str(p.relative_to(PROJECT_ROOT)) for p in existing]
        picked = st.selectbox(
            "Manifest",
            options=rel_options,
            help="📄 Manifest YAML para executar workflow"
        )
        manifest_path = PROJECT_ROOT / picked
        st.code(manifest_path.read_text(encoding="utf-8"), language="yaml")
    else:
        st.markdown("Edite o YAML abaixo (mesmo esquema de `datapipeline_manifest_patterns.md`) e salve:")
        default_yaml = (
            "manifest_id: pp_example_20260101\n"
            "environment: DEV\n"
            "operation: ensure\n"
            "owner: dlctl-agent\n"
            "resource_type: DataPipeline\n"
            "displayName: pp_example\n"
            "description: \"\"\n"
            "safety:\n"
            "  allow_write: true\n"
            "  delete_allowed: false\n"
            "  allow_move_existing: true\n"
            "desired_state:\n"
            "  displayName: pp_example\n"
            "  description: \"\"\n"
            "  folderPath: pipelines/SUPRIMENTOS\n"
            "  definition_file: ../../fabric_definitions/CHANGE_ME.definition.json\n"
            "  parameters: {}\n"
        )
        yaml_text = st.text_area(
            "Conteúdo YAML",
            value=default_yaml,
            height=300,
            help="📄 Manifesto de recurso Fabric (DataPipeline, SemanticModel, Notebook, etc)"
        )
        new_filename = st.text_input(
            "Nome do arquivo (será salvo em manifests/datapipeline/)",
            value="novo_manifest.yaml",
            help="📝 Arquivo YAML a criar (sem /; usa estrutura padrão)"
        )
        if st.button(
            "Salvar manifest",
            help="💾 Valida YAML e salva no projeto"
        ):
            try:
                yaml.safe_load(yaml_text)  # valida sintaxe antes de salvar
                target = manifests_dir / "datapipeline" / new_filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(yaml_text, encoding="utf-8")
                st.success(f"Manifest salvo em {target}")
                st.rerun()
            except yaml.YAMLError as exc:
                st.error(f"YAML inválido: {exc}")

    if manifest_path:
        col_v, col_p, col_d = st.columns(3)
        with col_v:
            if st.button("① Validate"):
                m = manifest_engine.load_manifest(manifest_path)
                result = manifest_engine.validate(m)
                st.session_state["manifest_loaded"] = m
                if result.ok:
                    st.success("Válido")
                else:
                    st.error("Inválido")
                for issue in result.issues:
                    (st.error if issue.level == "error" else st.warning)(issue.message)
        with col_p:
            if st.button("② Plan"):
                m = st.session_state.get("manifest_loaded") or manifest_engine.load_manifest(manifest_path)
                try:
                    client = None
                    try:
                        from dlctl.connectors.fabric_api import build_client_from_profile
                        client = build_client_from_profile(profile)
                    except Exception:
                        client = None
                    plan_result = manifest_engine.plan(m, fabric_client=client)
                    st.session_state["manifest_plan"] = plan_result
                    st.info(f"Ação planejada: **{plan_result.action}** — {plan_result.diff_summary}")
                except SecurityError as exc:
                    st.error(str(exc))
        with col_d:
            if st.button("③ Dry-run"):
                m = st.session_state.get("manifest_loaded") or manifest_engine.load_manifest(manifest_path)
                plan_result = st.session_state.get("manifest_plan")
                if not plan_result:
                    st.warning("Rode 'Plan' primeiro.")
                else:
                    outcome = manifest_engine.dry_run(m, plan_result)
                    if outcome.ok:
                        st.success("dry-run OK: nenhuma divergência de hash/definição.")
                    else:
                        for issue in outcome.issues:
                            st.error(issue.message)

        st.divider()
        st.markdown("**④ Apply — requer confirmação explícita (equivalente a `--confirm-write`)**")
        _write_blocked = profile.microsoft.is_read_only
        if _write_blocked:
            st.warning("🔒 Escopo read_only: ações de escrita/apply estão desabilitadas. Altere o escopo em Configuração > Microsoft Fabric para 'contributor'.")
        confirm_write = st.checkbox("Confirmo a escrita (--confirm-write)", key="manifest_confirm_write", disabled=_write_blocked)
        confirm_production = st.checkbox("Confirmo produção (--confirm-production, só necessário em PRD)", key="manifest_confirm_prod", disabled=_write_blocked)
        confirm_move = st.checkbox("Confirmo mover item existente (--confirm-move, se aplicável)", key="manifest_confirm_move", disabled=_write_blocked)
        if st.button("Aplicar manifest (APPLY)", type="primary", disabled=_write_blocked):
            m = st.session_state.get("manifest_loaded") or manifest_engine.load_manifest(manifest_path)
            plan_result = st.session_state.get("manifest_plan")
            if not plan_result:
                st.warning("Rode 'Plan' (e idealmente 'Dry-run') antes de aplicar.")
            else:
                try:
                    client = None
                    try:
                        from dlctl.connectors.fabric_api import build_client_from_profile
                        client = build_client_from_profile(profile)
                    except Exception:
                        client = None
                    gate = GateContext(profile=profile)
                    result = manifest_engine.apply(
                        m, plan_result, gate, confirm_write=confirm_write,
                        confirm_production=confirm_production, confirm_move=confirm_move, fabric_client=client,
                    )
                    color_fn = {"applied": st.success, "noop": st.info, "manual_required": st.warning, "failed": st.error}
                    color_fn.get(result["status"], st.write)(f"{result['status']}: {result}")
                except SecurityError as exc:
                    st.error(f"BLOCKED: {exc}")
    elif mode == "Selecionar existente":
        st.info("Nenhum manifest encontrado em manifests/. Crie um na aba 'Criar/editar novo'.")

# ==================== 5. Execute (gated) ====================
with tab_execute:
    st.subheader("Execute — Canonical Execution Workflow")
    with st.form("form_execution"):
        execution_id = st.text_input("execution_id", value="exec_pilot_001")
        item_display_name = st.text_input("item_display_name (nome do item no Fabric)")
        item_type = st.selectbox("item_type", options=["Notebook", "DataPipeline", "Dataflow", "CopyJob"])
        parameters_json = st.text_area("parameters (JSON)", value="{}")
        build_manifest = st.form_submit_button("Montar manifesto de execução")
    if build_manifest:
        try:
            params = json.loads(parameters_json or "{}")
            st.session_state["execution_manifest"] = ExecutionManifest(
                execution_id=execution_id, item_display_name=item_display_name,
                item_type=item_type, parameters=params,
            )
            st.success("Manifesto de execução montado (veja os botões abaixo).")
        except json.JSONDecodeError as exc:
            st.error(f"JSON de parâmetros inválido: {exc}")

    exec_manifest = st.session_state.get("execution_manifest")
    if exec_manifest:
        col_ep, col_ed = st.columns(2)
        with col_ep:
            if st.button("① Plan execução"):
                st.json(plan_execution(exec_manifest))
        with col_ed:
            if st.button("② Dry-run execução"):
                issues = dry_run_execution(exec_manifest)
                if issues:
                    for i in issues:
                        st.error(i)
                else:
                    st.success("dry-run OK")

        st.divider()
        admin_actions_blocked = False
        _exec_blocked = profile.microsoft.is_read_only
        if _exec_blocked:
            st.warning("🔒 Escopo read_only: execução no Fabric desabilitada. Altere em Configuração > Microsoft Fabric para 'contributor'.")
        confirm_execute = st.checkbox("Confirmo a execução (--confirm-execute)", key="execute_confirm", disabled=_exec_blocked)
        if st.button("③ Apply (disparar execução)", type="primary", disabled=_exec_blocked):
            try:
                client = None
                try:
                    from dlctl.connectors.fabric_api import build_client_from_profile
                    client = build_client_from_profile(profile)
                except Exception:
                    client = None
                gate = GateContext(profile=profile)
                result = apply_execution(exec_manifest, gate, confirm_execute=confirm_execute, fabric_client=client)
                color_fn = {"started": st.success, "manual_required": st.warning, "failed": st.error}
                color_fn.get(result["status"], st.write)(f"{result['status']}: {result}")
            except SecurityError as exc:
                st.error(f"BLOCKED: {exc}")

# ==================== 6. Pipeline Router ====================
with tab_pipeline:
    st.subheader("Pipeline Router — constellation-order-tracking-etl (fim a fim)")
    with st.form("form_pipeline"):
        bronze_base_path_pl = st.text_input("Bronze base path", value="Files/Bronze")
        silver_base_path_pl = st.text_input("Silver base path", value="Tables/silver")
        gold_base_path_pl = st.text_input("Gold base path", value="Tables/gold")
        write_pl = st.checkbox("Gravar notebooks em disco (--write)", value=True)
        _pl_blocked = profile.microsoft.is_read_only
        if _pl_blocked:
            st.warning("🔒 Escopo read_only: publish, escrita e execução do pipeline estão desabilitados. Altere em Configuração > Microsoft Fabric.")
        publish_pl = st.checkbox("Tentar publicar Silver/Gold via manifest (--publish)", disabled=_pl_blocked)
        confirm_write_pl = st.checkbox("Confirmo escrita (--confirm-write)", disabled=_pl_blocked)
        confirm_execute_pl = st.checkbox("Confirmo execução (--confirm-execute)", disabled=_pl_blocked)
        run_button = st.form_submit_button("🚀 Rodar pipeline completo", type="primary", disabled=_pl_blocked)

    if run_button:
        progress_area = st.container()
        steps_log: list[dict] = []

        def on_step(index: int, name: str, status: str, detail: str) -> None:
            steps_log.append({"index": index, "name": name, "status": status, "detail": detail})

        with st.spinner("Executando pipeline..."):
            result = run_order_tracking(
                profile, domain=domain, bronze_base_path=bronze_base_path_pl,
                silver_base_path=silver_base_path_pl, gold_base_path=gold_base_path_pl,
                write=write_pl, publish=publish_pl, confirm_write=confirm_write_pl,
                confirm_execute=confirm_execute_pl, on_step=on_step,
            )

        with progress_area:
            emoji_map = {"success": "✅", "failed": "❌", "blocked": "🛑", "skipped": "⏭️"}
            for s in steps_log:
                st.write(f"{emoji_map.get(s['status'], '⏳')} **[{s['index']}] {s['name']}** — {s['status']}  \n_{s['detail']}_")

        status_fn = {"success": st.success, "blocked": st.warning, "failed": st.error}
        status_fn.get(result["status"], st.info)(f"Run {result['status']}: run_id={result['run_id']} — {result['summary']}")
        st.info("Veja a página principal (Visão Geral) para o histórico completo desta e de outras execuções.")
