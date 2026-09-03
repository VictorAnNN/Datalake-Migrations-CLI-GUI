# Validação da linhagem consolidada — 03/09/2026

## Decisões técnicas

- `Domínio` e `Sistema de Origem` são conceitos distintos. O primeiro indica a área consumidora; o segundo vem da coluna `Sistema` do mapping do cliente.
- `Oracle ERP` é exibido como `Oracle ERP (Fusion)` e `MAXIMO` como `Máximo`; os demais valores são preservados.
- Quando a tabela não possui `Sistema`, a origem só é herdada da dependência upstream explícita mais próxima. Prefixos e nomes parecidos não são usados para adivinhar a fonte.
- Cada linha expõe `Evidência Sistema de Origem`, distinguindo valor direto do mapping, herança por linhagem e ausência de evidência.
- URLs e caminhos da coluna `(0) Source` não são incorporados ao HTML autônomo.

## Resultado estático local

Base: 600 entradas, sendo 589 tabelas canônicas e 11 entradas não canônicas.

- 569 entradas possuem sistema identificado.
- 568 foram classificadas diretamente pela coluna `Sistema`.
- 1 foi classificada pela dependência upstream mais próxima.
- 31 permanecem como `Não identificado`; devem ser corrigidas no mapping ou respaldadas por uma dependência explícita.

Distribuição identificada:

| Sistema | Entradas |
|---|---:|
| Oracle ERP (Fusion) | 283 |
| Máximo | 142 |
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
- 93/103 linhagens estáticas fim a fim possuem a tabela inicial materializada.
- 8 relatórios e 10 nomes únicos de modelos semânticos têm correspondência nominal no DEV.
- IDs legados de report/dataset não coincidem com os IDs do DEV; cópia/publicação gera novas identidades.
- 151/589 tabelas possuem notebook candidato por correspondência nominal. Isso é indício, não vínculo de execução.

## Limites da evidência

O relatório comprova relações estáticas, correspondência nominal e presença física observada. Não comprova execução, atualização, contrato de colunas, relacionamento do modelo semântico, materialização recente ou resultado funcional dos visuais.
