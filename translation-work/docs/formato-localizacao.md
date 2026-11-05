# Formato de localização

- `Game/*.xlsx` e `Dialog/**/*.xlsx`: colunas com sufixo `_EN` alimentam a coluna irmã sem o sufixo. O mapeamento registra planilha, ID, campo e coordenada. IDs duplicados usam coordenadas e revisão conservadora na próxima mudança.
- `Data/*.xlsx`: abas com cabeçalho `k` preservam a chave e registram as células de valor. `Name.xlsx` fornece fragmentos de nomes. `chara_talk.xlsx` e `god_talk.xlsx` usam a primeira coluna como chave e guardam falas nas colunas nomeadas.
- `Text`, `Data` e `Widget`: arquivos UTF-8 são lidos por linha. O escritor mantém os bytes das linhas não editadas, inclusive separadores CRLF e diretivas.
- `Text/version.txt`: o bloco editorial existente é reinserido antes do tópico de atualização. Se o ponto de inserção mudar, o build exige revisão do formato.
- `lang.ini`: configuração do idioma do mod existente. Regras de gramática e fontes fazem parte do comportamento do jogo.
- OOXML: membros intactos são copiados byte a byte. Apenas as células de destino são editadas no XML da planilha. Fórmulas em células de destino e estruturas de linha desconhecidas encerram a operação.
- Fontes compiladas `Data/Source`, conteúdo de executáveis, retratos, vozes e extensões de outros mods ficam fora do parser.
