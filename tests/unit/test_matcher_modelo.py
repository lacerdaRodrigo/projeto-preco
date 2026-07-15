"""Testes do portão de part-number (PLANO §5) — o modelo forte no matcher."""

from decimal import Decimal

from domain import OfertaBruta, Produto
from domain.matching import Destino, Etapa, casar


def _oferta(titulo: str) -> OfertaBruta:
    return OfertaBruta(titulo=titulo, preco=Decimal("100.00"), url="http://x")


def test_part_number_hifenizado_aceita_quase_certeza():
    produto = Produto(nome="Notebook Acer Aspire 5", categoria="notebook",
                       modelo="A515-45-R2A3")
    r = casar(produto, _oferta("Acer Aspire 5 A515-45-R2A3 Ryzen 5 8GB 512GB"))
    assert r.destino is Destino.ACEITA
    assert r.etapa is Etapa.MODELO
    assert r.score == 0.95
    assert "A515-45-R2A3" in r.motivo


def test_part_number_ausente_no_titulo_nao_dispara():
    # Modelo diferente no título → o portão não aceita; segue o pipeline normal.
    produto = Produto(nome="Notebook Acer Aspire 5", categoria="notebook",
                      modelo="A515-45-R2A3")
    r = casar(produto, _oferta("Acer Aspire 5 A515-45-R74Z Ryzen 7 16GB"))
    assert r.etapa is not Etapa.MODELO  # R74Z não é R2A3


def test_nao_casa_por_prefixo_g67_em_g675():
    # Casa por token, não substring: modelo "AF-32" não bate em "AF-320".
    produto = Produto(nome="Airfryer Mondial", categoria="eletronicos", modelo="AF-32")
    r = casar(produto, _oferta("Airfryer Mondial AF-320 Family"))
    assert r.etapa is not Etapa.MODELO


def test_modelo_de_linha_sem_hifen_nao_auto_aceita():
    # "Moto G67" não fixa armazenamento → NÃO passa pelo portão de modelo; quem
    # decide é a capacidade/similaridade (256GB ≠ 128GB tem que poder descartar).
    produto = Produto(nome="Motorola Moto G67 256GB", categoria="celular",
                      modelo="Moto G67", atributos={"capacidade": "256gb"})
    r = casar(produto, _oferta("Motorola Moto G67 128GB"))
    assert r.etapa is not Etapa.MODELO
    assert r.destino is Destino.DESCARTA  # capacidade diverge (256 ≠ 128)


def test_veto_vence_o_part_number():
    # Acessório com o part-number exato ainda é descartado pelo veto (vem antes).
    produto = Produto(nome="Notebook Acer Aspire 5", categoria="notebook",
                      modelo="A515-45-R2A3", palavras_proibidas=("capa",))
    r = casar(produto, _oferta("Capa para Acer Aspire 5 A515-45-R2A3"))
    assert r.destino is Destino.DESCARTA
    assert r.etapa is Etapa.VETO


def test_numero_de_modelo_diferente_descarta():
    # O falso-positivo clássico: G17/G56/G77 NÃO são G67 (mudam 1 char do resto
    # igual). O número do modelo é portão, não token fraco.
    produto = Produto(nome="Motorola Moto G67 256GB", categoria="celular",
                      marca="Motorola", modelo="Moto G67")
    for errado in ("Smartphone Motorola Moto G17 256GB 5G",
                   "Motorola Moto G56 5G 256GB", "Motorola Moto G77 5G 256GB"):
        r = casar(produto, _oferta(errado))
        assert r.destino is Destino.DESCARTA, errado
        assert r.etapa is Etapa.MODELO, errado


def test_linha_confirmada_com_capacidade_ok_aceita():
    produto = Produto(nome="Motorola Moto G67 256GB", categoria="celular",
                      marca="Motorola", modelo="Moto G67")
    r = casar(produto, _oferta("Motorola Moto G67 5G 256GB Grafite"))
    assert r.destino is Destino.ACEITA
    assert r.etapa is Etapa.MODELO


def test_modelo_presente_sem_a_linha_ainda_casa():
    # "Motorola G67" (sem a palavra "Moto") tem o número g67 → é o mesmo modelo.
    produto = Produto(nome="Motorola Moto G67 256GB", categoria="celular",
                      marca="Motorola", modelo="Moto G67")
    r = casar(produto, _oferta("Motorola G67 Power 5G 256GB"))
    assert r.destino is Destino.ACEITA
    assert r.etapa is Etapa.MODELO
