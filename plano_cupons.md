Plano â Carteira: descobrir cupons + apagar/editar + cupons por produto

Contexto (por que isto existe)

O motor de cupom/cashback jÃ¡ funciona (domÃ­nio + repo + cÃ¡lculo _decompor + escadinha na UI), mas a carteira Ã© 100% manual. O Rodrigo nÃ£o quer digitar cupom: os cupons devem vir direto do buscador e jÃ¡ entrar na comparaÃ§Ã£o de preÃ§o, automaticamente. Cashback continua manual (Ã© elegibilidade pessoal â vocÃª sabe se tem Inter/MÃ©liuz). TrÃªs frentes, sendo a principal a descoberta automÃ¡tica de cupons:

1. Descobrir cupons automaticamente por loja e aplicar direto no preÃ§o (sem passo manual de carteira).
2. Apagar/editar carteira (cashback manual; fixar/remover cupom descoberto).
3. Cupom por produto na UI â mostrar QUAL cupom incidiu + status, na escadinha (RN13).

Ressalva firme (define o desenho da descoberta): o CLAUDE.md proÃ­be tocar checkout, entÃ£o garantia 100% ("esse cÃ³digo dÃ¡ desconto agora?") nÃ£o dÃ¡ sem a loja. NÃ£o prometemos isso. Mas validamos por SINAIS (decisÃ£o do Rodrigo â opÃ§Ã£o "sinais de confianÃ§a", sem tocar a loja), como os prÃ³prios sites de cupom fazem:
- Validade: se a fonte informa data de expiraÃ§Ã£o â jÃ¡ venceu? â expirado.
- Frescor da fonte: linguagem "verificado hoje / funcionou para X%" nos snippets (Cuponomia, Pelando, MÃ©liuz).
- CorroboraÃ§Ã£o: mesmo cÃ³digo aparece em â¥N fontes recentes â mais confianÃ§a.

Cada cupom descoberto vira um registro com status (provÃ¡vel vÃ¡lido/expirado/nÃ£o confirmado) + confianÃ§a (alta/mÃ©dia/baixa) + evidÃªncias. Aplica automÃ¡tico no preÃ§o (o Rodrigo quer direto), mas o desconto e o preÃ§o vÃ£o marcados "nÃ£o confirmado" â mesma filosofia do preÃ§o de vitrine jÃ¡ existente (preco_confirmado=False, "mostrar marcado Ã© melhor que sumir"). Regras da aplicaÃ§Ã£o automÃ¡tica: sÃ³ aplica o melhor cupom provÃ¡vel vÃ¡lido (nÃ£o aplica expirado; nÃ£o confirmado/1-fonte fica listado como "possÃ­vel", nÃ£o desconta) â pra nÃ£o inventar preÃ§o falso-baixo. Nada de checkout. Prefere API > scraping; Serper Ã© o proxy educado (padrÃ£o do coletor de preÃ§o); dado externo Ã© nÃ£o-confiÃ¡vel (valida formato do cÃ³digo, escapa).

Abordagem

PeÃ§a A â Descoberta automÃ¡tica de cupons, aplicada direto (o principal)

Porta nova (nÃºcleo nÃ£o importa rede): application/buscadores.py â BuscadorDeCupons (Protocol) async buscar(loja: str) -> list[CupomDescoberto] + o tipo CupomDescoberto (puro): Cupom + status (StatusCupom: provavel_valido/expirado/nao_confirmado) + confianca (alta/media/baixa) + evidencias: list[str]. Adaptador plugÃ¡vel (mesma ideia do Coletor).

Adaptador adapters/cupons/serper_llm.py â BuscadorCuponsSerperLLM:
- Serper web search q="cupom {loja} desconto", gl=br (reusa httpx+Serperganic (tÃ­tulo/snippet/link/date) + answerBox.
- LLM extrai dos snippets (padrÃ£o de adapters/classificadores/llm.py): JSON [{codigo, tipo, desconto, validade, sinal_frescor}]. Parse defensivo; valida cÃ³digo ^[A-Z0-9]{4,20}$;
dedup por cÃ³digo agregando as fontes.
- Status por sinais (determinÃ­stico): validade no passado â expirado; â¥2 fontes ou frescor recente â provavel_valido (confianÃ§a pelo nÂº de fontes); 1 fonte sem frescor â nao_confirmado. evidencias = ["visto em N sites", "Cuponomia: verificado hoje", "expira 31/12"].
- Falha (sem chave/HTTPâ 200/JSON invÃ¡lido) â [] (degrada limpo). Nunca t

Cache + persistÃªncia (pra nÃ£o descobrir a cada busca): a tabela cupom ganha colunas origem (manual/descoberto), status, confianca, evidencias (JSON), descoberto_em. O buscador faz upsert dos descobertos por loja. TTL (ex.: 24h): busca de novo sÃ³ se o registro da loja estiver velho. Assim o custo Serper/LLM Ã© 1Ã/loja/dia, reaproveitado entre produtos.

IntegraÃ§Ã£o na busca (aplica direto): em buscar_agora/_ofertas_guardadas,garante cupons frescos (descobre se stale) e o _decompor aplica o melhorprovavel_valido (manual tem prioridade; senÃ£o o descoberto). O desconto e o preÃ§o saem marcados quando vieram de cupom descoberto (cupom_confirmado=False), a UI avisa. expirado
nÃ£o aplica; nao_confirmado fica listado, nÃ£o desconta.

Onde roda a descoberta: no buscar_agora (lazy, com cache) â orquestrado o o BuscadorDeCupons como porta (igual coletor/classificador). SemSERPER_API_KEY/NVIDIA_API_KEY â sem descoberta (sÃ³ carteira manual, como hoje).

CLI (opcional): cupom-descobrir "<loja>" mostra o que achou + status (e popula o cache).

Fora do V1 (anotar): descoberta de cashback (MÃ©liuz atrÃ¡s de login) fica pra depois. V1 descobre sÃ³ cupons; cashback continua manual.

PeÃ§a B â Gerir a carteira (cashback manual + remover cupom)

- Porta+SQLite: RepositorioCupom.remover(loja, codigo) e RepositorioCashpplication/repositorios.py + adapters/repositorios/sqlite.py, DELETE ...WHERE).
- API: DELETE /api/carteira/cupom (loja+codigo) e DELETE /api/carteira/cashback (loja+fonte).
- Front (carteira/page.js): o cashback continua com form de adicionar (Ã©ma lista por loja mostrando os descobertos (cÃ³digo, desconto, status,evidÃªncias), com ð pra remover um que nÃ£o presta. Form manual de cupom vira opcional/secundÃ¡rio (nÃ£o Ã© mais o caminho principal). Editar cashback = re-salvar (upsert jÃ¡ atualiza).
- CLI (opcional): cupom-remover "<loja>" "<codigo>".

PeÃ§a C â Cupom por produto na UI (RN13)

- _decompor (application/buscar_produto.py) jÃ¡ recebe do avaliar_melhor_cupom/avaliar_melhor_cashback o objeto aplicado â hoje descarta. Passar a devolver Cupom|None +
Cashback|None.
- OfertaRankeada + OfertaView ganham cupom_codigo, cupom_status, cupom_confirmado: bool, cashback_fonte. _ofertas_guardadas preenche.
- Front (produtos/[id]/page.js, Escadinha): nomear e marcar â "â cupom N confirmado)", "â cashback via inter". Chip por status. PreÃ§o final com cupom descoberto herda o aviso "nÃ£o confirmado".

Arquivos (criar/alterar)

- Novos: src/application/buscadores.py (porta BuscadorDeCupons + CupomDescoberto/StatusCupom), src/adapters/cupons/__init__.py + serper_llm.py (adaptador),
tests/.../test_buscador_cupons_serper_llm.py.
- Alterar: src/application/repositorios.py (+remover, +campos descoberto no contrato), src/adapters/repositorios/sqlite.py (colunas
origem/status/confianca/evidencias/descoberto_em na tabela cupom; +DELETsrc/application/buscar_produto.py (injeta BuscadorDeCupons; _decompor devolve objetos + flag confirmado; OfertaRankeada), src/interface/api.py (injeta buscador no buscar_agora com cache/TTL; DELETE; OfertaView campos cupom; _ofertas_guardadas),
src/interface/cli.py (comandos opcionais), web/app/carteira/page.js, webweb/app/lib/api.js, web/app/globals.css.

Testes (nascem junto; nunca batem em serviÃ§o real)

- Descoberta: Serper + LLM mockados (respx) â snippets fixos viram list[CupomDescoberto]; cÃ³digo malformado filtrado; status por sinais (validade passada â expirado; â¥2 fontes/frescor â provavel_valido; 1 fonte sem frescor â nao_confirmado); HTTP erro/sem chave â [].
- Cache/aplicaÃ§Ã£o: buscador fake injetado â cupom descoberto entra no cÃ¡do=False; expirado nÃ£o aplica; re-busca dentro do TTL nÃ£o re-chama o buscador (cache).
- Remover: repo remove a linha; DELETE na API some da listagem.
- Por produto: _decompor/OfertaView expÃµem cupom_codigo+cupom_status.
- RegressÃ£o: 218 testes atuais continuam verdes; ruff/mypy limpos.

VerificaÃ§Ã£o (ponta a ponta)

1. .venv/bin/pytest Â· ruff check src tests Â· mypy src verdes.
2. Localhost: buscar um produto com loja KaBuM â o cupom descoberto jÃ¡ a, marcado "nÃ£o confirmado" + status â Carteira mostra os descobertos porloja, com ð pra remover um ruim. (precisa SERPER_API_KEY+NVIDIA_API_KEY+rede.)
3. Sem as chaves: sem descoberta (sÃ³ carteira manual/cashback), resto no

Notas / dÃ­vidas

- ValidaÃ§Ã£o Ã© por SINAIS, nÃ£o garantia â status+confianÃ§a dizem "provÃ¡veno checkout, que nÃ£o tocamos). Cupom descoberto aplica marcado "nÃ£oconfirmado"; sÃ³ o melhor provavel_valido desconta (nÃ£o inventa preÃ§o falso-baixo).
- Custo/latÃªncia: descoberta Ã© 1 Serper + 1 LLM por loja; cache com TTL 1Âª vez numa loja Ã© mais lenta.
- Carteira nÃ£o Ã© escopada por conta_id (RN16) â diferente de produto/sku. V1 tem 1 conta, entÃ£o ok; anotar pro multiusuÃ¡rio (V6).
- Gotcha de banco: servidor lÃª precos.db relativo ao cwd (uvicorn de src/ â src/precos.db; CLI da raiz â ./precos.db).
- primeira_compra continua sem aplicar no cÃ¡lculo (fora do escopo deste

Plano aprovado. ComeÃ§ando a implementar. Vou montar um todo pra rastrear e comeÃ§ar pela fundaÃ§Ã£o (porta + tipos).