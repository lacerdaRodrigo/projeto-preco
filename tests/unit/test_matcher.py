"""Testes do pipeline de matching (§14), portão por portão.

Cada teste isola UMA etapa e confere também o *motivo* (explicabilidade é
requisito). Os pares realistas "é/não é" ficam no dataset de regressão.
"""

from decimal import Decimal

from domain import OfertaBruta, Produto
from domain.matching import Destino, Etapa, casar


def _oferta(titulo: str, ean: str | None = None) -> OfertaBruta:
    return OfertaBruta(titulo=titulo, preco=Decimal("100.00"), url="http://x", ean=ean)


def test_ean_igual_aceita_na_hora():
    produto = Produto(nome="Echo Dot 5", categoria="eletronicos", ean="7899999999999")
    r = casar(produto, _oferta("Qualquer título ruidoso", ean="7899999999999"))
    assert r.destino is Destino.ACEITA
    assert r.score == 1.0
    assert r.etapa is Etapa.EAN


def test_palavra_proibida_descarta():
    # "capa" proibida: o acessório não é o produto.
    produto = Produto(
        nome="Echo Dot 5", categoria="eletronicos", palavras_proibidas=("capa",)
    )
    r = casar(produto, _oferta("Capa para Echo Dot 5"))
    assert r.destino is Destino.DESCARTA
    assert r.etapa is Etapa.VETO
    assert "capa" in r.motivo


def test_palavra_obrigatoria_ausente_descarta():
    produto = Produto(
        nome="Galaxy S25", categoria="celular", palavras_obrigatorias=("ultra",)
    )
    r = casar(produto, _oferta("Samsung Galaxy S25 128GB"))  # sem "ultra"
    assert r.destino is Destino.DESCARTA
    assert r.etapa is Etapa.VETO
    assert "ultra" in r.motivo


def test_capacidade_divergente_descarta():
    # O exemplo do PRD: 8GB não é 16GB, mesmo com título parecidíssimo.
    produto = Produto(
        nome="Vivobook 15",
        categoria="notebook",
        atributos={"capacidade": "16gb"},
    )
    r = casar(produto, _oferta("Notebook Asus Vivobook 15 8GB"))
    assert r.destino is Destino.DESCARTA
    assert r.etapa is Etapa.ATRIBUTO
    assert "capacidade" in r.motivo


def test_titulos_muito_parecidos_aceita_por_similaridade():
    produto = Produto(
        nome="Galaxy S25 Ultra 512GB Preto", marca="Samsung", categoria="celular"
    )
    r = casar(produto, _oferta("Samsung Galaxy S25 Ultra Black 512 GB"))
    assert r.destino is Destino.ACEITA
    assert r.etapa is Etapa.SIMILARIDADE
    assert r.score >= 0.85


def test_titulo_sem_relacao_descarta_por_score_baixo():
    produto = Produto(nome="Echo Dot 5", categoria="eletronicos")
    r = casar(produto, _oferta("Cadeira Gamer ThunderX3"))
    assert r.destino is Destino.DESCARTA
    assert r.etapa is Etapa.SIMILARIDADE
    assert r.score < 0.6


def test_ean_diferente_nao_curto_circuita_segue_pipeline():
    # EAN só ACEITA quando bate; diferente/ausente segue para as outras etapas.
    produto = Produto(nome="Echo Dot 5", categoria="eletronicos", ean="111")
    r = casar(produto, _oferta("Cadeira Gamer", ean="222"))
    assert r.etapa is not Etapa.EAN
