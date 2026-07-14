"""Testes do coletor de demonstração (mesmo rigor dos outros: JSON gravado + respx)."""

import asyncio
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from adapters.coletores.sandbox import ColetorSandbox, parsear_busca
from application.coletores import ColetorQuebrado, LojaIndisponivel

_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "sandbox_busca.json").read_text(
        encoding="utf-8"
    )
)
_URL = "https://dummyjson.com/products/search"


def test_parse_ignora_item_sem_preco():
    ofertas = parsear_busca(_FIXTURE)
    assert len(ofertas) == 2  # o de preço null foi pulado


def test_parse_mapeia_campos():
    oferta = parsear_busca(_FIXTURE)[0]
    assert oferta.titulo == "iPhone 13 Pro"
    assert oferta.preco == Decimal("1099.99")
    assert oferta.url.endswith("/products/121")
    assert oferta.em_estoque is True


def test_parse_estoque_zero_vira_indisponivel():
    assert parsear_busca(_FIXTURE)[1].em_estoque is False  # stock == 0


def test_parse_estrutura_inesperada_quebra():
    with pytest.raises(ColetorQuebrado):
        parsear_busca({"foo": 1})


@respx.mock
def test_busca_ok():
    respx.get(_URL).mock(return_value=httpx.Response(200, json=_FIXTURE))
    ofertas = asyncio.run(ColetorSandbox().buscar("iphone"))
    assert len(ofertas) == 2


@respx.mock
def test_erro_5xx_vira_indisponivel():
    respx.get(_URL).mock(return_value=httpx.Response(502))
    with pytest.raises(LojaIndisponivel):
        asyncio.run(ColetorSandbox().buscar("iphone"))
