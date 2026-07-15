"""Adaptador web (FastAPI) — a "porta web" sobre o MESMO núcleo do CLI.

Igual ao `cli.py`, este é um composition root: amarra config + adaptadores +
caso de uso. Não contém regra de negócio (essa vive no domain/application); só
traduz HTTP ↔ núcleo. Assim a web e o terminal compartilham exatamente a mesma
lógica de busca, matching e preço final.

Rodar (localhost):
    .venv/bin/uvicorn interface.api:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from decimal import Decimal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from adapters.classificadores import ClassificadorLLM
from adapters.coletores.google_shopping import ColetorGoogleShopping
from adapters.coletores.kabum import ColetorKabum
from adapters.extratores import extrair_identidade_do_titulo
from adapters.repositorios.sqlite import (
    RepositorioProdutoSQLite,
    RepositorioSKUSQLite,
    RepositorioSnapshotSQLite,
    conectar,
)
from application.buscar_produto import (
    BuscarProduto,
    OfertaTriada,
    ProdutoInexistente,
    ResultadoBusca,
)
from application.coletores import Coletor
from config import Config, carregar_config
from domain import Produto, SnapshotPreco, calcular_preco_final, dinheiro

# V1: uma conta fixa (RN16; multiusuário é V6, o gancho conta_id já existe).
CONTA_PADRAO = 1

app = FastAPI(title="Smart Price Tracker — API", version="0.1.0")

# O front (Next.js) roda noutra porta; libera só o localhost dele (CORS).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Contratos HTTP (o que entra e sai em JSON) ----------

class ProdutoNovo(BaseModel):
    nome: str
    categoria: str
    marca: str | None = None
    modelo: str | None = None
    ean: str | None = None
    preco_referencia: str | None = None  # quanto você espera pagar (referência)
    palavras_obrigatorias: list[str] = []
    palavras_proibidas: list[str] = []


class ProdutoPorTitulo(BaseModel):
    """Entrada título-first (decisão firme): o Rodrigo cola o título; o extrator
    tira marca/modelo/categoria. Os demais campos são refinamentos opcionais que
    o título não carrega (não vêm do extrator)."""

    titulo: str
    categoria: str | None = None  # sobrescreve a categoria detectada
    preco_referencia: str | None = None
    palavras_obrigatorias: list[str] = []
    palavras_proibidas: list[str] = []


class ProdutoView(BaseModel):
    id: int
    nome: str
    categoria: str
    marca: str | None = None
    modelo: str | None = None
    ean: str | None = None
    preco_referencia: str | None = None
    palavras_obrigatorias: list[str] = []
    palavras_proibidas: list[str] = []


class OfertaView(BaseModel):
    loja: str
    titulo: str
    url: str
    preco_final: str  # string pra não perder centavo em float no JSON
    em_estoque: bool
    score_match: float
    coletado_em: str | None = None  # quando esse preço foi coletado (ISO)
    # False = preço de vitrine (Google Shopping), não confirmado na página.
    preco_confirmado: bool = True


class OfertaTriadaView(BaseModel):
    """Uma oferta que ficou de fora do ranking, com o porquê (o funil visível)."""

    loja: str
    titulo: str
    motivo: str
    etapa: str
    score: float


class DiagnosticoView(BaseModel):
    """Onde as lojas morreram nesta busca — pra a gente ver, não sumir em silêncio."""

    em_revisao: list[OfertaTriadaView] = []
    descartadas: list[OfertaTriadaView] = []


class ProdutoDetalhe(BaseModel):
    produto: ProdutoView
    ofertas: list[OfertaView]
    # Só preenchido logo após uma busca (o GET do produto não tem funil a mostrar).
    diagnostico: DiagnosticoView | None = None


# ---------- Fiação (mesma do CLI) ----------

def _abrir() -> tuple[sqlite3.Connection, Config]:
    config = carregar_config()
    caminho = config.database_url.removeprefix("sqlite:///")
    return conectar(caminho), config


def _coletores(config: Config) -> list[Coletor]:
    """Padrão: Google Shopping (várias lojas). Sem chave, cai no KaBuM!."""
    if config.serper_api_key:
        return [ColetorGoogleShopping(config.serper_api_key)]
    return [ColetorKabum()]


def _classificador(config: Config) -> ClassificadorLLM | None:
    """O juiz de identidade por IA. Sem chave NVIDIA → None (matching determinístico)."""
    if not config.nvidia_api_key:
        return None
    return ClassificadorLLM(
        config.nvidia_api_key,
        config.nvidia_base_url,
        config.nvidia_model_classificador,
    )


def _produto_view(produto: Produto) -> ProdutoView:
    if produto.id is None:  # invariante: o repositório sempre preenche o id
        raise RuntimeError("produto sem id (não deveria acontecer)")
    return ProdutoView(
        id=produto.id,
        nome=produto.nome,
        categoria=produto.categoria,
        marca=produto.marca,
        modelo=produto.modelo,
        ean=produto.ean,
        preco_referencia=str(produto.preco_referencia) if produto.preco_referencia else None,
        palavras_obrigatorias=list(produto.palavras_obrigatorias),
        palavras_proibidas=list(produto.palavras_proibidas),
    )


def _dinheiro_opcional(valor: str | None) -> Decimal | None:
    """Texto do formulário → Decimal. Vazio/None → None. Inválido → 400.

    Aceita formato BR ("8.999,90") e ponto decimal ("8999.90")."""
    if valor is None or not valor.strip():
        return None
    texto = valor.strip()
    if "," in texto:  # BR: ponto é milhar, vírgula é decimal
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return dinheiro(texto)
    except Exception as e:  # noqa: BLE001 - vira 400 pro cliente
        raise HTTPException(400, f"preço de referência inválido: {valor!r}") from e


def _preco_final_snapshot(snap: SnapshotPreco) -> Decimal:
    """Preço final à vista do snapshot guardado (§16; V1 sem cupom/cashback)."""
    return calcular_preco_final(
        preco=snap.preco,
        preco_avista=snap.preco_avista,
        frete=snap.frete,
        frete_cotado=snap.frete_cotado,
    )


# ---------- Rotas ----------

@app.get("/api/produtos", response_model=list[ProdutoView])
def listar_produtos() -> list[ProdutoView]:
    con, _ = _abrir()
    try:
        produtos = RepositorioProdutoSQLite(con).produtos_ativos(CONTA_PADRAO)
        return [_produto_view(p) for p in produtos]
    finally:
        con.close()


@app.post("/api/produtos", response_model=ProdutoView, status_code=201)
def cadastrar_produto(dados: ProdutoNovo) -> ProdutoView:
    con, _ = _abrir()
    try:
        produto = RepositorioProdutoSQLite(con).salvar(
            Produto(
                nome=dados.nome,
                categoria=dados.categoria,
                marca=dados.marca,
                modelo=dados.modelo,
                ean=dados.ean,
                preco_referencia=_dinheiro_opcional(dados.preco_referencia),
                palavras_obrigatorias=tuple(dados.palavras_obrigatorias),
                palavras_proibidas=tuple(dados.palavras_proibidas),
            ),
            CONTA_PADRAO,
        )
        return _produto_view(produto)
    finally:
        con.close()


@app.post("/api/rastrear", response_model=ProdutoView, status_code=201)
def rastrear(dados: ProdutoPorTitulo) -> ProdutoView:
    """Porta da frente (título-first): cola o título → extrai a identidade
    canônica (marca/modelo/specs/categoria) e cadastra. Espelha o `rastrear` do CLI.

    Extração pelo LLM (quando há chave) com fallback na heurística. Refinamentos
    que o título não carrega (categoria override, preço de referência, palavras
    de matching) entram por cima da identidade extraída."""
    config = carregar_config()
    ref = extrair_identidade_do_titulo(
        dados.titulo,
        nvidia_api_key=config.nvidia_api_key,
        nvidia_base_url=config.nvidia_base_url,
        nvidia_model=config.nvidia_model,
    )
    if ref is None:
        raise HTTPException(400, "não deu pra identificar o produto por esse título")
    produto = ref.para_produto()  # Produto é frozen; refinamentos via replace
    produto = replace(
        produto,
        categoria=dados.categoria or produto.categoria,
        preco_referencia=_dinheiro_opcional(dados.preco_referencia)
        or produto.preco_referencia,
        palavras_obrigatorias=tuple(dados.palavras_obrigatorias),
        palavras_proibidas=tuple(dados.palavras_proibidas),
    )
    con, _ = _abrir()
    try:
        return _produto_view(RepositorioProdutoSQLite(con).salvar(produto, CONTA_PADRAO))
    finally:
        con.close()


@app.delete("/api/produtos/{produto_id}", status_code=204)
def arquivar_produto(produto_id: int) -> None:
    """Arquiva o produto (RF17) — some da lista, histórico preservado."""
    con, _ = _abrir()
    try:
        if not RepositorioProdutoSQLite(con).arquivar(produto_id, CONTA_PADRAO):
            raise HTTPException(404, f"produto {produto_id} não encontrado")
    finally:
        con.close()


@app.get("/api/produtos/{produto_id}", response_model=ProdutoDetalhe)
def obter_produto(produto_id: int) -> ProdutoDetalhe:
    con, _ = _abrir()
    try:
        produto = RepositorioProdutoSQLite(con).obter(produto_id, CONTA_PADRAO)
        if produto is None:
            raise HTTPException(404, f"produto {produto_id} não encontrado")
        ofertas = _ofertas_guardadas(con, produto_id)
        return ProdutoDetalhe(produto=_produto_view(produto), ofertas=ofertas)
    finally:
        con.close()


@app.post("/api/produtos/{produto_id}/buscar", response_model=ProdutoDetalhe)
def buscar_agora(produto_id: int) -> ProdutoDetalhe:
    con, config = _abrir()
    try:
        caso = BuscarProduto(
            coletores=_coletores(config),
            repo_produto=RepositorioProdutoSQLite(con),
            repo_sku=RepositorioSKUSQLite(con),
            repo_snapshot=RepositorioSnapshotSQLite(con),
            classificador=_classificador(config),
        )
        try:
            resultado = asyncio.run(
                caso.executar(produto_id, CONTA_PADRAO, config.cep_destino)
            )
        except ProdutoInexistente as e:
            raise HTTPException(404, str(e)) from e
        # Lê de volta do banco: mesma forma/ordem do GET, já com o timestamp. O
        # flag "preço confirmado" não é persistido, então vem do ranking (por loja).
        ofertas = _ofertas_guardadas(con, produto_id)
        confirmacao = {o.loja: o.preco_confirmado for o in resultado.ranking}
        for oferta in ofertas:
            oferta.preco_confirmado = confirmacao.get(oferta.loja, True)
        return ProdutoDetalhe(
            produto=_produto_view(resultado.produto),
            ofertas=ofertas,
            diagnostico=_diagnostico_view(resultado),
        )
    finally:
        con.close()


def _diagnostico_view(resultado: ResultadoBusca) -> DiagnosticoView:
    """Traduz o funil do maestro (em revisão + descartadas) pra JSON."""
    def triar(itens: list[OfertaTriada]) -> list[OfertaTriadaView]:
        return [
            OfertaTriadaView(
                loja=i.loja, titulo=i.titulo, motivo=i.motivo,
                etapa=i.etapa, score=i.score,
            )
            for i in itens
        ]

    return DiagnosticoView(
        em_revisao=triar(resultado.em_revisao_itens),
        descartadas=triar(resultado.descartadas_itens),
    )


def _ofertas_guardadas(con: sqlite3.Connection, produto_id: int) -> list[OfertaView]:
    """Ofertas já persistidas (SKU + último snapshot), ordenadas pela mais barata."""
    repo_sku = RepositorioSKUSQLite(con)
    repo_snap = RepositorioSnapshotSQLite(con)
    linhas: list[tuple[Decimal, OfertaView]] = []
    for sku in repo_sku.de_produto(produto_id, CONTA_PADRAO):
        if sku.id is None:
            continue
        snap = repo_snap.ultimo_snapshot(sku.id, CONTA_PADRAO)
        if snap is None:
            continue
        final = _preco_final_snapshot(snap)
        linhas.append(
            (
                final,
                OfertaView(
                    loja=sku.loja_origem or "",
                    titulo=sku.titulo_original,
                    url=sku.url,
                    preco_final=str(final),
                    em_estoque=snap.em_estoque,
                    score_match=sku.score_match,
                    coletado_em=snap.coletado_em.isoformat() if snap.coletado_em else None,
                ),
            )
        )
    linhas.sort(key=lambda t: t[0])
    return [view for _, view in linhas]
