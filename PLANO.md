# Plano de execução — Smart Price Tracker

Este é o **mapa de construção**: em que ordem montar o projeto, do zero até o fim.
Complementa o [`SMART-PRICE-TRACKER.md`](./docs/SMART-PRICE-TRACKER.md) (o PRD, que diz *o quê* e *o porquê*);
aqui é o *como* e o *em que ordem*. Marque `[x]` conforme avança.

## Princípio-guia
**Fatia vertical fina primeiro.** Fazer 1 produto atravessar o sistema inteiro (loja → matching → preço → banco → CLI) antes de generalizar. Cada peça nasce com teste. Só depois adiciona mais lojas e sobe pra nuvem.

## Decisões já tomadas
- **1ª loja:** Mercado Livre, via **API oficial** (sem scraping) — regra API-first (PRD §25).
- **Banco no começo:** **SQLite** (simples, local); migra pro **Supabase** na Fase 2.
- **Código em PT-BR**, nomes claros. Testes com **pytest**.
- **Nunca** commit/push sem o Rodrigo pedir.
- **Mapa PRD:** Fase 1 = a "primeira fatia" do V1 (§24: 1 loja + SQLite). O V1 completo do PRD (2–3 lojas + Supabase) começa na Fase 1 e fecha no início da Fase 2.

---

## Estado atual  ✅
- [x] Documentação organizada e sincronizada (README, PRD, CLAUDE.md)
- [x] `.gitignore` (protege `.env`) e `.env.example` (modelo, sem segredo)
- [x] Esqueleto de pastas do V1 (`src/`, `tests/`, `docs/`)
- [x] Repositório git iniciado (branch `organizar-casa`)
- [x] **Fase 0 e Fase 1 completas** — a fatia vertical roda local (cadastrar → buscar → ranking).
- [x] **Comparação real multi-loja via Google Shopping (Serper)** — `buscar` traz N lojas BR de uma vez. **105 testes verdes**; ruff/mypy/bandit limpos.

---

# O que falta para a V1

A **fatia vertical já roda local** (Fase 1 ✅). Daqui pra frente há três níveis, do mais imediato ao mais completo.

---

## ✅ FEITO: comparação real via Google Shopping (Serper)

**Objetivo:** digitar um produto (Echo Dot, iPhone, geladeira...) e ver o **preço em várias lojas BR de uma vez** — sem anti-bot, sem proxy, sem OAuth. O [Serper](https://serper.dev) devolve os resultados do Google Shopping (preço + loja) via API, e a camada gratuita (**2.500 buscas, sem cartão**) sobra pra uso pessoal.

**Por que este caminho** (e não os anteriores): o ML fechou a API; as lojas VTEX bloqueiam por reputação de IP. O Google Shopping, via Serper, **agrega N lojas** e resolve o anti-bot por baixo — é o encaixe certo pro nosso contrato `Coletor`.

### Passo a passo (na ordem, sem chute)

- [x] **1. (Rodrigo) Criar a chave** — conta grátis em [serper.dev](https://serper.dev). Feito.
- [x] **2. Ver o formato real ANTES de codar** — resposta real capturada: `{searchParameters, shopping:[...], credits}`; cada item traz `title`, `source` (a loja!), `link`, `price`, `imageUrl`, `productId`. Sem frete/EAN/estoque.
- [x] **3. Guardar a chave com segurança** — `SERPER_API_KEY` no `.env`; `config.py` lê e **mascara no `repr`** (não vaza em log).
- [x] **4. Construir `ColetorGoogleShopping`** (`adapters/coletores/google_shopping.py`) — honra o contrato; POST pro Serper; parseia o preço BR tratando o **espaço não-quebrável (`\xa0`)**, o sufixo **" agora"** e o **ponto de milhar**. Erros tipados como os outros.
- [x] **5. Tratar o "1 coletor = N lojas"** — coletor marca `agrega_lojas=True`; o maestro agrupa por **loja de origem** (`(loja_id, source)`), `SKU` ganhou `loja_origem` (unicidade `(produto, loja, loja_origem)`), `OfertaRankeada.loja` mostra a loja de origem. Uma busca → N SKUs, um por loja.
- [x] **6. Testes** — fixture real do Serper + `respx`; parser puro + preço BR cobertos; teste do maestro provando "agregador vira N SKUs". **105 testes verdes**; ruff/mypy/bandit limpos.
- [x] **7. Rodar ao vivo** — `buscar 1` traz **14 lojas BR de uma vez** (ML, Shopee, KaBuM!, Magalu, Carrefour, eBay...), ordenadas pela mais barata. 🎉

**Pronto:** você digita um produto e vê o preço dele em várias lojas BR, ordenado pela mais barata. ✅

> **Custo real medido:** `num=40` gasta **2 créditos** (não 1). Com 2.500 grátis dá ~1.250 buscas amplas. Dá pra baixar `_NUM_RESULTADOS` se quiser economizar.
>
> **Ressalva capturada (limpeza futura):** o Google às vezes rotula a mesma loja de formas diferentes (`Mercado Livre` vs `mercadolivre.com.br`) e **rotaciona** quais vendedores mostra a cada busca. Efeito: a lista de SKUs cresce ao longo do tempo (lojas novas + histórico de preço — o que a gente quer), mas com **duplicatas de loja**. A idempotência da *lógica* está correta (teste com dado idêntico não duplica); o crescimento vem do dado externo mudar de verdade. Melhoria futura: **normalizar o `source`** (mapear apelidos → loja canônica) pra fundir esses SKUs.

### Refinamento: descobrir no Serper → **verificar na página do produto** (link + preço real)
Descoberto testando ao vivo: o `link` do shopping **expira** (cai na home do Google) e o **preço do Google Shopping é aproximado/desatualizado** (ex.: KaBuM! R$489 no Google vs **R$449,90** real). Então o coletor foi ajustado pra:
1. **Descobrir** no Serper (quais lojas têm + achar a URL) — shopping + 1 busca orgânica por loja.
2. **Achar a página do PRODUTO** (não lista/busca): só aceita link cujo **domínio bate com a loja** E que é **página de produto** (`_e_link_de_produto`). Lista/categoria → descarta a loja.
3. **Verificar preço E nome na própria página** (`_extrair_da_pagina`: JSON-LD schema.org / meta Open Graph). Loja que não expõe o preço no HTML (algumas VTEX carregam via JS) → **descartada**. O **título passa a vir da página** (produto real), corrigindo o título ruidoso/errado do Google (ex.: "S25" numa página de S26) — e o matching passa a rodar sobre o produto verdadeiro.
4. **URL limpa** (`_limpar_url`): tira parâmetros de rastreio (`srsltid`, `utm_*`) → URL curta e canônica, que abre e copia sem quebrar.

**Resultado:** menos lojas por busca, mas cada uma com **link certo + preço real + nome certo** (validado ao vivo: Echo Dot 5 → KaBuM! R$449,90 etc.; Galaxy S26 Ultra → 4 lojas, todas S26 Ultra, match 1.00). Custo: ~1 crédito/loja + 1 leitura de página/loja.

> **Cruzou um princípio de propósito:** ler a página é **scraping** (a regra é "API-first, scrape é último recurso"). Decisão consciente do Rodrigo pra ter preço correto; é leitura educada (UA de navegador, 1 req/loja, com `rate_limit`). Melhorias futuras: mapa de apelidos de loja; parser de preço p/ VTEX (via API `sku/stockkeepingunitbyid` em vez de HTML).

---

Os três níveis abaixo seguem valendo (blindagem + nuvem):

### 1. Rodando com dado REAL de loja BR  ✅✅
- [x] **Coletor KaBuM!** (`adapters/coletores/kabum.py`, API pública de catálogo, **sem token**) — loja BR real (tech/games, da lista do §12). `pesquisa-preco buscar <id>` traz **preço real ao vivo** (com preço à vista/PIX, estoque, frete grátis, vendedor 1P vs marketplace). É o coletor padrão do CLI.
- [x] **Coletor sandbox** (`--demo`, dummyjson) — pra testar o encanamento sem depender de loja.

**Mercado Livre** — coletor pronto e correto, mas **descartado por ora**: o ML fechou a busca pública atrás de policy/OAuth (todos os endpoints de produto dão **403 "PolicyAgent"**, mesmo com token — confirmado por vários devs). Só volta se o ML aprovar acesso de parceiro. O código fica guardado pra esse dia.

> Lição real capturada: a busca da loja é **ampla e ruidosa** (buscar "SSD Kingston 1TB" traz SSDs de outras marcas). O **matcher filtra** — é o coração do sistema, exatamente como o §14 previu. Precisão de modelo (ex.: RTX 4060 ≠ 5060) se resolve com `palavras_obrigatorias`.

### 2. Blindar a V1 antes de crescer  (Fase 1.5 — PRD §27)
- [ ] **pre-commit**: `gitleaks` (segredo) + `ruff` + `bandit` a cada commit.
- [ ] **CI** (`.github/workflows/ci.yml`): `pytest` + lint travando o merge.
- [ ] **Branch protection** na `main`.

### 3. Fechar a V1 completa do PRD  (Fase 2 — 2–3 lojas + nuvem)
- [x] **Múltiplos coletores** — KaBuM! (API própria, **confiável**, sem anti-bot) + **coletor VTEX genérico** (`ColetorVTEX(dominio, loja_id, nome)`, serve milhares de lojas VTEX).
  - **Realidade do anti-bot:** as lojas VTEX (Americanas, Casas Bahia, e mesmo mid-size) bloqueiam a API pública por **reputação de IP** — respondem no começo e passam a dar HTTP 400/403 depois de algumas batidas, independente de User-Agent ou cliente HTTP. Por isso o padrão do `buscar` é **só KaBuM!**; as VTEX ficam em `--vtex` (melhor esforço).
  - **Para usar VTEX de verdade (futuro):** precisa de infra anti-bloqueio — proxies residenciais rotativos e/ou `curl_cffi`/curl-impersonate (imita o fingerprint TLS de navegador). Fica para quando/se valer a pena.
- [ ] **Cupons e cashback** entrando no preço final (§15/§16) — a fórmula já os prevê.
- [ ] **Migrar SQLite → Supabase Postgres** (só troca o adaptador; liga **RLS por `conta_id`**).
- [ ] **Alertas por e-mail** (queda de preço, cupom novo, volta de estoque).

**Detalhe de cada fase abaixo.** Web (Vercel) + coleta agendada (GitHub Actions) já são V2 (Fase 2, parte final).

---

## Fase 0 — Fundação  (setup, antes de qualquer regra)  ✅
Deixar o projeto "instalável e testável". Sem isso, nada roda.
- [x] `pyproject.toml` — deps (`httpx`, `typer`, `rich`) + dev (`pytest`, `ruff`, `mypy`, `bandit`, `pip-audit`), Python 3.12
- [x] Criar ambiente virtual e instalar as deps (`.venv`)
- [x] `src/config.py` — lê o `.env` (segredo fora do código; `repr` mascara o token)
- [x] `pytest` verde (5 testes de config) + lint/tipo/segurança limpos

**Pronto:** `pytest`, `ruff`, `mypy`, `bandit` e `pip-audit` passam num projeto instalável.

## Fase 1 — V1 (fatia vertical): 1 loja, núcleo local em SQLite
O coração do sistema, provado ponta a ponta com **uma** loja. Ordem do mais puro (sem I/O) ao mais externo. Cada peça com teste em `tests/`.

- [x] **1. Domínio** — entidades puras (sem rede/banco) — §9/§10/§11/§16:
  - `Produto`: nome, categoria, marca, modelo, EAN, `preco_referencia`, `palavras_obrigatorias/proibidas`, `modelos_equivalentes`, `atributos` (JSON)
  - `OfertaBruta`: título, preço, `preco_avista`, `desconto_pix`, frete, `frete_cotado`, prazo, parcelas, `em_estoque`, vendedor, `vendedor_oficial`, `url`
  - `SKU` (oferta já casada ao produto, 1 por loja — RN01) e `SnapshotPreco` (série temporal; url+timestamp — RN11 + rastreabilidade)
  - **Fórmula do preço final à vista** (ordem do §16): base à vista/PIX → cupom → cashback → +frete se cotado (RN02/RN09). No V1 sem cupom/cashback (entram na Fase 2), mas a ordem já os prevê.
  - _(pendente, migrado p/ o item 2)_ Mapa de config **categoria → atributos-chave** (curado à mão) — §11: é config do matching, entra junto dele.
- [x] **2. Matching** (§14) — pipeline de portões: EAN → palavra proibida/obrigatória → normalização → atributos-chave → similaridade → **score (≥0.85 aceita · 0.6–0.85 revisar · <0.6 descarta, RN04)**. Devolve **o porquê** da decisão. Limiares/dicionários em **config**, não código. **Semear `tests/matching_dataset/`** com pares rotulados "é/não é" (regressão do matcher). O mais testado do sistema.
- [x] **3. Coletor Mercado Livre** (§12/§13) — honra o contrato `buscar(descricao, cep) -> [OfertaBruta]`; sem estado; **vazio ≠ erro**; erros tipados (`LojaIndisponivel`→retry, `ProdutoNaoEncontrado`→vazio, `ColetorQuebrado`→`coletor_degradado`, não grava; RN08/RN12). Testado contra JSON **gravado** (`tests/fixtures/`), nunca a loja ao vivo.
- [x] **4. Repositório SQLite** (§9 contratos) — interfaces por intenção (`salvar_snapshot_se_mudou`, `ultimo_snapshot`…); **idempotente** (RN11); **todo acesso filtra por `conta_id`** desde já (1 conta fixa, RN16); guarda url+timestamp. Atrás do contrato → troca por Supabase depois sem mexer no núcleo.
- [x] **5. Caso de uso `BuscarProduto`** (§13) — o "maestro": carrega produto+config → coletor → matching → preço final → grava idempotente; escopado por conta, resiliente por loja.
- [x] **6. CLI** (`typer` + `rich`) — `cadastrar`, `listar` e `buscar` (ranking por preço final à vista). Comando `pesquisa-preco`.

**Pronto:** pelo terminal você cadastra 1 produto, roda a busca e vê o preço final calculado e salvo — rodando de novo não duplica (RN11). ✅ **A fatia vertical roda local.** (71 testes verdes; lint/tipo/segurança limpos.)

## Fase 1.5 — Blindagem: CI + pre-commit  (PRD §27)
Travar qualidade e segurança antes de crescer.
- [ ] **pre-commit**: `gitleaks` (segredo) + `ruff` + `bandit` a cada commit
- [ ] **CI mínima** (`.github/workflows/ci.yml`): `pytest` + lint a cada push/PR (trava merge)
- [ ] **Branch protection** na `main` (CI verde antes de merge)

**Pronto quando:** um commit com segredo ou teste quebrado é barrado automaticamente.

## Fase 2 — V2: nuvem + web
Tirar do "só no meu PC" e ganhar tela e automação (PRD §24). Fecha o V1 completo do PRD (2–3 lojas + Supabase) e avança.
- [ ] Migrar o repositório de SQLite → **Supabase Postgres** (só troca o adaptador; liga **RLS por `conta_id`**, §27)
- [ ] Adicionar 1–2 coletores a mais (fecha os "2–3 coletores" do V1; matching passa a valer de verdade com variedade)
- [ ] **Cupons** e **cashback** entrando no preço final (PRD §15, §16)
- [ ] **Alertas** por e-mail (`queda_preco`, `cupom_novo`, `volta_estoque`, `promo_suspeita`/RN06); anti-spam por transição (PRD §18)
- [~] **Web** (Next.js/Vercel): cadastro + dashboard — **começou em localhost** (ver abaixo). Falta Supabase + Supabase Auth (login) pra publicar.
- [ ] **GitHub Actions**: coleta agendada (`cron`) + "Buscar agora" (`workflow_dispatch`)

**Pronto quando:** a coleta roda sozinha na nuvem e você acompanha pela web, sem ligar o PC.

### Web em localhost (fatia inicial ✅) — Next.js + FastAPI
Desenho: **adaptador web FastAPI** (`src/interface/api.py`, irmão do `cli.py`, reusa o núcleo) + **front Next.js** (`web/`, design "Clean"). Instruções em `web/README.md`.
- [x] API FastAPI: `GET/POST /api/produtos`, `GET /api/produtos/{id}`, `POST /api/produtos/{id}/buscar` (coleta real). CORS pro `:3000`.
- [x] Front Next.js: telas **Produtos**, **Cadastrar**, **Dashboard** (comparação por barras + "Buscar agora" + link direto da loja).
- [ ] Telas restantes do DESIGN-SUMMARY: Login (Supabase Auth), Alertas, Configurações, evolução de preço 30 dias.
- [ ] Trocar SQLite → Supabase e publicar (Vercel + backend).

## Fases 3 a 6 — evolução (detalhe no PRD §24)
O produto muda de papel: **Comparador → Vigia → Conselheiro**.
- [ ] **V3 — Analítico + IA leve:** gráficos de evolução, ranking, economia acumulada, IA no matching difícil.
- [ ] **V4 — Inteligência:** melhor momento de compra, promoção falsa por IA, aprende sua preferência.
- [ ] **V5 — Mobile:** app consumindo o mesmo Supabase.
- [ ] **V6 — Multiusuário:** contas separadas (o gancho `conta_id` já existe desde o V1).

---

## Como trabalhamos em cada peça
1. Escrevo a peça **em PT-BR**, pequena e focada.
2. Escrevo o **teste** que prova a regra dela.
3. Rodo, mostro verde, explico o *porquê* de forma simples.
4. Só sigo pra próxima peça quando a atual está de pé.

> Regra de ouro dos testes (PRD §23): **nunca** bater na loja real em teste — usar respostas gravadas (fixtures/fakes).
