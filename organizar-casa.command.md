---
description: Organiza docs (README/arquivo-de-contexto/ADRs) e persiste preferências, mantendo tudo enxuto e o histórico no git. Agnóstico de ferramenta de IA.
---

# Organizar a casa: docs enxutos + preferências persistidas

Você vai (1) ler meu PERFIL abaixo e persistir minhas preferências, (2) configurar minhas preferências de trabalho e (3) limpar e reorganizar a documentação deste repositório. NÃO edite nada antes de me mostrar um plano do que muda em cada arquivo.

Este prompt é AGNÓSTICO DE FERRAMENTA (Claude Code, Gemini CLI, Codex, Cursor, Copilot, etc.). Dois conceitos são universais, mas o mecanismo concreto depende da ferramenta em uso:

- **ARQUIVO DE CONTEXTO DO AGENTE** = o markdown que a ferramenta carrega automaticamente com instruções pro agente. O CONCEITO é universal; o NOME varia:
  - Claude Code → `CLAUDE.md` · Gemini CLI → `GEMINI.md` · OpenAI Codex → `AGENTS.md` · Cursor → `.cursor/rules/*` (também lê `AGENTS.md`) · GitHub Copilot → `.github/copilot-instructions.md` · Windsurf → `.windsurf/rules`.
  - Detecte qual já existe no repo e use esse. Se nenhum existir, PERGUNTE a ferramenta; na dúvida, use **`AGENTS.md`** (padrão cross-tool mais portátil). Daqui pra frente chamo esse arquivo de **ACA** (Arquivo de Contexto do Agente).
- **MEMÓRIA PERSISTENTE** = onde ficam preferências que atravessam sessões. É uma capacidade OPCIONAL: nem toda ferramenta tem.
  - Se a ferramenta TEM memória (ex.: Claude Code) → use a memória dela.
  - Se NÃO tem → fallback: persista as preferências num arquivo VERSIONADO — no próprio ACA (seção "Preferências") ou em `docs/preferences.md`. Nunca perca a preferência só porque a ferramenta não tem memória.

---

## PERFIL DO USUÁRIO — PREENCHER (semente da memória)

> Preencha uma vez na sua matriz e mantenha guardada. Deixe em branco o que não se aplica; ignore linhas vazias.
> Regra do que entra: só o que é ÚTIL, NÃO óbvio e ATRAVESSA sessões (não dá pra descobrir no código nem no git).

**Quem sou eu** (tipo `user`)
- Papel/nível:
- O que estou aprendendo / quero evoluir:
- Como gosto que você me explique (ex.: sempre o porquê, direto ao ponto, com exemplos):

**Stack e estilo favoritos** (tipo `feedback`)
- Linguagens/frameworks preferidos:
- Convenções de código (nomes, padrões, arquitetura que sigo):
- Ferramentas de teste/lint/build que uso:

**Regras invioláveis** — "sempre / nunca" (tipo `feedback`)
- Nunca faça:
- Sempre faça:
- Sempre me PERGUNTE X antes de fazer Y:

**"Porquês" que não quero re-explicar** (tipo `feedback`/`project`)
- Decisões/escolhas minhas e o motivo:

**Gotchas que me fazem perder tempo** (tipo `feedback`)
- Armadilhas recorrentes / pegadinhas de ambiente:

**Ponteiros externos** (tipo `reference`)
- Dashboards, tickets, docs, URLs úteis:

---

### Passo 0 — Persistir o PERFIL
- Leia cada campo PREENCHIDO acima e persista (1 fato por unidade, tipo indicado, com Why e How to apply quando for feedback/project).
  - Ferramenta COM memória → salve na memória (ex.: Claude Code: 1 arquivo por fato + índice MEMORY.md).
  - Ferramenta SEM memória → grave na seção "Preferências" do ACA ou em `docs/preferences.md`.
- Ignore campos em branco. Se já existir registro equivalente, ATUALIZE em vez de duplicar.
- Não persista nada que seja derivável do código ou do git.
- Isto é POR PROJETO: rode este passo em cada projeto novo onde quiser essas preferências.

## Princípios (valem em TODO projeto)
1. Docs enxutos: NÃO documentar o que o git já registra. Histórico de mudanças, PRs, branches, diffs e evolução ficam no git — nunca em `.md`.
2. Antes de manter um trecho num doc, pergunte: "dá pra descobrir lendo o código ou o `git log`?" Se sim, remova.
3. Ao identificar melhoria, mudança de arquitetura, regra de negócio (nova/alterada) ou exclusão, atualize os docs afetados no mesmo trabalho — só os que a mudança toca, não todos por reflexo.
4. Documentação existe para o que NÃO é derivável do código: o "porquê", convenções não-óbvias, gotchas, contratos entre módulos/times.
5. Salvar ≠ salvar tudo. Salve o que é útil e NÃO óbvio. O óbvio o código já conta.
6. Mantenha vivo: diga uma vez, salve, reuse — e ATUALIZE ou APAGUE quando mudar. Memória/doc desatualizado é pior que não ter; ao mudar um fato, corrija o registro existente em vez de acumular.

## Passo 1 — Configurar preferências de trabalho
Persista estas preferências (memória se a ferramenta tiver; senão, ACA/`docs/preferences.md`). Fatos tipo "feedback", 1 por unidade, com Why e How to apply. Se já existirem parecidas, atualize em vez de duplicar:
- "Docs enxutos, histórico no git": não salvar histórico/PRs/mudanças/estrutura de código em `.md`.
- "Manter docs sincronizados": ao mudar arquitetura/regra/escopo, atualizar os docs afetados sem eu pedir.
- "ACA sem limite de linhas": em projetos grandes pode ser longo; o que importa é ser útil e não-óbvio, não curto.
- "Salvar só o útil e não-óbvio": preferir persistência estruturada a `.md` solto; nunca salvar o que é derivável do código/git.

## Passo 2 — Reorganizar os docs

### README.md (para HUMANOS)
- Reescreva para: o que é, como instalar, rodar e testar, principais comandos, arquitetura em 1 parágrafo, links úteis.
- REMOVA histórico / changelog manual / lista de PRs / descrição de branches — vive no git.
- Meta: legível em poucos minutos.

### ACA — arquivo de contexto do agente (para a IA) — SEM limite de linhas
- Use o nome correto da ferramenta em uso (`CLAUDE.md`/`GEMINI.md`/`AGENTS.md`/etc.; ver topo). Não crie um `CLAUDE.md` fixo se a ferramenta não for Claude.
- Só o que me ajuda a trabalhar e NÃO é óbvio pelo código: como rodar/testar/buildar, convenções não-óbvias, arquitetura a respeitar, regras de negócio invioláveis, gotchas.
- Remova histórico, PRs e qualquer coisa derivável do git/código.

### Monorepo / projetos grandes
- Vários pacotes/apps? UM ACA na raiz (visão geral + regras globais) e ACAs menores por pacote (`apps/api/`, `apps/web/`, `apps/mobile/`) com o específico daquele pacote. Nunca um arquivo monolítico na raiz.
- Documente os CONTRATOS entre módulos (o que um time precisa saber do outro), não o interior de cada um.

### Mobile (se houver)
- No ACA do pacote mobile, registre o que trava e não está no código: rodar em simulador/emulador e device físico; setup iOS (Xcode/CocoaPods/signing) e Android (SDK/Gradle/keystore); env vars e flavors/schemes; comandos de build/release; gotchas de plataforma.

### Decisões importantes
- O "porquê" de escolhas de arquitetura vira ADR curto em `docs/adr/` (contexto → decisão → consequência, ~15 linhas). Não recriar changelog manual.

## Passo 3 — Segurança antes de apagar (repos grandes)
- **Se NÃO houver git neste repo**: pare e me avise ANTES de apagar qualquer coisa. Sem git, o histórico não é recuperável — não remova histórico de docs sem minha confirmação explícita (ou sugira `git init` primeiro).
- Antes de remover, mostre um RESUMO do que existe em cada doc grande, separando "manter / mover pra ADR / apagar".
- Só apague depois que eu aprovar. Com git, o removido continua recuperável.

## Idempotência (rodar de novo)
- Este comando pode ser rodado várias vezes no mesmo repo. Se um doc já está enxuto e organizado, NÃO reescreva — apenas reporte "já está ok" e siga.
- Só proponha mudanças onde houver de fato o que enxugar/corrigir. Não gere diff cosmético nem reformate por reformatar.

## Entrega
1. Plano primeiro (o que sai, o que fica, o que vira ADR, por arquivo).
2. Após aprovação, aplique.
3. Commit numa branch separada, mensagem clara. NÃO commitar direto na main.
