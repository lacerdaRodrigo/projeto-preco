"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, reais } from "./lib/api";

export default function Produtos() {
  const [produtos, setProdutos] = useState(null);
  const [erro, setErro] = useState(null);

  function carregar() {
    api.listarProdutos().then(setProdutos).catch((e) => setErro(e.message));
  }
  useEffect(carregar, []);

  async function arquivar(id, nome) {
    if (!confirm(`Arquivar "${nome}"? Ele some da lista (o histórico fica guardado).`)) return;
    try {
      await api.arquivarProduto(id);
      setProdutos((ps) => ps.filter((p) => p.id !== id));
    } catch (e) {
      setErro(e.message);
    }
  }

  return (
    <main className="container">
      <div className="cabecalho">
        <h1>Produtos monitorados</h1>
        <div className="espaco" />
        <Link href="/cadastrar" className="btn">+ Novo produto</Link>
      </div>

      {erro && (
        <div className="card" style={{ color: "var(--vermelho)" }}>
          Não consegui falar com a API ({erro}). O backend está rodando na porta 8000?
        </div>
      )}

      {produtos && produtos.length > 0 && (
        <div className="stats">
          <div className="card stat">
            <div className="rotulo">Produtos monitorados</div>
            <div className="valor">{produtos.length}</div>
          </div>
        </div>
      )}

      {!produtos && !erro && <p className="vazio">Carregando…</p>}

      {produtos && produtos.length === 0 && (
        <div className="vazio">
          Nenhum produto ainda. <Link href="/cadastrar" className="link-loja">Cadastre o primeiro</Link>.
        </div>
      )}

      {produtos && produtos.length > 0 && (
        <div className="grid">
          {produtos.map((p) => (
            <div className="card produto-card" key={p.id}>
              <h3>{p.nome}</h3>
              <div className="categoria">
                {p.categoria}{p.marca ? ` · ${p.marca}` : ""}
              </div>
              {p.preco_referencia && (
                <div className="categoria" style={{ marginTop: 6 }}>
                  referência: <strong>{reais(p.preco_referencia)}</strong>
                </div>
              )}
              <div className="rodape">
                <Link href={`/produtos/${p.id}`} className="btn secundario">Ver ofertas</Link>
                <button className="btn fantasma" onClick={() => arquivar(p.id, p.nome)}>
                  Arquivar
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
