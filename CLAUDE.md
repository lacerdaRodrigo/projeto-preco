# Smart Price Tracker

Sistema **pessoal** para comparar preços de produtos em lojas online BR, buscar cupons e alertar quando vale a pena comprar. Planejamento completo em `SMART-PRICE-TRACKER.md` (anexar só ao planejar).

## Stack
- **Worker** Python 3.12 · **Supabase Postgres** (local+nuvem; SQLite só p/ testes offline) · httpx (async) · SQLAlchemy+Alembic · Typer+Rich (CLI) · pytest
- **Web** Next.js/React na Vercel · **Supabase Auth** (login) · agendamento por **GitHub Actions** (cron + `workflow_dispatch`)
- Mesmo worker roda local ou na nuvem — só muda a config por ambiente.

## Como rodar / testar
- (preencher quando o código existir: comando de run, de teste, de lint)

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

## Convenções de trabalho
- Docs enxutos: histórico/PRs/mudanças ficam no git, **não** em `.md`. Ver [[docs-enxutos-git-nao-md]].
- Começar pela fatia vertical da V1: 1 produto → 2 lojas → matching → preço final → histórico → CLI.
