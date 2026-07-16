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

  const comLojas = produtos ? produtos.filter((p) => p.num_lojas > 0) : [];
  const economia = comLojas.reduce((soma, p) => {
    if (!p.preco_referencia || !p.melhor_preco) return soma;
    const dif = Number(p.preco_referencia) - Number(p.melhor_preco);
    return soma + (dif > 0 ? dif : 0);
  }, 0);

  return (
    <main className="container">
      <div className="cabecalho">
        <h1>Produtos monitorados</h1>
        <div className="espaco" />
        <Link href="/cadastrar" className="btn">+ Novo produto</Link>
      </div>
      <p className="subtitulo">
        Cole o título, o sistema busca nas lojas BR e valida se é o produto certo.
      </p>

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
          <div className="card stat">
            <div className="rotulo">Com ofertas encontradas</div>
            <div className="valor">{comLojas.length}</div>
          </div>
          <div className="card stat">
            <div className="rotulo">Economia vs. referência</div>
            <div className="valor" style={{ color: economia > 0 ? "var(--verde)" : undefined }}>
              {reais(economia)}
            </div>
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

              <MiniComparacao produto={p} />

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

// O elemento central de clareza: no card, ver de relance "cadastrado × melhor".
function MiniComparacao({ produto }) {
  const referencia = produto.preco_referencia ? Number(produto.preco_referencia) : null;
  const melhor = produto.melhor_preco ? Number(produto.melhor_preco) : null;

  if (!melhor) {
    return <div className="mini-vazio">Aguardando busca — abra e clique em “Buscar agora”.</div>;
  }

  const escala = Math.max(melhor, referencia || 0) || 1;
  const economia = referencia !== null ? referencia - melhor : null;

  return (
    <div className="mini-comp">
      <div className="mini-linha">
        <div className="mini-topo">
          <span className="rot">Melhor preço</span>
          <span className="pill-lojas">{produto.num_lojas} loja{produto.num_lojas > 1 ? "s" : ""}</span>
          <span className="val" style={{ color: "var(--verde)" }}>{reais(melhor)}</span>
        </div>
        <div className="mini-track">
          <span className="best" style={{ width: `${(melhor / escala) * 100}%` }} />
        </div>
      </div>

      {referencia !== null && (
        <div className="mini-linha">
          <div className="mini-topo">
            <span className="rot">Cadastrado</span>
            <span className="val">{reais(referencia)}</span>
          </div>
          <div className="mini-track">
            <span className="ref" style={{ width: `${(referencia / escala) * 100}%` }} />
          </div>
        </div>
      )}

      {economia !== null && (
        <span className={`mini-eco${economia >= 0 ? "" : " acima"}`}>
          {economia >= 0 ? "▼" : "▲"} {reais(Math.abs(economia))} {economia >= 0 ? "abaixo" : "acima"} do cadastrado
        </span>
      )}
    </div>
  );
}
