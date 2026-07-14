# Plano — Busca de Produtos (rota de ataque)

> Origem: sessão de planejamento (14/07/2026). Complementa `SMART-PRICE-TRACKER.md` §13 (busca) e §14 (matching); regras RN01–RN16 continuam valendo.
> **Este documento vai para o PC onde o código já existe: adapte ao que está implementado (contrato Coletor, matcher, repositórios) — não crie caminho paralelo nem reescreva o que funciona.**

## 1. Problema

Buscar produto exige entender o que o usuário colou. Pré-modelar banco de atributos por categoria (notebook, TV, airfryer, sanduicheira...) não escala e trava quando a categoria não existe.

## 2. Decisão

**Entrada = o TÍTULO do produto que EU colo.** Eu já pesquiso no Google e trago o **modelo específico** que quero (ex.: "Smartphone Motorola Moto G67 5G 256GB 12GB Câmera 50MP..."); o sistema tira do título o que importa e busca por isso.

**Divisão de responsabilidade:** eu (Rodrigo) garanto o **dado de entrada correto e específico**; o sistema **extrai o que importa e busca**. Uma esteira única, com enriquecimento progressivo. **Schema de categoria é acelerador opcional, nunca pré-requisito** — a precisão do matching acompanha a especificidade do INPUT, não a existência de molde.

**Regra de ouro: o sistema nunca trava por "categoria sem schema".**

**Fora de escopo (V1): descoberta / consultas vagas** — "mesa 06 cadeiras", "notebook bom e barato". Eu não faço pergunta solta; trago o modelo definido. A descoberta é comigo, no Google. (Ideia parqueada; se um dia entrar, vira rota à parte, sem mexer no que funciona.)

> **Extrator por URL/página — PARQUEADO (off):** ler o JSON-LD do link funciona em lojas que expõem dado estruturado (GTSM1, Zema...), mas as grandes (Mercado Livre, Magazine Luiza) **bloqueiam** a leitura automática (desafio/403) — briga que não é nossa. O código fica em `adapters/extratores/pagina.py` pra uso futuro; o **caminho ativo é o título**. Quando só sobra a URL, o **slug** dela vira o título (`adapters/extratores/texto.py::extrair_do_slug`).

## 3. Pipeline (um fluxo, uma rota: RASTREAR)

1. Colo o **título** do produto (o modelo específico que já escolhi).
2. **Extrator** (automático, sem formulário): título → `{categoria, marca, modelo/part-number, ean?, atributos}`.
3. **Roteador = guarda de especificidade**: tem âncora (EAN, part-number, ou marca+modelo)? → segue. Vago demais (só categoria) → avisa "seja específico", não inventa busca. **Não bifurca em descoberta.**
4. Busca via **serper.dev `/shopping`** (`gl=br`, `hl=pt-br`) — query pela **âncora + specs-chave**, nunca pela string inteira (string cheia over-constringe: nenhuma loja titula igual).
5. **Matching por portões** (§5).
6. **Ranking** por preço final — mostra **TODAS** as lojas que casaram, da mais barata pra mais cara (não 1 só; podem ser 3, 4, 5+).

### Exemplo — "Smartphone Motorola Moto G67 5G 256GB 12GB (4GB RAM + 8GB RAM Boost) Câmera 50MP Sony Lytia 600 Tela 1.5K AMOLED 120Hz"
- Extração: categoria=smartphone, marca=Motorola, modelo=**Moto G67** (âncora), {armazenamento:256GB, ram:12GB, rede:5G, camera:50MP, tela:AMOLED 120Hz}. Confiança ALTA.
- Query enxuta: `"Motorola Moto G67 256GB"` → matching filtra (descarta G85, 128GB, capa, seminovo) → aceitos viram SKU + snapshot na hora → ranking por preço.

## 4. Extrator (título → atributos)

- **V1: heurística determinística** — regex de part-number, unidades (GB/SSD/polegadas/litros/watts/MP), dicionário de marcas e categorias.
- Palavras de ruído/intenção ("barato", "promoção", "melhor") saem da query — não são atributos. Se o título só tiver isso (sem marca/modelo), o roteador **pede um título específico** (não há rota de descoberta no V1).
- Categoria **conhecida** no mapa `categoria → atributos-chave` (é CONFIG, não código — PRD §11): usa atributos-chave no matching.
- Categoria **desconhecida** (ex.: sanduicheira): **modo genérico** = marca + modelo + similaridade textual. Funciona sem schema (ex.: "Sanduicheira Mondial S-15" casa por Mondial + S-15).
- Já existe (base): extrator de título (`extrair_do_titulo`) e de slug (`extrair_do_slug`) puxam título + EAN. **Falta** a heurística de marca/part-number/atributos — é o próximo degrau.
- Futuro (V3): LLM como extrator universal (só título→atributos, resposta cacheada), atrás da MESMA interface do heurístico.

## 5. Matching — novo portão de part-number

Inserir portão entre o EAN e os vetos (ordem de curto-circuito do §14):

1. EAN bate → aceita (1.0).
2. **NOVO: part-number/modelo bate (ex. A515-45-R2A3, Moto G67) → score ~0.95, quase-certeza.**
3. Palavras proibidas/obrigatórias (veto): "capa", "película", "seminovo"...
4. Atributo-chave diverge (256GB ≠ 128GB · 8GB ≠ 16GB) → descarta.
5. Similaridade textual → score final. Limiares RN04 inalterados (≥0.85 aceita · 0.6–0.85 revisar · <0.6 descarta).

Exemplo de filtragem esperada (busca do Acer A515-45-R2A3):

| Resultado | Decisão | Motivo |
|---|---|---|
| KaBuM "A515-45-R2A3 8GB 512GB" | ✅ aceita | part-number + atributos batem |
| Magalu "A515-45 Ryzen5 8GB 512GB" | ✅ aceita (~0.88) | sem sufixo, atributos batem |
| Amazon "A515-45-R74Z Ryzen7 16GB" | ❌ descarta | atributo-chave diverge — o falso-positivo clássico |
| ML "Capa Case Neoprene Aspire 5" | ❌ descarta | palavra proibida + sanidade de preço |
| CB "A515-45-R2A3 Seminovo" | ❌ descarta/revisar | palavra proibida "seminovo" |

Cada erro corrigido na fila "revisar" vira caso no dataset rotulado (PRD §23).

## 6. Coletor serper `/shopping` (meta-coletor)

- Implementa o **contrato Coletor existente** (`buscar(descricao, cep) → OfertaBruta[]`) — **já existe** em `adapters/coletores/google_shopping.py`.
- Google Shopping agrega N lojas em 1 chamada → 1 crédito cobre descoberta que custaria N coletores. **É ele quem enfrenta o anti-bot das lojas grandes** (por isso não brigamos com ML/Magalu no extrator).
- Preço retornado é **VITRINE** (sem PIX/cupom; frete às vezes vem) → `frete_cotado=false`; o **preço final** refina depois, só nos top-N, via coletores por loja (quando existirem).
- Ruído esperado: acessórios, seminovos, patrocinados → quem filtra é o matching, não o coletor (coletor continua "burro", PRD §12).
- `SERPER_API_KEY` via `.env`/secrets — nunca hardcoded.

## 7. Orçamento serper (2.500 créditos)

- **Cache por query normalizada** (TTL de horas): repetir busca não queima crédito e mantém idempotência.
- 1 busca de produto = 1 chamada `/shopping` (sem paginação por padrão).
- Contador de créditos usados persistido + alerta em ~80%.
- Testes usam **fixtures JSON gravadas** — teste nunca gasta crédito (PRD §23).

## 8. Dados (zero tabela por categoria)

- `PRODUTO.atributos` JSON (já previsto no schema): `{ram:8, ssd:512}` e `{litros:4}` convivem na mesma coluna.
- Mapa `categoria → atributos-chave` = arquivo de config; adicionar categoria = 1 linha, não migration.
- Toda oferta com URL + timestamp (rastreabilidade); snapshot só se mudou (RN11).

## 9. Ordem de implementação (adaptar ao que já existe no código)

1. ✅ Coletor serper `/shopping` no contrato Coletor + fixtures (feito: `google_shopping.py`).
2. ✅ Extrator base de título/slug + EAN (feito: `adapters/extratores/`).
3. **Extrator heurístico**: enriquecer o de título → categoria/marca/part-number/atributos + confiança + testes.
4. **Portão de part-number** no matcher + casos novos no dataset rotulado.
5. **Roteador = guarda de especificidade** (tem âncora? senão pede título específico).
6. **Query pela âncora** (marca+modelo+specs-chave), não pela string inteira.
7. Cache de query + contador de créditos.
8. CLI: `buscar "<título>"` mostrando as decisões do matching e o ranking com todas as lojas.

## 10. Critérios de aceite

- "Motorola Moto G67 5G 256GB..." → extrai marca/modelo/256GB; ranking só com score ≥0.85; descarta G85/128GB/capa/seminovo.
- "Acer A515-45-R2A3 8GB 512GB" → part-number vira âncora; descarta R74Z/16GB.
- "mesa 06 cadeiras" (vago) → o sistema **NÃO** busca: pede um título específico (ex.: "Conjunto Madesa Lily Mesa 4 Cadeiras Preto"). Descoberta é comigo, no Google.
- "Sanduicheira Mondial S-15" (categoria sem schema) → funciona em modo genérico (marca+modelo).
- Rodar 2× a mesma busca → não duplica nada (RN11) e a 2ª usa cache (0 crédito).
- Nenhuma compra automática (RN07); nenhum segredo no código; testes não batem em serviço real.

---

## Nota de vocabulário — o que "pipeline" quer dizer neste documento

**Pipeline = esteira de etapas encadeadas** — como uma linha de montagem: o dado entra numa ponta, cada estação faz **uma** transformação e passa o resultado adiante, até sair pronto na outra ponta.

```
"Smartphone Motorola Moto G67 5G 256GB ..."   ← entra o título (eu colo)
        │
   [1. EXTRATOR]      → vira dado estruturado: {marca: Motorola, modelo: Moto G67, armazenamento: 256GB...}
        │
   [2. ROTEADOR]      → guarda: tem âncora? sim → segue (não bifurca)
        │
   [3. BUSCA serper]  → vira lista de ofertas brutas (Magalu, Amazon, ML...)
        │
   [4. MATCHING]      → filtra: descarta G85, 128GB, capa, seminovo
        │
   [5. RANKING]       → sai o resultado: TODAS as lojas que casaram, menor preço primeiro
```

Cada etapa **não sabe nada das outras** — o extrator só extrai, o matching só filtra. É isso que deixa cada peça simples de escrever, testar e trocar isoladamente (ex.: trocar a heurística do extrator por LLM sem mexer no resto).

**"Pipeline único" (§2):** é **uma esteira só** — a mesma p/ smartphone, notebook, mesa ou sanduicheira. O roteador (etapa 2) **não bifurca**: é só uma guarda que confere se o título é específico o bastante pra buscar (descoberta é fora de escopo).

A palavra aparece em mais dois lugares, mesmo sentido, escalas diferentes:
- **§5 — "pipeline de portões" do matching:** mini-esteira dentro da etapa 4 (EAN → part-number → vetos → atributos → similaridade), onde cada portão pode encerrar o processo antes do próximo.
- **PRD — "pipeline agendada":** a esteira inteira rodando sozinha no cron do GitHub Actions p/ todos os produtos ativos, em vez de disparada manualmente.
