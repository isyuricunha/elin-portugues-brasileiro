# Fluxo de tradução

1. Execute o preflight descrito em [README](../README.md).
2. Leia [o briefing](briefing-do-jogo.md) e as decisões registradas no [glossário](glossario-ptbr.md).
3. Use `resume` para localizar pendências. Compare o contexto do arquivo com as linhas vizinhas e confirme quem fala, quem ouve e quem é descrito.
4. Preencha os lotes ou aplique alterações com `apply`. Rode `check` e registre progresso em Git. Os commits de lotes ficam separados de uma publicação.
5. Ao receber uma fonte nova, inspecione `update-sources --dry-run` antes de aceitar o diff. Revise entradas que perderam a aprovação ou mudaram de contexto.
6. Com a revisão encerrada, rode `build` e `verify-output`. Teste a pasta do mod numa instalação de teste. A publicação usa somente o pacote verificado.
