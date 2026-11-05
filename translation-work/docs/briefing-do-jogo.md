# Elin · briefing de localização

## Ylva e o lugar do jogador

Elin pertence à série Eternal League of Nefia e retoma o mundo de Elona. Em North Tyris, a aventura mistura exploração de masmorras, sobrevivência, criação de itens e construção de um lar. O terreno inicial pode evoluir de abrigo para comunidade com moradores e visitantes. A campanha aborda a história dos humanos e dos Elea, mas o jogo permite que cada pessoa dê prioridade a atividades diferentes. Uma fala sobre a próxima etapa da história e um aviso sobre o estoque do lar podem aparecer na mesma sessão, com funções bem distintas. [Steam](https://store.steampowered.com/app/2135150/Elin/) · [Ylvania](https://ylvania.org/elin_dev_e.html)

## Pessoas, lugares e grupos

A base local contém cenas para Fiama, Loytel, Ashland, Farris, Melilith e Kettle, entre outros. Comece pelas planilhas `Dialog/Drama/_main.xlsx` e `_tutorial.xlsx` para ver como o jogo apresenta o lar e ensina suas rotinas. Nas planilhas de personagens, use o identificador da cena para localizar falas relacionadas. As linhas de script ao redor do diálogo podem mostrar quem entra em cena, quem recebe uma resposta ou para onde a conversa salta. O nome do arquivo aponta para o assunto da cena, mas interlocutores e personagens citados podem mudar entre linhas.

A religião tem presença mecânica e narrativa. Histórias e textos devocionais dão contexto a divindades recorrentes como Ehekatl, Mani e Lulwy. Cruze `Game/Religion.xlsx`, `Data/god_talk.xlsx` e os textos de fé e livros para distinguir voz divina, nome de culto e rótulo de interface. As tabelas `Faction`, `Area` e `Chara` ajudam a verificar filiação, tipo de local e personagem. Use o glossário já existente como registro das decisões do projeto.

## Exploração, lar e interface

- **Lar e assentamento.** Compare políticas, zonas de trabalho, moradores e mobiliário em `Area`, `HomeResource`, `Element` e `Thing`. Um nome de zona pode reaparecer como comando curto.
- **Aventura e sobrevivência.** Cruze nomes de itens e criaturas, efeitos e logs em `Thing`, `Chara`, `Element`, `Stat` e `Game`. Efeitos podem ser temporários e várias mensagens combinam o sujeito com partes de frases em tempo de execução.
- **Documentos e humor.** Livros religiosos, jornais, cartas, ajuda e falas de mascotes têm vozes e funções diferentes. O jornal pode misturar orientação de jogo e ficção. `Text/version.txt` inclui notas da versão e um bloco editorial preexistente do projeto.
- **Nomes gerados.** Em `Alias` e `Word_mix`, a ordem dos fragmentos, os números de peso, os marcadores de combinação e os prefixos de variável têm efeito no resultado. Verifique o conjunto de padrões antes de propor uma mudança linguística. [Guia oficial de localização](https://docs.google.com/document/d/e/2PACX-1vSj8lHcRFhFU_332eYCAlft9u1hkTlb5efUqVPsLQTtOPA79Tgh3FvNfJz9edvy0jI616BdiLidyxdz/pub)

## Quem fala, a quem e sobre quem

O mapeamento entrega arquivo, planilha, campo e chave nativa quando disponível. Leia as linhas anteriores e seguintes para confirmar quem fala, quem é tratado como segunda pessoa e quem é descrito. Para uma fala em primeira pessoa, uma identificação confirmada de Fiama pode orientar a concordância da personagem. Para uma fala dela sobre Loytel, verifique separadamente a identidade do referente. Com personagem do jogador ou NPC gerado, investigue as seleções feitas pelo motor e o que o jogo garante sobre a identidade antes de resolver concordância fixa. O catálogo não atribui gênero pelo nome de uma aba, de uma chave ou de um retrato.

Preserve `#1`, `#2`, diretivas de condição, links e sequências de controle. O guia oficial descreve o uso de formas de terceira pessoa do inglês em `Game.xlsx`, além de opções do idioma e substituições de tom. A configuração PT-BR existente foi preservada. Confira em contexto nomes próprios de apoiadores e textos que a fonte inglesa apresenta em CJK. Algumas células antigas têm fallback explícito para a exibição original.

## Limites da referência

A fonte editável da migração tem como referência **EA 23.352**. A instalação inspecionada é **EA 23.355** e já inclui tabelas compiladas em `Package/_Elona/Data/Source`. O texto e as cenas disponíveis localmente podem mudar entre essas versões. O briefing descreve evidências da fonte e materiais oficiais. A apresentação dos diálogos, acentos e glifos em jogo ainda depende de teste no cliente.

Fontes locais deste briefing: `EN/Package/Lang/EN/{Game,Dialog,Text,Data,Widget}`, em particular `Dialog/Drama`, `Game/Religion.xlsx`, `Game/Faction.xlsx`, `Data/god_talk.xlsx` e `Text/version.txt`. [Página da desenvolvedora](https://ylvania.org/elin_dev_e.html) · [Comunicados na Steam](https://steamcommunity.com/app/2135150/allnews/?l=english)
