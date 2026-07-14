"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "../lib/api";

export default function Cadastrar() {
  const router = useRouter();
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState(null);
  const [form, setForm] = useState({
    nome: "", categoria: "", marca: "", modelo: "", ean: "",
    preco_referencia: "", palavras_obrigatorias: "", palavras_proibidas: "",
  });

  function set(campo, valor) {
    setForm((f) => ({ ...f, [campo]: valor }));
  }

  function lista(texto) {
    return texto.split(",").map((s) => s.trim()).filter(Boolean);
  }

  async function salvar(e) {
    e.preventDefault();
    setSalvando(true);
    setErro(null);
    try {
      const produto = await api.cadastrarProduto({
        nome: form.nome,
        categoria: form.categoria,
        marca: form.marca || null,
        modelo: form.modelo || null,
        ean: form.ean || null,
        preco_referencia: form.preco_referencia || null,
        palavras_obrigatorias: lista(form.palavras_obrigatorias),
        palavras_proibidas: lista(form.palavras_proibidas),
      });
      router.push(`/produtos/${produto.id}`);
    } catch (e) {
      setErro(e.message);
      setSalvando(false);
    }
  }

  return (
    <main className="container">
      <div className="cabecalho"><h1>Cadastrar produto</h1></div>
      <form className="form" onSubmit={salvar}>
        <div className="campo">
          <label>Nome *</label>
          <input required value={form.nome} onChange={(e) => set("nome", e.target.value)}
            placeholder="Ex.: Echo Dot 5" />
        </div>
        <div className="campo">
          <label>Categoria *</label>
          <input required value={form.categoria} onChange={(e) => set("categoria", e.target.value)}
            placeholder="Ex.: eletronicos" />
        </div>
        <div className="campo">
          <label>Marca</label>
          <input value={form.marca} onChange={(e) => set("marca", e.target.value)}
            placeholder="Ex.: Samsung" />
        </div>
        <div className="campo">
          <label>Preço de referência</label>
          <span className="dica">Quanto você espera pagar. Vira a linha de comparação no dashboard.</span>
          <input value={form.preco_referencia}
            onChange={(e) => set("preco_referencia", e.target.value)}
            placeholder="Ex.: 449,90" />
        </div>
        <div className="campo">
          <label>Palavras obrigatórias</label>
          <span className="dica">Separadas por vírgula. A oferta precisa conter todas (ex.: S26, Ultra).</span>
          <input value={form.palavras_obrigatorias}
            onChange={(e) => set("palavras_obrigatorias", e.target.value)} />
        </div>
        <div className="campo">
          <label>Palavras proibidas</label>
          <span className="dica">Filtra acessório/errado (ex.: capa, pelicula, S25).</span>
          <input value={form.palavras_proibidas}
            onChange={(e) => set("palavras_proibidas", e.target.value)} />
        </div>
        {erro && <div style={{ color: "var(--vermelho)" }}>{erro}</div>}
        <div className="form-acoes">
          <button className="btn" type="submit" disabled={salvando}>
            {salvando ? "Salvando…" : "Cadastrar"}
          </button>
        </div>
      </form>
    </main>
  );
}
