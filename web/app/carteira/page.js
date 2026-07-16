"use client";

import { useEffect, useState } from "react";
import { api, reais } from "../lib/api";

// Carteira: cupons vêm DIRETO do buscador (descobertos na busca de cada produto)
// e já entram no preço marcados "não confirmado". Aqui você vê os descobertos por
// loja e remove os que não prestam. Cashback é manual (elegibilidade sua).
export default function Carteira() {
  const [dados, setDados] = useState(null);
  const [erro, setErro] = useState(null);

  function carregar() {
    api.listarCarteira().then(setDados).catch((e) => setErro(e.message));
  }
  useEffect(carregar, []);

  async function removerCupom(loja, codigo) {
    try { await api.removerCupom(loja, codigo); carregar(); }
    catch (e) { setErro(e.message); }
  }
  async function removerCashback(loja, fonte) {
    try { await api.removerCashback(loja, fonte); carregar(); }
    catch (e) { setErro(e.message); }
  }

  return (
    <main className="container">
      <div className="cabecalho"><h1>Carteira</h1></div>
      <p className="subtitulo">
        Cupons são <strong>descobertos automaticamente</strong> na busca e entram no
        preço marcados “não confirmado” (teste na loja). Cashback é você que informa.
      </p>

      {erro && (
        <div className="card" style={{ color: "var(--vermelho)" }}>
          Não consegui falar com a API ({erro}). O backend está na porta 8000?
        </div>
      )}

      {!dados && !erro && <p className="vazio">Carregando…</p>}

      {dados && (
        <div className="carteira-grid">
          <section>
            <h2 style={{ fontSize: 18, margin: "0 0 12px" }}>Cupons descobertos</h2>
            <CuponsDescobertos itens={dados.descobertos} onRemover={removerCupom} />
            {dados.cupons.length > 0 && (
              <>
                <h3 style={{ fontSize: 15, margin: "22px 0 10px" }}>Cupons manuais</h3>
                <div className="card">
                  {dados.cupons.map((c, i) => (
                    <div className="item-carteira" key={i}>
                      <div>
                        <span className="loja">{c.loja}</span>{" "}
                        <code className="codigo">{c.codigo}</code>
                        <span className="chip confirmado" style={{ marginLeft: 6 }}>confirmado</span>
                        <BotaoRemover onClick={() => removerCupom(c.loja, c.codigo)} />
                      </div>
                      <div className="titulo">
                        {c.tipo === "percentual" ? `${Number(c.desconto)}% off` : `${reais(c.desconto)} off`}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </section>

          <section>
            <FormCashback aoSalvar={carregar} aoErro={setErro} />
            <ListaCashbacks cashbacks={dados.cashbacks} onRemover={removerCashback} />
          </section>
        </div>
      )}
    </main>
  );
}

const _STATUS = {
  provavel_valido: { rotulo: "provável válido", classe: "confirmado" },
  nao_confirmado: { rotulo: "não confirmado", classe: "neutro" },
  expirado: { rotulo: "expirado", classe: "vitrine" },
};

function CuponsDescobertos({ itens, onRemover }) {
  if (!itens || itens.length === 0) {
    return (
      <div className="mini-vazio">
        Nenhum cupom descoberto ainda. Rode uma busca de produto — o sistema procura
        cupons das lojas automaticamente.
      </div>
    );
  }
  return (
    <div className="card">
      {itens.map((c, i) => {
        const s = _STATUS[c.status] || _STATUS.nao_confirmado;
        return (
          <div className="item-carteira" key={i}>
            <div>
              <span className="loja">{c.loja}</span>{" "}
              <code className="codigo">{c.codigo}</code>
              <span className={`chip ${s.classe}`} style={{ marginLeft: 6 }}>{s.rotulo}</span>
              <BotaoRemover onClick={() => onRemover(c.loja, c.codigo)} />
            </div>
            <div className="titulo">
              {c.tipo === "percentual" ? `${Number(c.desconto)}% off` : `${reais(c.desconto)} off`}
              {c.validade && ` · até ${c.validade}`}
              {c.evidencias?.length > 0 && ` · ${c.evidencias.join(" · ")}`}
            </div>
            <div className="titulo" style={{ fontSize: 12 }}>
              vale para: {c.categorias?.length > 0 ? c.categorias.join(", ") : "geral"}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function BotaoRemover({ onClick }) {
  return (
    <button className="btn-remover" onClick={onClick} title="Remover" aria-label="Remover">🗑</button>
  );
}

function FormCashback({ aoSalvar, aoErro }) {
  const vazio = { loja: "", fonte: "", percentual: "", teto: "", condicao: "" };
  const [form, setForm] = useState(vazio);
  const [salvando, setSalvando] = useState(false);
  const set = (c, v) => setForm((f) => ({ ...f, [c]: v }));

  async function salvar(e) {
    e.preventDefault();
    setSalvando(true);
    aoErro(null);
    try {
      await api.cadastrarCashback({
        loja: form.loja.trim(),
        fonte: form.fonte.trim(),
        percentual: form.percentual || "0",
        teto: form.teto || null,
        condicao: form.condicao.trim() || null,
      });
      setForm(vazio);
      aoSalvar();
    } catch (e) {
      aoErro(e.message);
    } finally {
      setSalvando(false);
    }
  }

  return (
    <form className="card form" onSubmit={salvar} style={{ marginBottom: 18 }}>
      <h2 style={{ margin: 0, fontSize: 18 }}>Novo cashback</h2>
      <div className="dois">
        <div className="campo">
          <label>Loja</label>
          <input required value={form.loja} onChange={(e) => set("loja", e.target.value)} placeholder="Ex.: KaBuM!" />
        </div>
        <div className="campo">
          <label>Fonte</label>
          <span className="dica">Quem paga.</span>
          <input required value={form.fonte} onChange={(e) => set("fonte", e.target.value)} placeholder="inter" />
        </div>
      </div>
      <div className="dois">
        <div className="campo">
          <label>Percentual (%)</label>
          <input required value={form.percentual} onChange={(e) => set("percentual", e.target.value)} placeholder="5" />
        </div>
        <div className="campo">
          <label>Teto (opcional)</label>
          <input value={form.teto} onChange={(e) => set("teto", e.target.value)} placeholder="100" />
        </div>
      </div>
      <div className="campo">
        <label>Condição (opcional)</label>
        <span className="dica">Só vale se estiver em CASHBACK_ELEGIVEL no .env (ex.: inter).</span>
        <input value={form.condicao} onChange={(e) => set("condicao", e.target.value)} placeholder="inter" />
      </div>
      <div className="form-acoes">
        <button className="btn" type="submit" disabled={salvando}>{salvando ? "Salvando…" : "Adicionar cashback"}</button>
      </div>
    </form>
  );
}

function ListaCashbacks({ cashbacks, onRemover }) {
  if (!cashbacks || cashbacks.length === 0) return <div className="mini-vazio">Nenhum cashback cadastrado.</div>;
  return (
    <div className="card">
      <h2 style={{ marginTop: 0, fontSize: 16 }}>Cashbacks ({cashbacks.length})</h2>
      {cashbacks.map((c, i) => (
        <div className="item-carteira" key={i}>
          <div>
            <span className="loja">{c.loja}</span>{" "}
            <span className="chip confirmado">{Number(c.percentual)}%</span>
            <span className="titulo" style={{ marginLeft: 6 }}>via {c.fonte}</span>
            <BotaoRemover onClick={() => onRemover(c.loja, c.fonte)} />
          </div>
          <div className="titulo">
            {c.teto ? `teto ${reais(c.teto)}` : "sem teto"}
            {c.condicao && ` · condição: ${c.condicao}`}
          </div>
        </div>
      ))}
    </div>
  );
}
