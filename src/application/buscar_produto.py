"""Caso de uso BuscarProduto — o maestro da fatia vertical (§13).

Pega UM produto e coordena tudo até o resultado gravado: carrega o produto →
dispara os coletores em paralelo (resiliente por loja) → casa cada oferta →
calcula o preço final → grava idempotente. **Orquestra, não contém regra**: as
regras vivem no domain; aqui só a coreografia. Depende só de portas (Coletor,
Repositório) — zero import de adaptador, então roda igual local e na nuvem.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from application.coletores import Coletor, ErroColetor, LojaIndisponivel
from application.repositorios import (
    RepositorioProduto,
    RepositorioSKU,
    RepositorioSnapshot,
)
from domain import (
    SKU,
    OfertaBruta,
    Produto,
    SnapshotPreco,
    calcular_preco_final,
)
from domain.matching import ConfigMatching, Destino, casar


class ProdutoInexistente(Exception):
    """O produto pedido não existe (ou não é da conta)."""


@dataclass(frozen=True)
class OfertaRankeada:
    """Uma oferta aceita, já com o preço final calculado (§16)."""

    loja: str
    titulo: str
    url: str
    preco_final: Decimal
    em_estoque: bool
    score_match: float


@dataclass(frozen=True)
class ResultadoBusca:
    """O que o maestro devolve: o ranking + o que deu errado, transparente."""

    produto: Produto
    ranking: list[OfertaRankeada]  # por preço final; em estoque primeiro
    em_revisao: int  # ofertas 0.6–0.85 (foram pra fila, não pro ranking)
    descartadas: int
    lojas_indisponiveis: list[str]  # falha transitória → dá pra tentar de novo
    lojas_degradadas: list[str]  # coletor quebrado (RN12) → não gravou nada


@dataclass(frozen=True)
class _Coleta:
    """Resultado interno de UMA loja (isola a falha dela — RN08)."""

    coletor: Coletor
    ofertas: list[OfertaBruta]
    status: str  # "ok" | "indisponivel" | "degradado"


@dataclass(frozen=True)
class _Candidata:
    """Uma oferta que casou, esperando disputar a vaga de 'melhor da loja'."""

    coletor: Coletor
    oferta: OfertaBruta
    score: float
    loja_origem: str  # a loja que dá identidade ao SKU (source, ou nome do coletor)


class BuscarProduto:
    def __init__(
        self,
        coletores: Sequence[Coletor],
        repo_produto: RepositorioProduto,
        repo_sku: RepositorioSKU,
        repo_snapshot: RepositorioSnapshot,
        config_matching: ConfigMatching | None = None,
        agora: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._coletores = coletores
        self._produtos = repo_produto
        self._skus = repo_sku
        self._snapshots = repo_snapshot
        self._config = config_matching
        self._agora = agora  # injetável para testes deterministas

    async def executar(
        self, produto_id: int, conta_id: int, cep: str | None = None
    ) -> ResultadoBusca:
        # 1. Carrega o produto (já escopado por conta).
        produto = self._produtos.obter(produto_id, conta_id)
        if produto is None or produto.id is None:
            raise ProdutoInexistente(f"produto {produto_id} não encontrado na conta")

        # 2. Fan-out: todas as lojas em paralelo, cada falha isolada (RN08).
        descricao = _descricao_de(produto)
        coletas = await asyncio.gather(
            *(self._coletar_seguro(c, descricao, cep) for c in self._coletores)
        )

        # 3. Casa cada oferta. As aceitas vão pra um balde POR LOJA DE ORIGEM — o
        #    SKU é 1 por loja (RN01). Um agregador (Google Shopping) traz N lojas
        #    numa busca só, então a identidade vem da loja de origem, não do coletor.
        aceitas: dict[tuple[int, str], list[_Candidata]] = {}
        em_revisao = descartadas = 0
        for coleta in coletas:
            for oferta in coleta.ofertas:
                decisao = casar(produto, oferta, self._config)
                if decisao.destino is Destino.REVISAR:
                    em_revisao += 1
                elif decisao.destino is Destino.DESCARTA:
                    descartadas += 1
                else:
                    loja_origem = _loja_de_origem(coleta.coletor, oferta)
                    candidata = _Candidata(
                        coleta.coletor, oferta, decisao.score, loja_origem
                    )
                    chave = (coleta.coletor.loja_id, loja_origem)
                    aceitas.setdefault(chave, []).append(candidata)

        # 4–5. Por loja, escolhe a MELHOR oferta e grava (SKU + snapshot idempotente).
        ranking = [
            self._persistir(produto_id, _melhor(candidatas), conta_id)
            for candidatas in aceitas.values()
        ]

        # Ranking: em estoque primeiro, depois pelo menor preço final (§16).
        ranking.sort(key=lambda o: (not o.em_estoque, o.preco_final))

        return ResultadoBusca(
            produto=produto,
            ranking=ranking,
            em_revisao=em_revisao,
            descartadas=descartadas,
            lojas_indisponiveis=[c.coletor.nome for c in coletas if c.status == "indisponivel"],
            lojas_degradadas=[c.coletor.nome for c in coletas if c.status == "degradado"],
        )

    async def _coletar_seguro(
        self, coletor: Coletor, descricao: str, cep: str | None
    ) -> _Coleta:
        """Busca numa loja e traduz falha em status — nunca deixa vazar (RN08)."""
        try:
            ofertas = await coletor.buscar(descricao, cep)
            return _Coleta(coletor, ofertas, "ok")
        except LojaIndisponivel:
            return _Coleta(coletor, [], "indisponivel")  # transitório: retry depois
        except ErroColetor:
            # Inclui ColetorQuebrado (RN12): não grava nada dessa loja.
            return _Coleta(coletor, [], "degradado")

    def _persistir(
        self, produto_id: int, candidata: _Candidata, conta_id: int
    ) -> OfertaRankeada:
        coletor, oferta = candidata.coletor, candidata.oferta
        sku = self._skus.salvar_ou_atualizar(
            SKU(
                produto_id=produto_id,
                loja_id=coletor.loja_id,
                loja_origem=candidata.loja_origem,
                url=oferta.url,
                titulo_original=oferta.titulo,
                score_match=candidata.score,
                vendedor_oficial=oferta.vendedor_oficial,
            ),
            conta_id,
        )
        if sku.id is None:  # o repositório sempre preenche; guarda de sanidade
            raise RuntimeError("repositório não devolveu o id do SKU")
        # Grava o snapshot só se algo mudou (RN11) — rodar 2x não duplica.
        self._snapshots.salvar_snapshot_se_mudou(
            SnapshotPreco(
                sku_id=sku.id,
                preco=oferta.preco,
                preco_avista=oferta.preco_avista,
                desconto_pix=oferta.desconto_pix,
                frete=oferta.frete,
                frete_cotado=oferta.frete_cotado,
                prazo_dias=oferta.prazo_dias,
                parcelas=oferta.parcelas,
                sem_juros=oferta.sem_juros,
                em_estoque=oferta.em_estoque,
                coletado_em=self._agora(),
            ),
            conta_id,
        )
        return OfertaRankeada(
            loja=candidata.loja_origem,
            titulo=oferta.titulo,
            url=oferta.url,
            preco_final=_preco_final_de(oferta),
            em_estoque=oferta.em_estoque,
            score_match=candidata.score,
        )


def _loja_de_origem(coletor: Coletor, oferta: OfertaBruta) -> str:
    """Qual loja dá identidade ao SKU desta oferta.

    Coletor de uma loja só → o nome dele (comportamento de sempre). Agregador
    (Google Shopping) → a loja de origem de cada oferta (`vendedor`/source), pra
    N lojas de uma busca virarem N SKUs, não colapsarem num só. Ver PLANO passo 5.
    """
    if getattr(coletor, "agrega_lojas", False) and oferta.vendedor:
        return oferta.vendedor
    return coletor.nome


def _melhor(candidatas: list[_Candidata]) -> _Candidata:
    """A melhor oferta de uma loja: em estoque primeiro, menor preço final,
    empate desfeito pelo maior score de matching."""
    return min(
        candidatas,
        key=lambda c: (not c.oferta.em_estoque, _preco_final_de(c.oferta), -c.score),
    )


def _preco_final_de(oferta: OfertaBruta) -> Decimal:
    """Preço final à vista de uma oferta (§16). No V1, sem cupom/cashback."""
    return calcular_preco_final(
        preco=oferta.preco,
        preco_avista=oferta.preco_avista,
        frete=oferta.frete,
        frete_cotado=oferta.frete_cotado,
    )


def _descricao_de(produto: Produto) -> str:
    """Monta o texto de busca a partir dos campos que identificam o produto."""
    partes = [produto.nome, produto.marca or "", produto.modelo or ""]
    return " ".join(p for p in partes if p).strip()
