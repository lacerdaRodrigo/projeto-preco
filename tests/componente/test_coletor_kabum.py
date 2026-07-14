"""Testes do coletor do KaBuM! (JSON gravado + respx; nunca a loja ao vivo)."""

import asyncio
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from adapters.coletores.kabum import ColetorKabum, parsear_busca
from application.coletores import ColetorQuebrado, LojaIndisponivel

_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "kabum_busca.json").read_text(
        encoding="utf-8"
    )
)
_URL = "https://servicespub.prod.api.aws.grupokabum.com.br/catalog/v2/products"


def test_parse_ignora_item_sem_preco():
    assert len(parsear_busca(_FIXTURE)) == 2  # o de preço null é pulado (RN12)


def test_parse_primeiro_item_1p_com_desconto_e_frete():
    oferta = parsear_busca(_FIXTURE)[0]
    assert oferta.titulo.startswith("SSD 1TB Kingston NV2")
    assert oferta.preco == Decimal("532.57")
    assert oferta.preco_avista == Decimal("468.66")  # à vista (PIX) menor
    assert oferta.desconto_pix == Decimal("63.91")   # 532.57 - 468.66
    assert oferta.frete_cotado is True
    assert oferta.frete == Decimal("0.00")
    assert oferta.vendedor == "KaBuM!"
    assert oferta.vendedor_oficial is True
    assert oferta.url.endswith("/produto/426028/ssd-1tb-kingston-nv2")


def test_parse_marketplace_sem_desconto():
    oferta = parsear_busca(_FIXTURE)[1]
    # price_with_discount == price → não conta como à vista.
    assert oferta.preco_avista is None
    assert oferta.frete_cotado is False       # sem frete grátis, não inventa (RN09)
    assert oferta.vendedor == "EQUIPECLUB"
    assert oferta.vendedor_oficial is False   # é marketplace, não 1P


def test_parse_estrutura_inesperada_quebra():
    with pytest.raises(ColetorQuebrado):
        parsear_busca({"meta": {}})  # sem 'data'


@respx.mock
def test_busca_ok():
    respx.get(_URL).mock(return_value=httpx.Response(200, json=_FIXTURE))
    ofertas = asyncio.run(ColetorKabum().buscar("ssd kingston"))
    assert len(ofertas) == 2


@respx.mock
def test_erro_5xx_vira_indisponivel():
    respx.get(_URL).mock(return_value=httpx.Response(500))
    with pytest.raises(LojaIndisponivel):
        asyncio.run(ColetorKabum().buscar("ssd"))
