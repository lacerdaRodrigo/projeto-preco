# Smart Price Tracker

Sistema **pessoal** que monitora e compara preços de produtos em lojas online brasileiras, busca cupons/cashback, calcula o **preço final real** e avisa quando vale a pena comprar.

> **Status:** 🧭 Planejamento — projeto em design, ainda sem código.
> **Fonte da verdade:** [`SMART-PRICE-TRACKER.md`](./SMART-PRICE-TRACKER.md) (PRD completo).

## O que resolve

Não é só "comparar preço agora", e sim responder: **"onde e quando comprar para gastar menos?"** — casando o mesmo produto entre lojas com títulos diferentes, considerando frete (por CEP), PIX, cupom e cashback, e guardando histórico para detectar promoção real vs. cilada.

## Como funciona

Três peças, cada uma no seu forte:

| Peça | Papel |
|------|-------|
| **Web (Vercel)** | Cadastrar produtos + dashboard de comparação |
| **Supabase (Postgres + Auth)** | Banco único (local e nuvem) + login |
| **GitHub Actions** | Pipeline agendada que roda o worker de coleta |

```
cadastra na web → grava no Supabase → cron (ou "Buscar agora") aciona o worker
→ coleta nas lojas → matching → preço final → grava → alerta por e-mail
```

O **mesmo worker (Python)** roda local ou na nuvem — só muda a config por ambiente.

## Stack planejada

Python 3.12 (worker) · Supabase Postgres · Next.js/React na Vercel · GitHub Actions · pytest + SonarCloud.
Detalhes em [PRD §21](./SMART-PRICE-TRACKER.md#21-tecnologias-recomendadas).

## Rodar / testar

> ⏳ Ainda não há código. Quando a V1 existir, os comandos de instalação, execução e teste entram aqui.

## Roadmap

V1 núcleo local + Supabase → V2 nuvem + web → V3 analítico/IA → V4 inteligência → V5 mobile → V6 multiusuário.
Ver [PRD §24](./SMART-PRICE-TRACKER.md#24-roadmap-v1--v6).

## Documentação

- [`SMART-PRICE-TRACKER.md`](./SMART-PRICE-TRACKER.md) — PRD: produto, arquitetura, dados, testes, segurança.
- [`CLAUDE.md`](./CLAUDE.md) — contexto e regras para IAs trabalharem no projeto.
