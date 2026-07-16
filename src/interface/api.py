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
from adapters.cupons import BuscadorCuponsSerperLLM
from adapters.coletores.google_shopping import ColetorGoogleShopping
from adapters.coletores.kabum import ColetorKabum
from adapters.extratores import extrair_identidade_do_titulo
from adapters.repositorios.sqlite import (
    RepositorioProdutoSQLite,
    RepositorioSKUSQLite,
    RepositorioSnapshotSQLite,
    RepositorioCupomSQLite,
    RepositorioCashbackSQLite,
    conectar,
)
from application.buscar_produto import (
    BuscarProduto,
    OfertaTriada,
    ProdutoInexistente,
    ResultadoBusca,
    _decompor,
)
from application.buscadores import StatusCupom
from application.coletores import Coletor
from config import Config, carregar_config
from datetime import date
from domain import OfertaBruta, Produto, dinheiro

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
    # Resumo pro card da lista (mini-comparação): melhor preço já encontrado e
    # quantas lojas. None/0 = "aguardando busca". Só preenchido na listagem.
    melhor_preco: str | None = None
    num_lojas: int = 0


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
    # Escadinha de desconto (§16): base à vista − cupom − cashback = preco_final.
    # None quando não há esse desconto. Strings pra não perder centavo no JSON.
    preco_base: str | None = None
    desconto_cupom: str | None = None
    desconto_cashback: str | None = None
    # Qual cupom/cashback incidiu (RN13). `cupom_confirmado=False` = cupom
    # DESCOBERTO (não digitado por você) → desconto "provável", a UI avisa.
    cupom_codigo: str | None = None
    cupom_confirmado: bool = True
    cashback_fonte: str | None = None
    # Cupons descobertos da loja (pra copiar ao lado de "Abrir na loja").
    cupons_loja: list[CupomLojaView] = []


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


class CupomView(BaseModel):
    loja: str
    codigo: str
    desconto: str
    tipo: str
    valor_min: str
    validade: str | None
    primeira_compra: bool


class CashbackView(BaseModel):
    loja: str
    fonte: str
    percentual: str
    teto: str | None
    condicao: str | None


class CupomDescobertoView(BaseModel):
    """Cupom achado pelo buscador, com a validação por sinais."""

    loja: str
    codigo: str
    desconto: str
    tipo: str
    validade: str | None
    status: str  # provavel_valido | nao_confirmado | expirado
    confianca: str  # alta | media | baixa
    evidencias: list[str]
    categorias: list[str]  # [] = geral (vale pra tudo)


class CupomLojaView(BaseModel):
    """Cupom da loja mostrado no card da oferta (ao lado de 'Abrir na loja')."""

    codigo: str
    desconto: str
    tipo: str
    status: str
    categorias: list[str]
    aplicavel: bool  # vale pra ESTE produto (categoria bate + provável válido)


class CarteiraView(BaseModel):
    cupons: list[CupomView]  # manuais (você digitou)
    descobertos: list[CupomDescobertoView] = []  # achados pelo buscador
    cashbacks: list[CashbackView]


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


def _buscador_cupons(config: Config) -> BuscadorCuponsSerperLLM | None:
    """Descoberta automática de cupons (Serper busca + LLM extrai). Sem Serper ou
    NVIDIA → None (só a carteira manual vale)."""
    if not (config.serper_api_key and config.nvidia_api_key):
        return None
    return BuscadorCuponsSerperLLM(
        serper_api_key=config.serper_api_key,
        nvidia_api_key=config.nvidia_api_key,
        nvidia_base_url=config.nvidia_base_url,
        nvidia_model=config.nvidia_model_classificador,
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


# ---------- Rotas ----------

@app.get("/api/produtos", response_model=list[ProdutoView])
def listar_produtos() -> list[ProdutoView]:
    con, config = _abrir()
    try:
        produtos = RepositorioProdutoSQLite(con).produtos_ativos(CONTA_PADRAO)
        views: list[ProdutoView] = []
        for p in produtos:
            view = _produto_view(p)
            if p.id is not None:
                ofertas = _ofertas_guardadas(con, p.id, config, p.categoria)  # barato 1º
                if ofertas:
                    view.melhor_preco = ofertas[0].preco_final
                    view.num_lojas = len(ofertas)
            views.append(view)
        return views
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
    con, config = _abrir()
    try:
        produto = RepositorioProdutoSQLite(con).obter(produto_id, CONTA_PADRAO)
        if produto is None:
            raise HTTPException(404, f"produto {produto_id} não encontrado")
        ofertas = _ofertas_guardadas(con, produto_id, config, produto.categoria)
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
            repo_cupom=RepositorioCupomSQLite(con),
            repo_cashback=RepositorioCashbackSQLite(con),
            classificador=_classificador(config),
            buscador_cupons=_buscador_cupons(config),
        )
        try:
            resultado = asyncio.run(
                caso.executar(
                    produto_id, 
                    CONTA_PADRAO, 
                    config.cep_destino, 
                    config.cashback_elegivel
                )
            )
        except ProdutoInexistente as e:
            raise HTTPException(404, str(e)) from e
        # Lê de volta do banco: mesma forma/ordem do GET, já com o timestamp. O
        # flag "preço confirmado" não é persistido, então vem do ranking (por loja).
        ofertas = _ofertas_guardadas(
            con, produto_id, config, resultado.produto.categoria
        )
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


def _ofertas_guardadas(
    con: sqlite3.Connection, produto_id: int, config: Config, categoria: str
) -> list[OfertaView]:
    """Ofertas persistidas (SKU + último snapshot), com a CARTEIRA aplicada
    (melhor cupom + melhor cashback) e a escadinha de desconto, ordenadas pela
    mais barata. Reaplica a carteira a cada leitura — adicionar um cupom e
    recarregar já reflete no preço, sem re-buscar nas lojas."""
    repo_sku = RepositorioSKUSQLite(con)
    repo_snap = RepositorioSnapshotSQLite(con)
    repo_cupom = RepositorioCupomSQLite(con)
    repo_cashback = RepositorioCashbackSQLite(con)
    hoje = date.today()
    linhas: list[tuple[Decimal, OfertaView]] = []
    for sku in repo_sku.de_produto(produto_id, CONTA_PADRAO):
        if sku.id is None:
            continue
        snap = repo_snap.ultimo_snapshot(sku.id, CONTA_PADRAO)
        if snap is None:
            continue
        loja = sku.loja_origem or ""
        oferta = OfertaBruta(
            titulo=sku.titulo_original,
            preco=snap.preco,
            url=sku.url,
            preco_avista=snap.preco_avista,
            desconto_pix=snap.desconto_pix,
            frete=snap.frete,
            frete_cotado=snap.frete_cotado,
            em_estoque=snap.em_estoque,
        )
        aplicaveis = [
            c for c in repo_cupom.ativos_por_loja(loja) if c.aplica_na_categoria(categoria)
        ]
        final, base, desc_cupom, desc_cashback, cupom_ap, cashback_ap = _decompor(
            oferta,
            aplicaveis,
            repo_cashback.ativos_por_loja(loja),
            hoje,
            config.cashback_elegivel,
        )
        descobertos_loja = repo_cupom.descobertos_por_loja(loja)
        descobertos = {d.cupom.codigo for d in descobertos_loja}
        cupons_loja = [
            CupomLojaView(
                codigo=d.cupom.codigo,
                desconto=str(d.cupom.desconto),
                tipo=d.cupom.tipo.value,
                status=d.status.value,
                categorias=list(d.cupom.categorias),
                aplicavel=(
                    d.status is StatusCupom.PROVAVEL_VALIDO
                    and d.cupom.aplica_na_categoria(categoria)
                ),
            )
            for d in descobertos_loja
        ]
        cupom_codigo = cupom_ap.codigo if cupom_ap else None
        linhas.append(
            (
                final,
                OfertaView(
                    loja=loja,
                    titulo=sku.titulo_original,
                    url=sku.url,
                    preco_final=str(final),
                    preco_base=str(base),
                    desconto_cupom=str(desc_cupom) if desc_cupom > 0 else None,
                    desconto_cashback=str(desc_cashback) if desc_cashback > 0 else None,
                    cupom_codigo=cupom_codigo,
                    cupom_confirmado=cupom_codigo is not None and cupom_codigo not in descobertos,
                    cashback_fonte=cashback_ap.fonte if cashback_ap else None,
                    cupons_loja=cupons_loja,
                    em_estoque=snap.em_estoque,
                    score_match=sku.score_match,
                    coletado_em=snap.coletado_em.isoformat() if snap.coletado_em else None,
                ),
            )
        )
    linhas.sort(key=lambda t: t[0])
    return [view for _, view in linhas]


@app.get("/api/carteira", response_model=CarteiraView)
def listar_carteira() -> CarteiraView:
    con, _ = _abrir()
    try:
        repo_cupom = RepositorioCupomSQLite(con)
        repo_cashback = RepositorioCashbackSQLite(con)
        manuais, descobertos = repo_cupom.listar_carteira()

        cupons = [
            CupomView(
                loja=loja,
                codigo=c.codigo,
                desconto=str(c.desconto),
                tipo=c.tipo.value,
                valor_min=str(c.valor_min),
                validade=c.validade.isoformat() if c.validade else None,
                primeira_compra=c.primeira_compra,
            )
            for loja, c in manuais
        ]
        cupons_descobertos = [
            CupomDescobertoView(
                loja=loja,
                codigo=d.cupom.codigo,
                desconto=str(d.cupom.desconto),
                tipo=d.cupom.tipo.value,
                validade=d.cupom.validade.isoformat() if d.cupom.validade else None,
                status=d.status.value,
                confianca=d.confianca.value,
                evidencias=d.evidencias,
                categorias=list(d.cupom.categorias),
            )
            for loja, d in descobertos
        ]
        cashbacks = [
            CashbackView(
                loja=loja,
                fonte=c.fonte,
                percentual=str(c.percentual),
                teto=str(c.teto) if c.teto else None,
                condicao=c.condicao,
            )
            for loja, c in repo_cashback.todos()
        ]
        return CarteiraView(
            cupons=cupons, descobertos=cupons_descobertos, cashbacks=cashbacks
        )
    finally:
        con.close()


@app.post("/api/carteira/cupom", response_model=CupomView, status_code=201)
def cadastrar_cupom(dados: CupomView) -> CupomView:
    from domain.cupom import Cupom, TipoDesconto
    from datetime import date
    con, _ = _abrir()
    try:
        val = date.fromisoformat(dados.validade) if dados.validade else None
        c = Cupom(
            codigo=dados.codigo,
            desconto=Decimal(dados.desconto),
            tipo=TipoDesconto(dados.tipo),
            valor_min=Decimal(dados.valor_min),
            validade=val,
            primeira_compra=dados.primeira_compra
        )
        RepositorioCupomSQLite(con).salvar(dados.loja, c)
        return dados
    finally:
        con.close()


@app.post("/api/carteira/cashback", response_model=CashbackView, status_code=201)
def cadastrar_cashback(dados: CashbackView) -> CashbackView:
    from domain.cashback import Cashback
    con, _ = _abrir()
    try:
        c = Cashback(
            fonte=dados.fonte,
            percentual=Decimal(dados.percentual),
            teto=Decimal(dados.teto) if dados.teto else None,
            condicao=dados.condicao
        )
        RepositorioCashbackSQLite(con).salvar(dados.loja, c)
        return dados
    finally:
        con.close()


@app.delete("/api/carteira/cupom", status_code=204)
def remover_cupom(loja: str, codigo: str) -> None:
    con, _ = _abrir()
    try:
        if not RepositorioCupomSQLite(con).remover(loja, codigo):
            raise HTTPException(404, f"cupom {codigo!r} não encontrado em {loja!r}")
    finally:
        con.close()


@app.delete("/api/carteira/cashback", status_code=204)
def remover_cashback(loja: str, fonte: str) -> None:
    con, _ = _abrir()
    try:
        if not RepositorioCashbackSQLite(con).remover(loja, fonte):
            raise HTTPException(404, f"cashback {fonte!r} não encontrado em {loja!r}")
    finally:
        con.close()
