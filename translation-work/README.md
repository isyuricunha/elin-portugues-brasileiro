# Toolkit de localização de Elin

A fonte editável fica em `EN/Package/Lang/EN`. Os 45 lotes em `translations/` preservam o trabalho do workspace privado no estado de `e8edd111722e185855e8f39661d9a078f46afe89`. O importador conferiu as chaves e textos da fila antiga contra o extrator e adotou os valores finais do pacote privado. Isso preservou 38 correções que divergiam dos lotes históricos, inclusive ajustes em tabelas e o deslocamento do texto de atualização. Também incluiu 935 entradas preexistentes fora da fila antiga, entre fragmentos de nomes, falas de personagens e divindades e o modelo de biografia. Em 107 dessas entradas, a toolkit conserva a versão importada por hash. Ao editar uma delas, a nova versão precisa passar na validação atual. Células fora das colunas nativas de diálogo foram excluídas da reconstrução. O histórico e as revisões do workspace privado continuam disponíveis naquele repositório. Nenhuma automação de tradução integra a toolkit.

## Primeiro uso

1. Leia [o briefing](docs/briefing-do-jogo.md), [o glossário](docs/glossario-ptbr.md) e [as diretrizes](docs/diretrizes-de-traducao.md).
2. Use Python 3.10 ou mais recente. No Ubuntu, prepare o ambiente com `python3 -m venv .venv` e `.venv/bin/python -m pip install -r translation-work/requirements.txt`.
3. Rode `.venv/bin/python -B translation-work/toolkit.py doctor --ubuntu-arm64`. O comando é somente leitura. Ele confere hashes das fontes, a cadeia de ferramentas, sistema e arquitetura, dependências e um teste nativo de leitura e reconstrução em memória. Se falhar, encaminhe o erro antes de trabalhar nos lotes.
4. Use `status` para ver a cobertura e `resume` para localizar pendências e suas revisões. Ambos funcionam sem importar o parser de planilhas.

Verificação local em Windows x64. Em Ubuntu Server 24.04 ARM64, espera-se Python 3.12 com as duas dependências puras em Python de `requirements.txt`. A execução real em ARM64 está pendente.

## Edição e validação

Passe os comandos abaixo após `python -B translation-work/toolkit.py`, usando o Python do ambiente.

| Comando | Uso |
| --- | --- |
| `status`, `resume` | Cobertura e fila de pendências. |
| `check` | Valida as entradas, os metadados imutáveis e a integridade das fontes. Aceita tradução parcial. |
| `apply edicoes.json` | Aplica um array de objetos com `id`, `revision`, `PTBR` e, quando pertinente, `fallback`. `revision` é o SHA-256 do registro inteiro, serializado em JSON ordenado e indentado com dois espaços, UTF-8 e LF final. |
| `update-sources --dry-run` | Localiza a instalação conhecida no Windows. `--game-root` indica outro caminho. |
| `update-sources --export-root CAMINHO --version "EA …" --dry-run` | Compara uma exportação completa e editável, validada para a versão informada. Retire `--dry-run` para aceitar o novo conjunto. |
| `build --dry-run`, `build` | Reconstrução de prova sem gravação, ou produção completa em `PTBR/`. Nenhum deles aceita pendências. |
| `verify-output`, `package CAMINHO.zip` | Conferência rápida das entradas e saídas ou criação local de ZIP verificado. |
| `gc --dry-run`, `gc`, `rollback`, `recover` | Inspeção de limpeza, limpeza, desfazer a última transação e recuperação. |

Os lotes têm até 500 entradas. Ao editar JSONL diretamente, altere `PTBR` e o campo `fallback` quando aplicável. Use `""` para pendência e `""` com `fallback: true` somente para os casos elegíveis em que se preserva a exibição do jogo. O validador cobre sintaxe e estrutura. A revisão de significado, gênero, tom e consistência permanece editorial.

## Atualização de fontes

A instalação EA 23.355 tem `Data`, `Text` e `Widget` em `Package/_Elona/Lang/EN` e diálogos em `Lang/_Dialog`, mas compila as tabelas de jogo em `Data/Source`. Sem uma exportação editável completa, a toolkit encerra com `EDITABLE_EXPORT_REQUIRED`. O [guia oficial de localização](https://docs.google.com/document/d/e/2PACX-1vSj8lHcRFhFU_332eYCAlft9u1hkTlb5efUqVPsLQTtOPA79Tgh3FvNfJz9edvy0jI616BdiLidyxdz/pub) descreve como o próprio jogo gera e atualiza a estrutura de um pacote de idioma. Use um pacote inglês descartável na versão alvo e preserve a exportação bruta. As colunas traduzidas de um pacote preexistente podem contaminar a referência, por isso mantenha o pacote de exportação separado do mod PT-BR.

O diff classifica inclusão, alteração, remoção e revisão posicional. Se um arquivo realmente saiu do jogo, confirme seu caminho relativo com `--allow-removed-file`. A remoção de uma família inteira permanece bloqueada. Para uma tabela com ID único, realocar a linha conserva a tradução se a fonte e o contexto forem iguais. Para textos por linha e tabelas sem chave única, qualquer mudança do arquivo pede revisão das posições. A atualização grava `reports/source-diff.jsonl` e guarda a tradução anterior nas entradas que mudaram. Operações repetidas com fontes iguais e a mesma versão são no-op.

## Armazenamento e recuperação

A toolkit mantém até 10 transações completas, com teto de 512 MiB e reserva de disco para gravação. Cada aplicação grava e guarda somente os lotes modificados. `gc --dry-run` lista a retenção sem tocar nos arquivos. Com journal pendente, a limpeza é bloqueada. Se um processo for interrompido, confirme que ele terminou e execute `recover`. Se a trava ficou órfã, use `recover --break-lock` antes de `recover`. O Git conserva o histórico de longo prazo.

## Build e publicação

O mod contém `package.xml` e `Lang/PTBR`; no jogo, a pasta do mod fica em `Package/PTBR`. A publicação é disparada no branch `main` quando `PTBR/` muda. A verificação usa o manifesto e hashes de arquivos; o CI não reconstrói as planilhas. O ZIP contém os arquivos do mod na raiz. A versão incrementa o patch SemVer e as tags existentes são preservados. O Actions gera dois anexos em cada Release. `PTBR.zip` contém a tradução e `PTBR-COM-PORTRAIT.zip` inclui também `Portrait/`. Os ZIPs ficam apenas na Release. O fluxo não foi executado no GitHub nesta migração.

Os [avisos da licença](../LICENSE), [permissão adicional](../GAME-DEVELOPER-PERMISSION.md) e [consentimento de contribuições](../CONTRIBUTING.md) valem nos escopos descritos em cada documento. A presença de fontes e ativos de Elin no histórico ou no workspace não concede direitos de distribuição sobre eles.
