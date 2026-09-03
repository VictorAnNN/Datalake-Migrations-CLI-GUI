"""Standalone HTML view for the dashboard lineage diagnostic.

The export intentionally has no CDN/runtime dependency: all styles, data and
interaction code are embedded so the artifact can be reviewed offline.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def _safe_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def export_dashboard_lineage_html(
    result: dict,
    output_path: Path,
    *,
    planning_context: dict | None = None,
    source_context: dict | None = None,
) -> Path:
    """Write an offline, searchable end-to-end lineage report."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": result.get("summary", {}),
        "rows": result.get("end_to_end_mapping_rows", []),
        "dashboard_quality": result.get("dashboard_quality_rows", []),
        "planning": planning_context or {},
        "sources": source_context or {},
    }
    html = _HTML.replace("__LINEAGE_DATA__", _safe_json(payload))
    output_path.write_text(html, encoding="utf-8")
    return output_path


_HTML = r'''<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mapa de linhagem — Constellation</title>
<style>
:root{--bg:#080d17;--panel:#101827;--panel2:#151f31;--line:#26344b;--text:#ecf3ff;--muted:#94a4bd;--cyan:#22d3ee;--blue:#60a5fa;--bronze:#ef4444;--silver:#aab5c6;--gold:#f6c344;--green:#34d399;--violet:#a78bfa;--orange:#fb923c}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(135deg,#070b12,#0b1220 58%,#07131c);color:var(--text);font:14px Inter,Segoe UI,Arial,sans-serif}button,input,select{font:inherit}.app{max-width:1760px;margin:auto;padding:24px}.header{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;margin-bottom:20px}.eyebrow{color:var(--cyan);font-weight:700;letter-spacing:.08em;text-transform:uppercase;font-size:12px}h1{font-size:27px;margin:6px 0}.subtitle,.note{color:var(--muted);line-height:1.5}.badge{border:1px solid var(--line);border-radius:999px;padding:7px 11px;color:var(--muted);white-space:nowrap}.grid{display:grid;gap:12px}.kpis{grid-template-columns:repeat(6,minmax(130px,1fr));margin-bottom:16px}.card,.panel{background:rgba(16,24,39,.92);border:1px solid var(--line);border-radius:12px}.card{padding:15px}.card .label{color:var(--muted);font-size:12px}.card .value{font-size:25px;font-weight:750;margin-top:7px}.panel{padding:17px;margin-bottom:16px}.panel h2{font-size:17px;margin:0 0 13px}.panel-head{display:flex;justify-content:space-between;align-items:center;gap:12px}.filters{grid-template-columns:2fr repeat(4,1fr) auto}.field label{display:block;color:var(--muted);font-size:11px;margin:0 0 5px}.field input,.field select{width:100%;background:#09111e;border:1px solid var(--line);border-radius:7px;color:var(--text);padding:9px}.btn{align-self:end;background:#102c3a;color:var(--cyan);border:1px solid #1c6070;border-radius:7px;padding:9px 12px;cursor:pointer}.btn:hover{background:#14394a}.split{display:grid;grid-template-columns:minmax(0,1fr) 430px;gap:16px}.flow{display:grid;grid-template-columns:repeat(5,minmax(130px,1fr));gap:24px;overflow:auto;padding:8px 2px 16px}.stage{position:relative;border:1px solid var(--line);border-radius:10px;padding:12px;min-height:105px;background:#0c1422}.stage:not(:last-child):after{content:'→';position:absolute;right:-20px;top:42%;color:#61728e;font-size:22px}.stage .n{font-size:11px;color:var(--muted);text-transform:uppercase}.stage .v{font-weight:700;margin:8px 0;overflow-wrap:anywhere}.stage .s{font-size:11px;color:var(--muted)}.stage.origin{border-top:3px solid var(--orange)}.stage.bronze{border-top:3px solid var(--bronze)}.stage.silver{border-top:3px solid var(--silver)}.stage.gold{border-top:3px solid var(--gold)}.stage.consumer{border-top:3px solid var(--green)}.layout{display:grid;grid-template-columns:minmax(0,1fr) 420px;gap:16px}.table-wrap{overflow:auto;max-height:620px;border:1px solid var(--line);border-radius:9px}table{width:100%;border-collapse:collapse;font-size:12px}th{position:sticky;top:0;background:#152036;color:#b9c7da;text-align:left;padding:10px;border-bottom:1px solid var(--line);z-index:1}td{padding:9px 10px;border-bottom:1px solid #1c293d;vertical-align:top}tbody tr{cursor:pointer}tbody tr:hover,tbody tr.active{background:#15243a}.status{display:inline-block;border-radius:999px;padding:4px 7px;font-weight:700;font-size:10px}.complete{background:#123c32;color:#6ee7b7}.partial{background:#443014;color:#fcd34d}.orphan{background:#471e27;color:#fda4af}.candidate{background:#28305a;color:#c4b5fd}.noncanonical{background:#432b18;color:#fdba74}.detail{position:sticky;top:15px;max-height:780px;overflow:auto}.detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.kv{background:#0b1320;border:1px solid #1e2d43;border-radius:8px;padding:10px}.kv.full{grid-column:1/-1}.kv b{display:block;color:var(--muted);font-size:10px;text-transform:uppercase;margin-bottom:5px}.kv span{overflow-wrap:anywhere}.bars{display:grid;gap:8px}.bar-row{display:grid;grid-template-columns:210px 1fr 52px;gap:10px;align-items:center}.bar{height:10px;background:#0a111d;border-radius:99px;overflow:hidden}.bar i{display:block;height:100%;border-radius:99px}.plan{grid-template-columns:repeat(6,minmax(130px,1fr))}.plan .card{background:#0b1422}.warn{border-left:3px solid var(--orange);padding-left:12px}.empty{color:var(--muted);padding:25px;text-align:center}.foot{font-size:11px;color:var(--muted);padding:8px 0 20px}.count{color:var(--cyan);font-weight:700}.hide{display:none!important}
@media(max-width:1100px){.kpis,.plan{grid-template-columns:repeat(3,1fr)}.layout,.split{grid-template-columns:1fr}.detail{position:static}.filters{grid-template-columns:1fr 1fr}.header{display:block}.badge{display:inline-block;margin-top:10px}}
@media(max-width:620px){.app{padding:12px}.kpis,.plan,.filters{grid-template-columns:1fr 1fr}.flow{grid-template-columns:1fr}.stage:not(:last-child):after{display:none}}
</style>
</head>
<body><main class="app">
<header class="header"><div><div class="eyebrow">Constellation · Auditoria estática</div><h1>Mapa fim a fim de linhagem</h1><div class="subtitle">Mapping do cliente → camadas → dataset/dataflow → dashboard, com motivo e próxima ação por item.</div></div><div class="badge" id="generated"></div></header>

<section class="grid kpis" id="kpis"></section>

<section class="panel" id="planningPanel"><div class="panel-head"><h2>Baseline interno de planejamento</h2><span class="badge" id="planningAsOf"></span></div><div class="grid plan" id="planning"></div><p class="note warn" id="planningNote"></p></section>

<section class="panel"><div class="panel-head"><h2>Cobertura do diagnóstico</h2><span class="note" id="visibleCount"></span></div><div class="bars" id="statusBars"></div></section>

<section class="panel"><h2>Filtros</h2><div class="grid filters">
<div class="field"><label>Busca</label><input id="search" placeholder="Tabela, dashboard, dataset, domínio, observação..."></div>
<div class="field"><label>Status</label><select id="status"><option value="">Todos</option></select></div>
<div class="field"><label>Camada mapeada</label><select id="layer"><option value="">Todas</option></select></div>
<div class="field"><label>Sistema fonte</label><select id="source"><option value="">Todos</option></select></div>
<div class="field"><label>Chega a dashboard</label><select id="reaches"><option value="">Todos</option><option>Sim</option><option>Candidato</option><option>Não</option></select></div>
<button class="btn" id="clear">Limpar</button>
</div></section>

<section class="panel"><h2>Rota selecionada</h2><div class="flow" id="flow"></div></section>

<section class="layout">
<section class="panel"><div class="panel-head"><h2>Itens do mapping</h2><span class="note">Clique numa linha para inspecionar</span></div><div class="table-wrap"><table><thead><tr><th>Tabela / entrada</th><th>Camada</th><th>Domínio</th><th>Sistema fonte</th><th>Status</th><th>Etapa</th><th>Dashboards</th></tr></thead><tbody id="rows"></tbody></table></div></section>
<aside class="panel detail"><h2>Diagnóstico</h2><div id="detail" class="empty">Selecione uma linha.</div></aside>
</section>

<section class="panel"><h2>Qualidade do inventário e fontes</h2><div class="grid plan" id="sources"></div><p class="note warn">Esta visão comprova somente relações estáticas nos artefatos fornecidos. Não comprova publicação, execução, materialização ou resultado funcional no Fabric.</p></section>
<footer class="foot">Arquivo autônomo: dados, estilos e interações estão incorporados; nenhuma conexão externa é necessária.</footer>
</main>
<script>
const DATA=__LINEAGE_DATA__;
const rows=DATA.rows||[], summary=DATA.summary||{};
const $=id=>document.getElementById(id), esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=n=>new Intl.NumberFormat('pt-BR').format(Number(n||0));
const statusClass=s=>s.startsWith('COMPLETO')?'complete':s.startsWith('PARCIAL')?'partial':s.startsWith('ORFAO')?'orphan':s.includes('CANDIDATO')?'candidate':'noncanonical';
const statusLabel=s=>({COMPLETO:'Completo',COMPLETO_DIRETO:'Completo direto',PARCIAL_SEM_DASHBOARD:'Parcial sem dashboard',ORFAO_SEM_ARESTA:'Órfão sem aresta',CANDIDATO_BAIXA_CONFIANCA:'Candidato baixa confiança',FONTE_ARQUIVO_NAO_TABELA:'Fonte arquivo',NOME_QUALIFICADO_NAO_NORMALIZADO:'Nome qualificado',ALIAS_EM_NOME_TABELA:'Alias no nome',ROTULO_NAO_CANONICO:'Rótulo não canônico'})[s]||s;

$('generated').textContent='Gerado em '+new Date(DATA.generated_at).toLocaleString('pt-BR');
const confirmed=summary.total_fim_a_fim_confirmado||0, noncanon=summary.total_fim_a_fim_entrada_nao_canonica||0;
const kpis=[['Entradas diagnosticadas',rows.length],['Tabelas canônicas',summary.total_tabelas_excel_cliente],['Fim a fim confirmado',confirmed],['Parciais',summary.total_fim_a_fim_parcial],['Órfãs',summary.total_fim_a_fim_orfao],['Não canônicas',noncanon]];
$('kpis').innerHTML=kpis.map(([l,v])=>`<div class="card"><div class="label">${esc(l)}</div><div class="value">${fmt(v)}</div></div>`).join('');

const planning=DATA.planning||{};
if(!Object.keys(planning).length){$('planningPanel').classList.add('hide')}else{
 $('planningAsOf').textContent=planning.as_of||'';
 $('planning').innerHTML=(planning.metrics||[]).map(x=>`<div class="card"><div class="label">${esc(x.label)}</div><div class="value">${esc(x.done)} / ${esc(x.total)}</div><div class="note">${esc(x.note||'')}</div></div>`).join('');
 $('planningNote').textContent=planning.note||'';
}

const statusCounts=rows.reduce((a,r)=>(a[r.status_fim_a_fim]=(a[r.status_fim_a_fim]||0)+1,a),{});
const maxStatus=Math.max(1,...Object.values(statusCounts));
$('statusBars').innerHTML=Object.entries(statusCounts).sort((a,b)=>b[1]-a[1]).map(([s,n])=>`<div class="bar-row"><span>${esc(statusLabel(s))}</span><span class="bar"><i class="${statusClass(s)}" style="width:${100*n/maxStatus}%"></i></span><strong>${fmt(n)}</strong></div>`).join('');

const statuses=[...new Set(rows.map(r=>r.status_fim_a_fim))].sort(), layers=[...new Set(rows.map(r=>r.camada_mapeada).filter(Boolean))].sort(), sources=[...new Set(rows.map(r=>r.sistema_origem).filter(Boolean))].sort();
$('status').innerHTML+=""+statuses.map(x=>`<option value="${esc(x)}">${esc(statusLabel(x))}</option>`).join('');
$('layer').innerHTML+=""+layers.map(x=>`<option>${esc(x)}</option>`).join('');
$('source').innerHTML+=""+sources.map(x=>`<option>${esc(x)}</option>`).join('');
let selected=null, filtered=[];
function apply(){
 const q=$('search').value.trim().toLocaleLowerCase('pt-BR'), st=$('status').value, la=$('layer').value, so=$('source').value, re=$('reaches').value;
 filtered=rows.filter(r=>(!st||r.status_fim_a_fim===st)&&(!la||r.camada_mapeada===la)&&(!so||r.sistema_origem===so)&&(!re||r.chega_dashboard===re)&&(!q||Object.values(r).join(' ').toLocaleLowerCase('pt-BR').includes(q)));
 $('visibleCount').innerHTML=`<span class="count">${fmt(filtered.length)}</span> de ${fmt(rows.length)} itens`;
 $('rows').innerHTML=filtered.map((r,i)=>`<tr data-i="${i}"><td><strong>${esc(r.tabela_mapeada)}</strong></td><td>${esc(r.camada_mapeada)}</td><td>${esc(r.dominio)}</td><td>${esc(r.sistema_origem||'—')}</td><td><span class="status ${statusClass(r.status_fim_a_fim)}">${esc(statusLabel(r.status_fim_a_fim))}</span></td><td>${esc(r.etapa_alcancada)}</td><td>${fmt(r.qtd_dashboards)}</td></tr>`).join('')||'<tr><td colspan="7" class="empty">Nenhum resultado.</td></tr>';
 [...$('rows').querySelectorAll('tr[data-i]')].forEach(tr=>tr.onclick=()=>select(filtered[+tr.dataset.i],tr));
 if(filtered.length&&(!selected||!filtered.includes(selected))) select(filtered[0],$('rows').querySelector('tr[data-i]')); else if(!filtered.length){selected=null;$('detail').innerHTML='<div class="empty">Nenhum resultado.</div>';$('flow').innerHTML=''}
}
function select(r,tr){
 selected=r;[...$('rows').querySelectorAll('tr')].forEach(x=>x.classList.remove('active'));if(tr)tr.classList.add('active');
 const path=(r.caminho_exemplo||r.tabela_mapeada||'').split(' -> ').filter(Boolean), stages=[];
 stages.push({c:'origin',n:'1. Mapping / origem',v:path[0]||r.tabela_mapeada,s:[r.sistema_origem,r.dominio].filter(Boolean).join(' · ')||'Origem não identificada'});
 const inner=path.slice(1,-1);inner.forEach((v,i)=>stages.push({c:v.startsWith('DW_')?'silver':(v.startsWith('DM_')||v.startsWith('PR_'))?'gold':'bronze',n:`${i+2}. Dependência`,v,s:'Relação estática'}));
 if(path.length>1)stages.push({c:(r.camada_mapeada||'').includes('Gold')?'gold':'silver',n:`${stages.length+1}. Endpoint`,v:path.at(-1),s:r.tipo_evidencia_endpoint||''});
 stages.push({c:'consumer',n:`${stages.length+1}. Consumidor`,v:r.dashboard||'Não identificado',s:r.dataset||r.etapa_alcancada});
 $('flow').innerHTML=stages.map(x=>`<div class="stage ${x.c}"><div class="n">${esc(x.n)}</div><div class="v">${esc(x.v)}</div><div class="s">${esc(x.s)}</div></div>`).join('');
 const fields=[['Sistema fonte',r.sistema_origem],['Evidência da fonte',r.evidencia_sistema_origem],['Status',statusLabel(r.status_fim_a_fim)],['Chega a dashboard',r.chega_dashboard],['Etapa alcançada',r.etapa_alcancada],['Confiança',r.confianca],['Tabela endpoint',r.tabela_endpoint],['Qtd. dashboards',r.qtd_dashboards],['Workspace',r.workspace],['Dashboard',r.dashboard],['Dataset',r.dataset],['Caminho conhecido',r.caminho_exemplo],['Dashboards (amostra)',r.dashboards_amostra],['Observação',r.observacao],['Ação recomendada',r.acao_recomendada],['Alertas',r.alertas],['Report ID',r.report_id],['Dataset ID',r.dataset_id]];
 $('detail').innerHTML=`<div class="detail-grid">${fields.map(([k,v])=>`<div class="kv ${String(v||'').length>80?'full':''}"><b>${esc(k)}</b><span>${esc(v||'—')}</span></div>`).join('')}</div>`;
}
['search','status','layer','source','reaches'].forEach(id=>$(id).addEventListener(id==='search'?'input':'change',apply));
$('clear').onclick=()=>{$('search').value='';$('status').value='';$('layer').value='';$('source').value='';$('reaches').value='';apply()};

const src=DATA.sources||{}, sourceCards=[
 ['Relatórios no scan',summary.total_reports_scan],['Relatórios com tabelas',summary.total_reports_com_tabelas],['Dataset não resolvido',summary.total_reports_dataset_nao_resolvido],['Sem fonte identificada',summary.total_reports_sem_fontes],['Dataflows no scan',summary.total_dataflows_scan],['Exports M disponíveis',summary.total_exports_dataflow]
];
if(src.report_inventory_rows!==undefined)sourceCards.push(['Inventário local de Reports',src.report_inventory_rows]);
$('sources').innerHTML=sourceCards.map(([l,v])=>`<div class="card"><div class="label">${esc(l)}</div><div class="value">${fmt(v)}</div></div>`).join('')+(src.note?`<div class="kv full"><b>Leitura das fontes</b><span>${esc(src.note)}</span></div>`:'');
apply();
</script></body></html>'''
