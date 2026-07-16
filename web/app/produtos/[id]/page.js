"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api, reais } from "../../lib/api";

function quando(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export default function Dashboard() {
  const { id } = useParams();
  const router = useRouter();
  const [dados, setDados] = useState(null);
  const [erro, setErro] = useState(null);
  const [buscando, setBuscando] = useState(false);

  useEffect(() => {
    api.obterProduto(id).then(setDados).catch((e) => setErro(e.message));
  }, [id]);

  async function buscarAgora() {
    setBuscando(true);
    setErro(null);
    try {
      setDados(await api.buscarAgora(id));
    } catch (e) {
      setErro(e.message);
    } finally {
      setBuscando(false);
    }
  }

  async function arquivar() {
    if (!confirm("Arquivar este produto? Ele some da lista (o histórico fica guardado).")) return;
    try {
      await api.arquivarProduto(id);
      router.push("/");
    } catch (e) {
      setErro(e.message);
    }
  }

  if (erro) return <main className="container"><div className="card" style={{ color: "var(--vermelho)" }}>{erro}</div></main>;
  if (!dados) return <main className="container"><p className="vazio">Carregando…</p></main>;

  const { produto, ofertas } = dados;
  const referencia = produto.preco_referencia ? Number(produto.preco_referencia) : null;
  const precos = ofertas.map((o) => Number(o.preco_final));
  const maiorBase = precos.length ? Math.max(...precos) : 0;
  const escala = Math.max(maiorBase, referencia || 0) || 1; // barras e ref na mesma escala
  const menor = precos.length ? Math.min(...precos) : 0;
  const economia = referencia !== null && precos.length ? referencia - menor : null;

  return (
    <main className="container">
      <div className="cabecalho">
        <Link href="/" className="link-loja">← Produtos</Link>
      </div>
      <div className="cabecalho">
        <h1>{produto.nome}</h1>
        <span className="badge">{produto.categoria}</span>
        <div className="espaco" />
        <button className="btn fantasma" onClick={arquivar}>Arquivar</button>
        <button className="btn" onClick={buscarAgora} disabled={buscando}>
          {buscando ? "Buscando…" : "🔎 Buscar agora"}
        </button>
      </div>

      {ofertas.length > 0 && (
        <div className="stats">
          <div className="card stat">
            <div className="rotulo">Melhor preço</div>
            <div className="valor" style={{ color: "var(--verde)" }}>{reais(menor)}</div>
          </div>
          {referencia !== null && (
            <div className="card stat">
              <div className="rotulo">Preço de referência</div>
              <div className="valor">{reais(referencia)}</div>
            </div>
          )}
          {economia !== null && (
            <div className="card stat">
              <div className="rotulo">{economia >= 0 ? "Economia vs. referência" : "Acima da referência"}</div>
              <div className="valor" style={{ color: economia >= 0 ? "var(--verde)" : "var(--vermelho)" }}>
                {reais(Math.abs(economia))}
              </div>
            </div>
          )}
          <div className="card stat">
            <div className="rotulo">Lojas encontradas</div>
            <div className="valor">{ofertas.length}</div>
          </div>
        </div>
      )}

      <div className="card">
        <h2 style={{ marginTop: 0, fontSize: 18 }}>Comparação por loja</h2>
        {referencia !== null && ofertas.length > 0 && (
          <p className="titulo" style={{ marginTop: -6 }}>
            A linha tracejada marca seu preço de referência ({reais(referencia)}).
            Barra <span style={{ color: "var(--verde)" }}>verde</span> = abaixo dela.
          </p>
        )}
        {ofertas.length === 0 && (
          <p className="vazio" style={{ padding: 24 }}>
            {buscando ? "Buscando nas lojas…" : "Sem ofertas ainda. Clique em “Buscar agora”."}
          </p>
        )}
        {ofertas.map((o, i) => {
          const preco = Number(o.preco_final);
          const largura = (preco / escala) * 100;
          const refPct = referencia !== null ? (referencia / escala) * 100 : null;
          const abaixoRef = referencia !== null && preco <= referencia;
          const ehMenor = preco === menor;
          return (
            <div className="oferta" key={i}>
              <div className="linha1">
                <span className="loja">{o.loja}</span>
                {ehMenor && <span className="melhor">● mais barato</span>}
                {!o.em_estoque && <span className="badge alerta">fora de estoque</span>}
                <span className="preco">{reais(preco)}</span>
              </div>
              <div className="titulo" style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                <span>{o.titulo}</span>
                {o.preco_confirmado === false ? (
                  <span className="chip vitrine" title="Preço listado no Google Shopping; pode variar na loja.">
                    preço de vitrine
                  </span>
                ) : (
                  <span className="chip confirmado" title="Preço confirmado na página da loja.">
                    confirmado
                  </span>
                )}
                {typeof o.score_match === "number" && (
                  <span className="chip neutro">match {o.score_match.toFixed(2)}</span>
                )}
              </div>
              <div className="barra">
                <span style={{ width: `${largura}%`, background: abaixoRef ? "var(--verde)" : undefined }} />
                {refPct !== null && <i className="ref-linha" style={{ left: `${refPct}%` }} />}
              </div>
              <Escadinha o={o} />
              <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                <a className="link-loja" href={o.url} target="_blank" rel="noreferrer">abrir na loja ↗</a>
                {o.coletado_em && <span className="titulo">coletado {quando(o.coletado_em)}</span>}
              </div>
            </div>
          );
        })}
      </div>

      <Funil diagnostico={dados.diagnostico} />
    </main>
  );
}

// A escadinha de desconto (§16): base à vista − cupom − cashback = preço final.
// Só aparece quando a carteira realmente mexeu no preço — senão o preço sozinho basta.
function Escadinha({ o }) {
  const cupom = o.desconto_cupom ? Number(o.desconto_cupom) : 0;
  const cashback = o.desconto_cashback ? Number(o.desconto_cashback) : 0;
  if (cupom <= 0 && cashback <= 0) return null;
  const base = o.preco_base ? Number(o.preco_base) : null;
  return (
    <div className="escadinha" title="Preço final = base à vista − cupom − cashback">
      {base !== null && <span className="deg">{reais(base)}</span>}
      {cupom > 0 && (
        <span className="deg desc">
          − cupom {o.cupom_codigo ? <code className="codigo">{o.cupom_codigo}</code> : null} {reais(cupom)}
          {o.cupom_confirmado === false && (
            <span className="chip vitrine" style={{ marginLeft: 6 }} title="Cupom descoberto na web — provável, mas não confirmado. Teste na loja.">
              não confirmado
            </span>
          )}
        </span>
      )}
      {cashback > 0 && (
        <span className="deg desc">
          − cashback {o.cashback_fonte ? `via ${o.cashback_fonte}` : ""} {reais(cashback)}
        </span>
      )}
      <span className="deg final">= {reais(o.preco_final)}</span>
    </div>
  );
}

// O funil visível: por que as outras lojas ficaram de fora. Acaba com o ponto
// cego (loja que apareceu na busca mas não bateu certeza some sem explicação).
function Funil({ diagnostico }) {
  if (!diagnostico) return null;
  const emRevisao = diagnostico.em_revisao || [];
  const descartadas = diagnostico.descartadas || [];
  if (emRevisao.length === 0 && descartadas.length === 0) return null;

  return (
    <div className="card">
      <h2 style={{ marginTop: 0, fontSize: 18 }}>Por que outras lojas ficaram de fora</h2>

      {emRevisao.length > 0 && (
        <details open>
          <summary>Em revisão ({emRevisao.length}) — quase bateu, confira</summary>
          {emRevisao.map((o, i) => (
            <div className="oferta" key={i}>
              <div className="linha1">
                <span className="loja">{o.loja}</span>
                <span className="titulo" style={{ marginLeft: 8 }}>
                  match {Number(o.score).toFixed(2)}
                </span>
              </div>
              <div className="titulo">{o.titulo}</div>
              <div className="titulo" style={{ color: "var(--amarelo, #b58900)" }}>{o.motivo}</div>
            </div>
          ))}
        </details>
      )}

      {descartadas.length > 0 && (
        <details>
          <summary>Descartadas ({descartadas.length}) — por quê</summary>
          {descartadas.map((o, i) => (
            <div className="oferta" key={i}>
              <div className="linha1"><span className="loja">{o.loja}</span></div>
              <div className="titulo">{o.titulo}</div>
              <div className="titulo" style={{ opacity: 0.75 }}>{o.motivo}</div>
            </div>
          ))}
        </details>
      )}
    </div>
  );
}
