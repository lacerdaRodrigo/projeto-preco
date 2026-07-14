# Front — Smart Price Tracker (Next.js)

Interface web (design "Clean" do `docs/DESIGN-SUMMARY.md`) rodando em **localhost**.
Fala com o **adaptador web FastAPI** (`src/interface/api.py`), que reusa o mesmo
núcleo Python do CLI — zero regra de negócio duplicada no front.

## Arquitetura

```
[Next.js :3000]  ->  [FastAPI :8000]  ->  [núcleo Python: BuscarProduto + SQLite]
  React / telas       API sobre o core     (mesma lógica do comando `pesquisa-preco`)
```

## Como rodar (dois terminais)

**1. Backend (API):** na raiz do projeto:
```bash
.venv/bin/pip install -e ".[web]"          # 1ª vez: instala FastAPI/uvicorn
.venv/bin/uvicorn interface.api:app --reload --port 8000
```

**2. Front (Next.js):** dentro de `web/`:
```bash
npm install        # 1ª vez
npm run dev        # abre em http://localhost:3000
```

Abra **http://localhost:3000**. Para mudar a URL da API, defina `NEXT_PUBLIC_API_URL`.

## Telas desta fatia

- **Produtos** (`/`) — lista os produtos monitorados.
- **Cadastrar** (`/cadastrar`) — formulário (nome, categoria, marca, palavras obrigatórias/proibidas).
- **Dashboard** (`/produtos/[id]`) — comparação por loja (barras), **Buscar agora** (dispara a coleta real via Google Shopping), link direto pra cada loja.

Próximas telas (do DESIGN-SUMMARY): Login (Supabase Auth), Alertas, Configurações,
evolução de preço 30 dias.
