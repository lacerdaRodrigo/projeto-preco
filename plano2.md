QUero fazer um plano gravar , rodei Geladeira Brastemp BRM46MK Frost Free 385 Litros Duplex Inox - 110V
e ainda esta aparecendo lojas no google direto , pq ? e algumas estÃ£o indo direto para a loja , que e o certo ok. https://www.google.com/search?q=Geladeira+Brastemp+BRM46MK+Frost+Free+385+Litros+Duplex+Inox+-+110V+Brastemp+Uau+CAIXA olah esse link https://www.google.com/search?q=Geladeira+Brastemp+BRM46MK+Frost+Free+385+Litros+Duplex+Inox+-+110V+Brastemp+Latam+Pass outro. pq essas lojas ficaram defora ? Por que outras lojas ficaram de fora
Em revisÃ£o (2) â quase bateu, confira
Lojas Nosso Lar
match 0.78
Geladeira Brastemp Duplex BRM46MBANA Inverter 385L Branca Frost Free com Smart Cold - 110V
similaridade textual 0.78
Zema
match 0.74
Geladeira Brastemp Frost Free Duplex 375 Litros Cor Branca com EspaÃ§o Adapt
similaridade textual 0.74  esse match e necessario mesmo ? 
+ Thought: 3.1s
âExplore Task â Explore matching system code
â³ 22 toolcalls Â· 49.1s
ctrl+x down view subagents
+ Thought: 5.4s
AnÃ¡lise
Por que ficaram de fora?
- Score 0.78 (Lojas Nosso Lar) e 0.74 (Zema) estÃ£o abaixo do limiar de aceitaÃ§Ã£o (0.85)
- Caem na faixa REVISAR (0.60â0.85) â nÃ£o viram SKU, nÃ£o entram no ranking, sÃ³ aparecem na tabela "Em revisÃ£o"
- SÃ³ lojas com score â¥ 0.85 viram oferta confirmada e abrem direto na loja
Problemas detectados:
Loja	Score	Problema
Lojas Nosso Lar	0.78	Modelo BRM46MBANA â  BRM46MK â sÃ£o produtos diferentes
Zema	0.74	375L â  385L + modelo diferente â capacidade divergente deveria ter descartado
A Zema (375L) passou pelos gates do pipeline mesmo tendo capacidade diferente? Preciso verificar se o gate de capacidade (etapa 5) falhou â talvez a string "375" vs "385" nÃ£o esteja sendo extraÃ­da/normalizada corretamente pra esses tÃ­tulos.
Match 0.74 Ã© necessÃ¡rio? â NÃ£o. Ã outro produto (375L). Se o gate de capacidade tivesse funcionado, teria ido pra DESCARTA direto.
O que quer fazer?
1. Ajustar thresholds â baixar limiar_aceita? (risco: falso-positivo)
2. Corrigir gate de capacidade â 375L vs 385L deveria descartar, nÃ£o ir pra revisÃ£o
3. Adicionar veto de modelo â BRM46MBANA tem part-number diferente de BRM46MK, deveria barrar
4. SÃ³ aceitar do jeito que estÃ¡ â revisÃ£o manual Ã© o comportamento esperado