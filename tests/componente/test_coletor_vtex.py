"""Testes do coletor VTEX genérico (JSON gravado + respx; nunca a loja ao vivo)."""

import asyncio
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from adapters.coletores.vtex import ColetorVTEX, parsear_busca
from application.coletores import ColetorQuebrado, LojaIndisponivel

_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "vtex_busca.json").read_text(
        encoding="utf-8"
    )
)
_DOMINIO = "www.americanas.com.br"
_URL = f"https://{_DOMINIO}/api/catalog_system/pub/products/search"


def _coletor() -> ColetorVTEX:
    return ColetorVTEX(_DOMINIO, loja_id=3, nome="Americanas")


def test_parse_ignora_produto_sem_oferta():
    assert len(parsear_busca(_FIXTURE, _DOMINIO)) == 2  # "sem oferta" foi pulado


def test_parse_primeiro_item_1p_disponivel():
    oferta = parsear_busca(_FIXTURE, _DOMINIO)[0]
    assert oferta.titulo == "Echo Dot 5 Geração Alexa Preto"
    assert oferta.preco == Decimal("279.00")
    assert oferta.ean == "0840080503417"
    assert oferta.em_estoque is True
    assert oferta.vendedor == "Americanas"
    assert oferta.vendedor_oficial is True  # sellerId "1" = a própria loja
    assert oferta.url.endswith("/echo-dot-5-geracao-alexa-preto/p")


def test_parse_marketplace_fora_de_estoque():
    oferta = parsear_busca(_FIXTURE, _DOMINIO)[1]
    assert oferta.em_estoque is False
    assert oferta.vendedor == "Loja Parceira"
    assert oferta.vendedor_oficial is False  # sellerId != "1"


def test_parse_resposta_nao_lista_quebra():
    with pytest.raises(ColetorQuebrado):
        parsear_busca({"products": []}, _DOMINIO)  # VTEX catalog é uma lista


@respx.mock
def test_busca_aceita_status_206():
    # VTEX devolve 206 (Partial Content) em busca com faixa — tem de valer como OK.
    respx.get(_URL).mock(return_value=httpx.Response(206, json=_FIXTURE))
    ofertas = asyncio.run(_coletor().buscar("echo dot"))
    assert len(ofertas) == 2


@respx.mock
def test_403_anti_bot_vira_indisponivel():
    respx.get(_URL).mock(return_value=httpx.Response(403))
    with pytest.raises(LojaIndisponivel):
        asyncio.run(_coletor().buscar("echo dot"))
