# Validação da linhagem consolidada — 03/09/2026

## Decisões técnicas

- `Domínio` e `Sistema de Origem` são conceitos distintos. O primeiro indica a área consumidora; o segundo vem da coluna `Sistema` do mapping do cliente.
- `Oracle ERP` é exibido como `Oracle ERP (Fusion)` e `MAXIMO` como `Máximo`; os demais valores são preservados.
- Quando a tabela não possui `Sistema`, a origem só é herdada da dependência upstream explícita mais próxima. Prefixos e nomes parecidos não são usados para adivinhar a fonte.
- Cada linha expõe `Evidência Sistema de Origem`, distinguindo valor direto do mapping, herança por linhagem e ausência de evidência.
- URLs e caminhos da coluna `(0) Source` não são incorporados ao HTML autônomo.

## Resultado estático local

Base: 600 entradas, sendo 589 tabelas canônicas e 11 entradas não canônicas.

- 580 entradas possuem sistema identificado.
- 568 foram classificadas diretamente pela coluna `Sistema`.
- 1 foi classificada pelo sistema explícito no script e 11 pela dependência upstream mais próxima.
- 20 permanecem como `Não identificado`; devem ser corrigidas no mapping ou respaldadas por uma dependência explícita.

Distribuição identificada:

| Sistema | Entradas |
|---|---:|
| Oracle ERP (Fusion) | 293 |
| Máximo | 143 |
| RM | 95 |
| GESTOR | 22 |
| OTRS | 13 |
| Barriers | 7 |
| DRAKE | 5 |
| Active Directory | 1 |
| Active Directory, OTRS | 1 |

## Reconciliação somente leitura com o Fabric DEV

Snapshot de `LAKEHOUSE-DEV` coletado em 03/09/2026 às 17:05 BRT.

- 411/589 tabelas canônicas foram encontradas fisicamente no OneLake.
- 408 estão na camada e Lakehouse esperados.
- 3 aparecem em outro domínio:
  - `PR_FDC_DOCUMENTS_PAYMENTS`: mapping Financeiro; `LH_SUPRIMENTOS.gold`.
  - `PR_GL_BALANCE`: mapping Controladoria; `LH_FINANCEIRO.gold`.
  - `PR_GL_JOURNAL`: mapping Controladoria; `LH_FINANCEIRO.gold`.
- 133/194 linhagens estáticas fim a fim possuem a tabela inicial materializada.
- 8 relatórios e 10 nomes únicos de modelos semânticos têm correspondência nominal no DEV.
- IDs legados de report/dataset não coincidem com os IDs do DEV; cópia/publicação gera novas identidades.
- 151/589 tabelas possuem notebook candidato por correspondência nominal. Isso é indício, não vínculo de execução.

O cruzamento usa 38 listagens de schema do OneLake coletadas até 10 minutos após o snapshot. Listagens de raiz/camada não contam como evidência de tabela.

| Status estático | Total | Encontrada | Ausente |
|---|---:|---:|---:|
| Órfão sem aresta | 337 | 253 | 84 |
| Parcial sem dashboard | 58 | 25 | 33 |
| Completo direto | 122 | 83 | 39 |
| Completo | 72 | 50 | 22 |

`Órfão sem aresta` significa que o mapping não possui aresta downstream nos scripts/views/Excel analisados; 253 deles estão materializados no DEV. `Parcial sem dashboard` significa que a cadeia estática conhecida não alcança um endpoint do scan; 25 deles também estão materializados. Portanto, esses rótulos não significam ausência no Fabric.

## Correção de cobertura das M-queries internas

O rastreador anterior descartava as tabelas internas do modelo quando o dataset também declarava Dataflows upstream. Agora as três evidências são combinadas: export do Dataflow, `FROM`/`JOIN` das M-queries do modelo e nome da entidade semântica, cada uma com confiança própria.

Com a correção, as tabelas mapeadas com consumidor identificado passaram de 103 para 194; órfãs caíram de 386 para 337 e parciais de 100 para 58.

`PR_INVENTORY_MAXIMO_TOT` é o caso de regressão: passou de órfã para `COMPLETO_DIRETO`, ligada a dois relatórios. Sua fonte agora é `Máximo`, sustentada pelo caminho/comentário da procedure, e não `Oracle ERP (Fusion)` herdado de uma dependência indireta.

Notebooks candidatos exigem o nome canônico completo da tabela como token no nome do notebook; nomes curtos não são inferidos. Reports e modelos são associados por nome canônico, pois IDs legados não sobrevivem à publicação.

## Limites da evidência

O relatório comprova relações estáticas, correspondência nominal e presença física observada. Não comprova execução, atualização, contrato de colunas, relacionamento do modelo semântico, materialização recente ou resultado funcional dos visuais.
