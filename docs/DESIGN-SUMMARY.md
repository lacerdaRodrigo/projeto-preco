# Smart Price Tracker — Resumo do Design (Frontend)

> Complementa o `SMART-PRICE-TRACKER.md` (PRD). Este documento registra o que foi prototipado na interface, decisões de design e o que ainda depende do backend (seções 9–20 do PRD).

**Status:** protótipo de front-end navegável, com dados simulados (mock). Sem integração real com Supabase, worker Python, coletores ou GitHub Actions.

> **Atualização 15/07/2026 — o front virou app real.** A direção "Clean" foi implementada em **Next.js** (`web/`), integrada à API FastAPI (não é mais mock). Telas ativas: **Produtos** (lista com card de mini-comparação "cadastrado × melhor preço" + nº de lojas), **Cadastrar** (título-first: cola o título, o backend extrai a identidade), **Dashboard do produto** (comparação por loja com linha de referência, chips confirmado/vitrine, e o **funil visível** "por que outras lojas ficaram de fora"). A API `/api/produtos` devolve `melhor_preco`/`num_lojas` pro card. **Ainda não implementado:** Login, Alertas, Configurações e o gráfico de evolução 30 dias (precisa de endpoint de histórico — os snapshots já existem no banco).

---

## Arquivos gerados

| Arquivo | Descrição |
|---|---|
| `Smart Price Tracker.dc.html` | Direção 1 — visual escuro, estilo painel financeiro (fintech). |
| `Smart Price Tracker - Ledger.dc.html` | Direção 2 — conceito "recibo/ledger" (papel, carimbos, monoespaçado). Descartada pelo usuário. |
| `Smart Price Tracker - Clean.dc.html` | **Direção final, em uso.** Visual claro, navbar padrão, comparação por barras. |

Todos são arquivos `.dc.html` autocontidos (abrem direto no navegador).

> ⚠️ Os arquivos `.dc.html` **não estão versionados neste repositório** — foram gerados na sessão de design e ficaram fora do repo. Este resumo é o registro do que foi prototipado. Ao versionar os protótipos, salvá-los aqui e remover este aviso.

---

## Direção final: "Clean"

- **Paleta:** fundo bege claro `#f7f6f2`, cartões brancos, borda `#e5e1d5`, texto tinta `#211f18`/`#8f8874`, acento verde-petróleo `#1f6f78` (trocável via Tweaks).
- **Tipografia:** Sora (títulos/números) + Source Sans 3 (corpo).
- **Elemento central de clareza:** barras de comparação — "Cadastrado" vs. "Melhor preço" no card do produto, e um gráfico de barras por loja no dashboard com uma **linha de referência** marcando o preço cadastrado atravessando todas as barras.
- **Responsivo:** navbar e grids se adaptam abaixo de 860px (colunas viram 1, ações empilham).

## Telas implementadas

1. **Login** — tela única, sem lógica real de autenticação (visual do Supabase Auth).
2. **Produtos** (lista) — grid de cards, busca por nome, estatísticas (economia acumulada, produtos monitorados, alertas), badge de status por produto.
3. **Dashboard do produto** — preço cadastrado × melhor preço, comparação por loja (ranqueada, com linha de referência), evolução de preço 30 dias (SVG), alertas do produto.
4. **Cadastro de produto** — formulário (nome, categoria, marca, EAN, preço de referência, palavras obrigatórias/proibidas). Ao salvar, o produto entra em estado "aguardando busca".
5. **Alertas** — feed de todos os alertas de todos os produtos, com marcar como lido e link para o produto.
6. **Configurações** — CEP destino, moeda/fuso (somente leitura), toggles de cashback elegível (Cliente Inter, AME, Méliuz).

## Interatividade simulada

- **"Buscar agora"** (card ou dashboard): dispara um estado "buscando…" e, após ~1.4s, gera de 2 a 4 lojas aleatórias com preço, frete, prazo, cupom e cashback fictícios — imitando o fluxo real de coleta (RF04-06, RF19).
- Produto recém-cadastrado nasce sem lojas ("aguardando busca") até rodar a primeira busca — reflete RN15/RF19 na experiência.
- Toast de confirmação para ações (produto cadastrado, busca concluída, config salva).

## O que é fiel ao PRD vs. o que é só maquete

**Fiel ao conceito (seções 6, 11, 16, 18, 19 do PRD):**
- Campos obrigatórios/opcionais de produto (RF01-03).
- Comparação sempre mostrando preço cadastrado ao lado do preço encontrado.
- Frete, cupom, cashback exibidos por loja.
- Dashboard de economia acumulada e evolução de preço.

**Simplificado ou não implementado (depende do worker/backend):**
- **RN02** — o preço por loja exibido é bruto; o cálculo líquido (à vista + frete − cupom − cashback) da seção 16 ainda não é aplicado literalmente linha a linha.
- **RN04/RN13/RN14** — matching por EAN/score e "melhor cupom automático" são só decorativos (dados já vêm prontos do mock).
- **RN06** — badge de "promoção suspeita" é fixo por mock, não calculado a partir da mediana de 30 dias.
- **RF17** — arquivar/reativar produto ainda não existe na UI.
- Tipo de alerta `promo_relampago` não está entre os simulados.
- Multiconta (RN16), login real, scraping, Supabase, GitHub Actions — fora do escopo de um protótipo de front-end.

## Próximos passos sugeridos

1. Aplicar a fórmula de preço final (seção 16) linha a linha na tela de comparação.
2. Tela de arquivar/reativar produto (RF17).
3. Handoff para desenvolvimento (worker Python + Supabase) seguindo a arquitetura da seção 9.
