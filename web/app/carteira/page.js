"use client";

import { useEffect, useState } from "react";
import { api, reais } from "../lib/api";

export default function Carteira() {
  const [carteira, setCarteira] = useState(null);
  const [erro, setErro] = useState(null);

  // Form states
  const [cupomL, setCupomL] = useState("");
  const [cupomC, setCupomC] = useState("");
  const [cupomD, setCupomD] = useState("");
  const [cupomT, setCupomT] = useState("percentual");
  
  const [cashL, setCashL] = useState("");
  const [cashF, setCashF] = useState("");
  const [cashP, setCashP] = useState("");
  const [cashC, setCashC] = useState("");

  function carregar() {
    api.listarCarteira().then(setCarteira).catch((e) => setErro(e.message));
  }
  useEffect(carregar, []);

  async function addCupom(e) {
    e.preventDefault();
    try {
      await api.cadastrarCupom({
        loja: cupomL,
        codigo: cupomC,
        desconto: cupomD,
        tipo: cupomT,
        valor_min: "0",
        validade: null,
        primeira_compra: false
      });
      setCupomL(""); setCupomC(""); setCupomD("");
      carregar();
    } catch (err) {
      setErro(err.message);
    }
  }

  async function addCashback(e) {
    e.preventDefault();
    try {
      await api.cadastrarCashback({
        loja: cashL,
        fonte: cashF,
        percentual: cashP,
        teto: null,
        condicao: cashC || null
      });
      setCashL(""); setCashF(""); setCashP(""); setCashC("");
      carregar();
    } catch (err) {
      setErro(err.message);
    }
  }

  if (erro) return <main className="container"><div className="card" style={{ color: "var(--vermelho)" }}>{erro}</div></main>;
  if (!carteira) return <main className="container"><p className="vazio">Carregando…</p></main>;

  return (
    <main className="container">
      <div className="cabecalho">
        <h1>Carteira Inteligente</h1>
      </div>
      <p className="subtitulo">
        Gerencie seus cupons e contas de cashback. Eles são aplicados automaticamente na busca!
      </p>

      <div className="grid">
        <div className="card">
          <h2 style={{marginTop: 0, marginBottom: 20}}>Novo Cupom</h2>
          <form className="form" onSubmit={addCupom}>
            <div className="campo">
              <label>Loja (ex: KaBuM!)</label>
              <input value={cupomL} onChange={e => setCupomL(e.target.value)} required />
            </div>
            <div className="campo">
              <label>Código do Cupom</label>
              <input value={cupomC} onChange={e => setCupomC(e.target.value)} required />
            </div>
            <div className="campo">
              <label>Desconto Numérico</label>
              <input type="number" step="0.01" value={cupomD} onChange={e => setCupomD(e.target.value)} required />
            </div>
            <div className="campo">
              <label>Tipo de Desconto</label>
              <select value={cupomT} onChange={e => setCupomT(e.target.value)}>
                <option value="percentual">Percentual (%)</option>
                <option value="fixo">Fixo (R$)</option>
              </select>
            </div>
            <div className="form-acoes">
              <button type="submit" className="btn">+ Salvar Cupom</button>
            </div>
          </form>
        </div>

        <div className="card">
          <h2 style={{marginTop: 0, marginBottom: 20}}>Novo Cashback</h2>
          <form className="form" onSubmit={addCashback}>
            <div className="campo">
              <label>Loja (ex: KaBuM!)</label>
              <input value={cashL} onChange={e => setCashL(e.target.value)} required />
            </div>
            <div className="campo">
              <label>Fonte (ex: inter, meliuz)</label>
              <input value={cashF} onChange={e => setCashF(e.target.value)} required />
            </div>
            <div className="campo">
              <label>Percentual (%)</label>
              <input type="number" step="0.01" value={cashP} onChange={e => setCashP(e.target.value)} required />
            </div>
            <div className="campo">
              <label>Condição (ex: inter)</label>
              <input value={cashC} onChange={e => setCashC(e.target.value)} placeholder="Opcional. DEVE constar no seu .env" />
            </div>
            <div className="form-acoes">
              <button type="submit" className="btn">+ Salvar Cashback</button>
            </div>
          </form>
        </div>
      </div>

      <div className="card" style={{marginTop: 32}}>
        <h2 style={{marginTop: 0}}>Meus Cupons Ativos</h2>
        {carteira.cupons.length === 0 && <p className="vazio" style={{padding: 24}}>Nenhum cupom cadastrado.</p>}
        {carteira.cupons.map((c, i) => (
          <div className="oferta" key={i}>
            <div className="linha1">
              <span className="loja">{c.loja}</span>
              <span className="chip confirmado">{c.codigo}</span>
              <span className="preco">
                {c.tipo === 'percentual' ? `${c.desconto}%` : reais(c.desconto)}
              </span>
            </div>
          </div>
        ))}
      </div>

      <div className="card" style={{marginTop: 32}}>
        <h2 style={{marginTop: 0}}>Meus Cashbacks Ativos</h2>
        {carteira.cashbacks.length === 0 && <p className="vazio" style={{padding: 24}}>Nenhum cashback cadastrado.</p>}
        {carteira.cashbacks.map((c, i) => (
          <div className="oferta" key={i}>
            <div className="linha1">
              <span className="loja">{c.loja}</span>
              <span className="chip vitrine">{c.fonte}</span>
              {c.condicao && <span className="chip neutro">Restrito: {c.condicao}</span>}
              <span className="preco" style={{color: "var(--verde)"}}>
                {c.percentual}% de volta
              </span>
            </div>
          </div>
        ))}
      </div>
    </main>
  );
}
