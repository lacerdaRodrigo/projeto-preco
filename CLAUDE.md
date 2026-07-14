# Smart Price Tracker

Sistema **pessoal** para comparar preços de produtos em lojas online BR, buscar cupons e alertar quando vale a pena comprar. Planejamento completo em `docs/SMART-PRICE-TRACKER.md` (anexar só ao planejar).

## Stack
- **Worker** Python 3.12 · **Persistência atrás do contrato Repositório**: V1 = **SQLite** via `sqlite3` da stdlib (queries parametrizadas); Fase 2 = **Supabase Postgres** (+ SQLAlchemy/Alembic), trocando só o adaptador · httpx (async) · Typer+Rich (CLI) · pytest
- **Web** Next.js/React na Vercel · **Supabase Auth** (login) · agendamento por **GitHub Actions** (cron + `workflow_dispatch`)
- Mesmo worker roda local ou na nuvem — só muda a config por ambiente.

## Como rodar / testar
Pré-requisito (Debian/Ubuntu): pacote de sistema `python3.12-venv` — sem ele `python3 -m venv` falha com *"ensurepip is not available"* (`sudo apt install python3.12-venv`).

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"          # projeto + ferramentas de dev
.venv/bin/pytest                           # testes
.venv/bin/ruff check src tests             # lint/format
.venv/bin/mypy src                         # tipos
.venv/bin/bandit -c pyproject.toml -r src  # segurança do código
.venv/bin/pip-audit                        # CVEs nas dependências
```

## Regras que não posso quebrar
- **Nunca** compra automática nem preenche checkout.
- Preço comparado = **preço final** = item + frete − cupom − cashback (nunca só vitrine).
- Núcleo (`domain/`, `application/`) não importa rede, BD nem UI.
- Cada loja é um **coletor plugável** (`adapters/coletores/`), mesma interface; não acoplar loja ao núcleo.
- Só comparar ofertas com score de matching ≥ 0.85.
- Todo preço rastreável (URL + timestamp). Idempotente: rodar 2x não duplica.
- Preferir API oficial > scraping. Respeitar robots.txt/ToS e rate-limit por loja.
- Multiusuário (eu + noiva): todo dado isolado por `conta_id` (RN16); esse isolamento é teste de **segurança**, não só de dados.
- Supabase: `service_role key` só no worker/backend (ignora RLS) — **nunca** no frontend. No front, só a `anon key`, protegida por RLS.
- Sem segredo hardcoded (usar `.env` local / GitHub Secrets / Vercel Env Vars).
- **Nunca logar** segredo nem dado pessoal (e-mail do login, CEP) — nem em stack trace/console (LGPD).
- Dado vindo de loja é **não-confiável**: validar, escapar antes de renderizar (XSS) e usar queries parametrizadas (nunca SQL concatenado). Preço absurdo/nulo → `coletor_degradado`, não grava (RN12).

## Convenções de trabalho
- Docs enxutos: histórico/PRs/mudanças ficam no git, **não** em `.md`. Ver [[docs-enxutos-git-nao-md]].
- Começar pela fatia vertical da V1: 1 produto → 2 lojas → matching → preço final → histórico → CLI.

## Entrada = título do produto (decisão firme)
- **A entrada principal é o TÍTULO** que o Rodrigo cola (ex.: "Smartphone Motorola Moto G67 5G 256GB..."). Ele já pesquisa no Google e traz o **modelo específico**; o sistema extrai o que importa (marca, modelo/part-number, atributos-chave) e busca por isso. Plano detalhado em `plano.md`.
- **Sem consultas vagas nem rota de descoberta** ("mesa 06 cadeiras", "notebook bom e barato"): o roteador é só uma **guarda de especificidade** — título vago → pede um específico, não inventa busca. Divisão de responsabilidade: o Rodrigo garante o dado de entrada; o sistema extrai e busca.
- **Extrator por URL/página fica PARQUEADO (off), não apagar.** Ler o JSON-LD do link funciona em lojas que expõem dado estruturado, mas as grandes (Mercado Livre, Magazine Luiza) bloqueiam a leitura (desafio/403). Código mantido em `adapters/extratores/pagina.py` pra uso futuro; quando só houver a URL, o **slug** vira título (`extrair_do_slug`). Quem enfrenta o anti-bot das lojas é o coletor Serper na etapa de busca, não a gente.
