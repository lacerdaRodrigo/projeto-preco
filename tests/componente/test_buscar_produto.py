"""Testes do maestro BuscarProduto (§13/§23).

Usa um COLETOR FAKE (nada de loja real) + repositórios SQLite em memória.
Prova as propriedades do §13: resiliente por loja (RN08), idempotente (RN11),
matching filtra o lixo e o ranking sai pelo preço final (§16).
"""

import asyncio
from decimal import Decimal

import pytest

from adapters.repositorios.sqlite import (
    RepositorioProdutoSQLite,
    RepositorioSKUSQLite,
    RepositorioSnapshotSQLite,
    conectar,
)
from application.buscar_produto import BuscarProduto, ProdutoInexistente
from application.coletores import ColetorQuebrado, LojaIndisponivel
from domain import OfertaBruta, Produto

CONTA = 1


class ColetorFake:
    """Coletor de mentira: devolve ofertas fixas ou levanta um erro."""

    def __init__(self, nome, loja_id, ofertas=None, erro=None):
        self.nome = nome
        self.loja_id = loja_id
        self.tipo = "marketplace"
        self.fonte = "api"
        self.rate_limit_ms = 0
        self._ofertas = ofertas or []
        self._erro = erro

    async def buscar(self, descricao, cep=None):
        if self._erro is not None:
            raise self._erro
        return list(self._ofertas)


class ColetorAgregadorFake(ColetorFake):
    """Simula um agregador (Google Shopping): UMA busca traz N lojas (source)."""

    agrega_lojas = True


def _oferta(titulo, preco, frete=None, frete_cotado=False, em_estoque=True, vendedor=None):
    return OfertaBruta(
        titulo=titulo,
        preco=Decimal(preco),
        url=f"http://loja/{titulo.replace(' ', '-')}",
        frete=Decimal(frete) if frete is not None else None,
        frete_cotado=frete_cotado,
        em_estoque=em_estoque,
        vendedor=vendedor,
    )


@pytest.fixture
def con():
    conexao = conectar(":memory:")
    yield conexao
    conexao.close()


def _monta(con, coletores):
    """Cria os repos, salva um produto e devolve (caso_de_uso, produto_id, repos)."""
    repo_p = RepositorioProdutoSQLite(con)
    repo_s = RepositorioSKUSQLite(con)
    repo_sn = RepositorioSnapshotSQLite(con)
    produto = repo_p.salvar(Produto(nome="Echo Dot 5", categoria="eletronicos"), CONTA)
    uc = BuscarProduto(coletores, repo_p, repo_s, repo_sn)
    return uc, produto.id, (repo_p, repo_s, repo_sn)


def test_fluxo_completo_casa_calcula_e_grava(con):
    coletor = ColetorFake(
        "Mercado Livre",
        1,
        ofertas=[
            _oferta("Echo Dot 5 Smart Speaker", "299.90"),  # casa
            _oferta("Cadeira Gamer ThunderX3", "1200.00"),  # não casa
        ],
    )
    uc, produto_id, (_, repo_s, repo_sn) = _monta(con, [coletor])

    resultado = asyncio.run(uc.executar(produto_id, CONTA))

    assert len(resultado.ranking) == 1
    assert resultado.descartadas == 1
    assert resultado.ranking[0].preco_final == Decimal("299.90")
    # Persistiu: virou SKU + snapshot.
    skus = repo_s.de_produto(produto_id, CONTA)
    assert len(skus) == 1
    assert repo_sn.ultimo_snapshot(skus[0].id, CONTA) is not None


def test_varias_ofertas_da_mesma_loja_viram_um_sku_o_melhor(con):
    # RN01: a loja devolve vários anúncios do mesmo produto → 1 SKU (o melhor).
    coletor = ColetorFake(
        "ML",
        1,
        ofertas=[
            _oferta("Echo Dot 5 caro", "349.00"),
            _oferta("Echo Dot 5 barato", "289.90"),  # melhor preço final
            _oferta("Echo Dot 5 medio", "319.00"),
        ],
    )
    uc, produto_id, (_, repo_s, _) = _monta(con, [coletor])

    resultado = asyncio.run(uc.executar(produto_id, CONTA))

    assert len(repo_s.de_produto(produto_id, CONTA)) == 1  # 1 SKU por loja
    assert len(resultado.ranking) == 1
    assert resultado.ranking[0].preco_final == Decimal("289.90")  # o mais barato


def test_rodar_duas_vezes_nao_duplica_snapshot(con):
    # Várias ofertas por loja (o cenário que quebrava a idempotência antes).
    coletor = ColetorFake(
        "ML",
        1,
        ofertas=[
            _oferta("Echo Dot 5 A", "349.00"),
            _oferta("Echo Dot 5 B", "289.90"),
            _oferta("Echo Dot 5 C", "319.00"),
        ],
    )
    uc, produto_id, _ = _monta(con, [coletor])

    asyncio.run(uc.executar(produto_id, CONTA))
    asyncio.run(uc.executar(produto_id, CONTA))

    total = con.execute("SELECT COUNT(*) c FROM snapshot_preco").fetchone()["c"]
    assert total == 1  # RN11: rodar 2x = mesmo estado, sem thrashing de SKU


def test_loja_indisponivel_nao_derruba_as_outras(con):
    quebrada = ColetorFake("Loja Fora", 2, erro=LojaIndisponivel("timeout"))
    boa = ColetorFake("ML", 1, ofertas=[_oferta("Echo Dot 5", "299.90")])
    uc, produto_id, _ = _monta(con, [quebrada, boa])

    resultado = asyncio.run(uc.executar(produto_id, CONTA))

    assert resultado.lojas_indisponiveis == ["Loja Fora"]
    assert len(resultado.ranking) == 1  # a boa entregou mesmo assim (RN08)


def test_coletor_quebrado_marca_degradado_e_nao_grava(con):
    degradada = ColetorFake("ML", 1, erro=ColetorQuebrado("html mudou"))
    uc, produto_id, (_, repo_s, _) = _monta(con, [degradada])

    resultado = asyncio.run(uc.executar(produto_id, CONTA))

    assert resultado.lojas_degradadas == ["ML"]
    assert resultado.ranking == []
    assert repo_s.de_produto(produto_id, CONTA) == []  # RN12: nada gravado


def test_ranking_ordena_por_preco_final_entre_lojas_com_frete(con):
    # Duas lojas: a "mais barata na vitrine" perde quando some o frete (§16).
    loja_a = ColetorFake(
        "Loja A", 1,
        ofertas=[_oferta("Echo Dot 5", "100.00", frete="10.00", frete_cotado=True)],  # 110
    )
    loja_b = ColetorFake(
        "Loja B", 2,
        ofertas=[_oferta("Echo Dot 5", "105.00")],  # 105 (mais barato no final)
    )
    uc, produto_id, _ = _monta(con, [loja_a, loja_b])

    resultado = asyncio.run(uc.executar(produto_id, CONTA))

    finais = [(o.loja, o.preco_final) for o in resultado.ranking]
    assert finais == [("Loja B", Decimal("105.00")), ("Loja A", Decimal("110.00"))]


def test_agregador_vira_um_sku_por_loja_de_origem(con):
    # Passo 5 do PLANO: 1 coletor (Google Shopping) traz N lojas (source). Cada
    # loja de origem vira SEU SKU — não colapsa tudo num só.
    agregador = ColetorAgregadorFake(
        "Google Shopping",
        10,
        ofertas=[
            _oferta("Echo Dot 5", "327.85", vendedor="Mercado Livre"),
            _oferta("Echo Dot 5", "299.90", vendedor="Magalu"),
            _oferta("Echo Dot 5", "349.00", vendedor="Carrefour"),
            # 2 anúncios da MESMA loja de origem → 1 SKU só (o mais barato).
            _oferta("Echo Dot 5 outro", "289.90", vendedor="Magalu"),
        ],
    )
    uc, produto_id, (_, repo_s, _) = _monta(con, [agregador])

    resultado = asyncio.run(uc.executar(produto_id, CONTA))

    # 3 lojas de origem distintas → 3 SKUs (Magalu não duplicou).
    assert len(repo_s.de_produto(produto_id, CONTA)) == 3
    lojas = {o.loja for o in resultado.ranking}
    assert lojas == {"Mercado Livre", "Magalu", "Carrefour"}
    # A oferta mais barata da Magalu (289.90) é a que representa a loja.
    magalu = next(o for o in resultado.ranking if o.loja == "Magalu")
    assert magalu.preco_final == Decimal("289.90")
    # Ranking global pela mais barata primeiro.
    assert resultado.ranking[0].loja == "Magalu"


def test_produto_inexistente_da_erro(con):
    uc, _, _ = _monta(con, [ColetorFake("ML", 1)])
    with pytest.raises(ProdutoInexistente):
        asyncio.run(uc.executar(999, CONTA))
