# Auditoria do piloto de Notebook Fabric — 2026-08-31

## Veredito

- Branch analisada: `dev`, commit `2adaf4501f37a0888f8653b8822204a0f2f9ebee`.
- Branch local de correção: `codex/notebook-pilot-hardening-20260831`.
- O código original não estava pronto para um piloto confiável: gerava 6 células, mas o contrato Constellation exige 10; o validador aceitava esse falso positivo; a publicação genérica não montava a definição oficial `ipynb`; e 2 testes de linhagem falhavam com coleções vazias.
- Após as correções: imagem Docker construída, `94/94` testes aprovados, piloto Silver gerado e validado, Python das 10 células compilável e plano de criação selado por SHA-256.
- Ensaio online concluído no `LAKEHOUSE-DEV`: o próprio `dlctl notebooks apply-create` criou um Notebook, a definição foi relida pela API, as 10 células C1-C10 foram preservadas e o item descartável foi removido com backup e verificação de ausência.

## Piloto preparado

- Fonte: `BRZ_PO_HEADERS_ALL`.
- Destino: `SLV_PO_HEADERS`.
- Target planejado: `LAKEHOUSE-DEV/codex_test_delete_me_slv_po_headers`.
- Notebook local: `notebooks/silver/SLV_PO_HEADERS.ipynb`.
- SHA-256 do notebook: `730d7b9fdc9a037192b509797a8d0ffeb3d0b37c1d1b41003f2901f29d32a8f1`.
- Plano local: `state/plans/codex_test_delete_me_slv_po_headers.plan.json`.
- Hash canônico do plano: `41694708d132e7c50f6fb094606a8668e840748d3705afb8b43b38a43fd3737e`.

## Correções implementadas

1. Geradores Silver e Gold aderentes ao contrato de 10 células.
2. Validação estrita de quantidade, tipo, IDs, ordem e marcadores das células.
3. Falha antecipada quando SQL ou contrato `.tab` obrigatório não existe.
4. `notebooks plan-create`: plano offline, target DEV e hashes de integridade.
5. `notebooks apply-create`: gate de escrita, detecção de nome existente, criação sem overwrite e sem execução.
6. Definição oficial Fabric: `format=ipynb`, `notebook-content.ipynb`, `InlineBase64`.
7. Tratamento de `201 Created` e `202 Accepted` com polling; `202` isolado não é sucesso.
8. Correção dos exportadores de linhagem para DataFrames vazios.
9. Dependências de teste incluídas na imagem Docker.

## Limites restantes

- O mapeamento simplificado não informa chaves primárias; o piloto gera `PRIMARY_KEYS=[]`, portanto não valida duplicidade/quarentena por PK.
- O mapeamento Gold não contém contrato tipado equivalente ao `.tab`; a estrutura está correta, mas a conformidade semântica Gold ainda precisa desse metadado.
- O fluxo genérico de manifests continua inadequado para atualizar definição de Notebook; o novo fluxo específico evita esse caminho, mas não o substitui globalmente.
- O fluxo específico cria um Notebook novo, mas ainda não atualiza, executa, valida materialização nem automatiza seu próprio rollback. A remoção deste ensaio usou a ferramenta governada externa `fabric-fullctl`.

## Ensaio online controlado

- Data: `2026-08-31`.
- Workspace: `LAKEHOUSE-DEV` (`8d8431e6-ef28-4356-8ca3-6cce6f99e5c4`).
- Nome descartável: `codex_test_delete_me_dlctl_pr7_20260831`.
- Plano: `state/plans/codex_test_delete_me_dlctl_pr7_20260831.plan.json`.
- SHA-256 do plano: `d6cec2a84a8e98dc2dc497a810617266dd000055d5b3a1add7ee76a89b652665`.
- SHA-256 local do notebook: `730d7b9fdc9a037192b509797a8d0ffeb3d0b37c1d1b41003f2901f29d32a8f1`.
- Resultado da criação: `SUCCEEDED`.
- Item criado: `194bf8c2-6f36-4ef6-94d5-011811011667`.
- Operação Fabric: `b9b4849f-1415-4682-be32-ea1bc1aad747`.
- Readback: o Fabric normalizou a entrada `ipynb` em `notebook-content.py` + `.platform`; foram encontrados exatamente 10 marcadores, de `C1_HEADER_METADATA` a `C10_METRICS`, na ordem canônica.
- Execução: não realizada; este ensaio prova publicação/readback, não runtime ou materialização.
- Rollback: definição respaldada e item excluído por ID; busca final pelo prefixo retornou zero candidatos.
- Gate: `allow_write` foi habilitado somente durante as operações autorizadas e restaurado byte a byte ao baseline ao final.

## Próximos passos

1. adicionar rollback tipado por `itemId` ao próprio `dlctl`;
2. adicionar readback pós-criação e validação automática dos marcadores/células;
3. testar execução somente com mapeamento, chaves e paths reais aprovados;
4. expor o fluxo específico `plan-create/apply-create` na GUI.

## Rollback

- PR: `https://github.com/rmvieira6/Datalake-Migrations-CLI-GUI/pull/7`.
- Para descartar as alterações de código, fechar o PR e remover a branch `codex/notebook-pilot-hardening-20260831` do fork.
- Artefatos do piloto estão ignorados pelo Git em `notebooks/` e `state/`.
