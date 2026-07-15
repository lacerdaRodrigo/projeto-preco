// Cliente da API (o adaptador web FastAPI). Base configurável por env; padrão
// aponta pro backend local. Nada de regra aqui — só fala HTTP com o núcleo.
const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function json(caminho, opcoes) {
  const resp = await fetch(`${BASE}${caminho}`, {
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    ...opcoes,
  });
  if (!resp.ok) {
    const corpo = await resp.text();
    throw new Error(`API ${resp.status}: ${corpo}`);
  }
  return resp.json();
}

export const api = {
  listarProdutos: () => json("/api/produtos"),
  obterProduto: (id) => json(`/api/produtos/${id}`),
  cadastrarProduto: (dados) =>
    json("/api/produtos", { method: "POST", body: JSON.stringify(dados) }),
  rastrear: (dados) =>
    json("/api/rastrear", { method: "POST", body: JSON.stringify(dados) }),
  buscarAgora: (id) =>
    json(`/api/produtos/${id}/buscar`, { method: "POST" }),
  arquivarProduto: async (id) => {
    const resp = await fetch(`${BASE}/api/produtos/${id}`, { method: "DELETE" });
    if (!resp.ok) throw new Error(`API ${resp.status}`);
  },
};

export function reais(valor) {
  const n = Number(valor);
  return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}
