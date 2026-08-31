# Auditoria do piloto de Notebook Fabric — 2026-08-31

## Veredito

- Branch analisada: `dev`, commit `2adaf4501f37a0888f8653b8822204a0f2f9ebee`.
- Branch local de correção: `codex/notebook-pilot-hardening-20260831`.
- O código original não estava pronto para um piloto confiável: gerava 6 células, mas o contrato Constellation exige 10; o validador aceitava esse falso positivo; a publicação genérica não montava a definição oficial `ipynb`; e 2 testes de linhagem falhavam com coleções vazias.
- Após as correções locais: imagem Docker construída, `94/94` testes aprovados, piloto Silver gerado e validado, Python das 10 células compilável e plano de criação selado por SHA-256.
- Nenhum item foi criado no Fabric: `ms_client_constellation` permanece com `microsoft.allow_write=false`; o `apply-create` foi bloqueado antes de autenticação/chamada HTTP, com exit code 3.

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
- Falta o ensaio online controlado: criar, obter definição por readback, opcionalmente executar com fontes válidas e excluir somente o `itemId` retornado.

## Próximo passo controlado

Após autorização explícita para habilitar escrita no perfil DEV:

1. aplicar o plano selado;
2. confirmar conclusão `201` ou LRO `Succeeded`;
3. ler a definição publicada e comparar SHA-256/células;
4. executar somente se os paths Bronze/Silver do piloto forem válidos;
5. excluir exclusivamente o item criado pelo `itemId` retornado;
6. anexar evidências e então abrir PR da branch local.

## Rollback local

- Nenhum commit foi criado e nenhum push foi feito.
- Para descartar todas as alterações, remover a branch local e retornar ao commit-base `2adaf4501f37a0888f8653b8822204a0f2f9ebee` após preservar qualquer trabalho desejado.
- Artefatos do piloto estão ignorados pelo Git em `notebooks/` e `state/`.
