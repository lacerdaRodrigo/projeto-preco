"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "../lib/api";

// Entrada título-first (decisão firme): o Rodrigo já pesquisou no Google e traz
// o modelo específico; ele cola o TÍTULO e o backend extrai marca/modelo/
// categoria. Os campos extras são refinamentos que o título não carrega.
export default function Cadastrar() {
  const router = useRouter();
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState(null);
  const [avancado, setAvancado] = useState(false);
  const [form, setForm] = useState({
    titulo: "", categoria: "", preco_referencia: "",
    palavras_obrigatorias: "", palavras_proibidas: "",
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
      const produto = await api.rastrear({
        titulo: form.titulo.trim(),
        categoria: form.categoria || null,
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
      <div className="cabecalho"><h1>Rastrear produto</h1></div>
      <form className="form" onSubmit={salvar}>
        <div className="campo">
          <label>Título do produto *</label>
          <span className="dica">
            Cole o título que você achou no Google (com marca, modelo e specs).
            O sistema extrai a identidade e busca por ela.
          </span>
          <textarea required rows={3} value={form.titulo}
            onChange={(e) => set("titulo", e.target.value)}
            placeholder="Ex.: Smartphone Motorola Moto G67 5G 256GB 8GB RAM Tela 6.7&quot;" />
        </div>

        <button type="button" className="btn fantasma"
          onClick={() => setAvancado((v) => !v)}>
          {avancado ? "− Menos opções" : "+ Refinar (opcional)"}
        </button>

        {avancado && (
          <>
            <div className="campo">
              <label>Categoria</label>
              <span className="dica">Sobrescreve a categoria detectada no título.</span>
              <input value={form.categoria} onChange={(e) => set("categoria", e.target.value)}
                placeholder="Ex.: eletronicos" />
            </div>
            <div className="campo">
              <label>Preço de referência</label>
              <span className="dica">Quanto você espera pagar. Vira a linha de comparação no dashboard.</span>
              <input value={form.preco_referencia}
                onChange={(e) => set("preco_referencia", e.target.value)}
                placeholder="Ex.: 1.499,90" />
            </div>
            <div className="campo">
              <label>Palavras obrigatórias</label>
              <span className="dica">Separadas por vírgula. A oferta precisa conter todas (ex.: G67, 256GB).</span>
              <input value={form.palavras_obrigatorias}
                onChange={(e) => set("palavras_obrigatorias", e.target.value)} />
            </div>
            <div className="campo">
              <label>Palavras proibidas</label>
              <span className="dica">Filtra acessório/errado (ex.: capa, pelicula, G66).</span>
              <input value={form.palavras_proibidas}
                onChange={(e) => set("palavras_proibidas", e.target.value)} />
            </div>
          </>
        )}

        {erro && <div style={{ color: "var(--vermelho)" }}>{erro}</div>}
        <div className="form-acoes">
          <button className="btn" type="submit" disabled={salvando}>
            {salvando ? "Rastreando…" : "Rastrear"}
          </button>
        </div>
      </form>
    </main>
  );
}
