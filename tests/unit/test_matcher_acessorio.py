"""Testes do veto de acessório/peça (§C) — não confundir o produto com sua peça."""

from decimal import Decimal

from domain import OfertaBruta, Produto
from domain.matching import Destino, Etapa, casar


def _oferta(titulo: str) -> OfertaBruta:
    return OfertaBruta(titulo=titulo, preco=Decimal("100.00"), url="http://x")


def _purificador() -> Produto:
    return Produto(
        nome="Purificador de Água Electrolux PE12G Painel Touch Cinza",
        categoria="eletronicos", marca="Electrolux", modelo="PE12G",
    )


def test_refil_do_purificador_e_vetado():
    for acessorio in [
        "Kit Refil Filtro Compatível Electrolux Pe12g",
        "Refil Purificador Electrolux PE12G",
        "Bomba Pressurizadora Purificador Electrolux Pe12g",
        "Pingadeira Original Para Purificador Pe12g Electrolux",
        "Gabinete Cinza Para Purificador Electrolux PE12G",
    ]:
        r = casar(_purificador(), _oferta(acessorio))
        assert r.destino is Destino.DESCARTA, acessorio
        assert r.etapa is Etapa.VETO, acessorio


def test_o_purificador_de_verdade_passa():
    r = casar(_purificador(), _oferta("Purificador de Água Electrolux PE12G Bivolt Grafite"))
    assert r.destino is Destino.ACEITA


def test_mouse_para_notebook_e_vetado():
    produto = Produto(nome="Notebook Asus TUF Gaming A15", categoria="notebook",
                      marca="Asus", modelo="A15")
    r = casar(produto, _oferta("Mouse Preto RGB Para ASUS TUF Gaming A15"))
    assert r.destino is Destino.DESCARTA
    assert r.etapa is Etapa.VETO


def test_quem_rastreia_o_refil_nao_e_vetado():
    # Se o MEU produto é um refil, "refil" está no meu nome → o veto se desarma.
    produto = Produto(nome="Refil Filtro Electrolux PE12G Original",
                      categoria="eletronicos", marca="Electrolux", modelo="PE12G")
    r = casar(produto, _oferta("Refil Filtro Original Electrolux PE12G"))
    assert r.destino is Destino.ACEITA
