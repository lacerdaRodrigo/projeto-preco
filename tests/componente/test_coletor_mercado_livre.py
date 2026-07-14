"""Testes do coletor do Mercado Livre (§12/§23).

Regra de ouro: NUNCA bate na loja real. O parse é validado contra JSON gravado
(`tests/fixtures/`); o comportamento de rede é simulado com `respx`.
"""

import asyncio
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from adapters.coletores.mercado_livre import ColetorMercadoLivre, parsear_busca
from application.coletores import ColetorQuebrado, LojaIndisponivel

_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "mercado_livre_busca.json").read_text(
        encoding="utf-8"
    )
)
_URL = "https://api.mercadolibre.com/sites/MLB/search"


# ---------- Parse puro (contra o JSON gravado) ----------

def test_parse_ignora_item_com_preco_absurdo():
    # São 3 resultados; o do preço null é pulado (RN12) → sobram 2.
    ofertas = parsear_busca(_FIXTURE)
    assert len(ofertas) == 2


def test_parse_mapeia_os_campos_da_primeira_oferta():
    oferta = parsear_busca(_FIXTURE)[0]
    assert oferta.titulo.startswith("Notebook Asus Vivobook 15 16GB")
    assert oferta.preco == Decimal("3499.90")  # dinheiro, não float
    assert oferta.url.endswith("MLB-1111111111")
    assert oferta.ean == "0195553777777"
    assert oferta.em_estoque is True
    assert oferta.vendedor == "ASUS OFICIAL"
    assert oferta.vendedor_oficial is True


def test_parse_frete_gratis_e_cotado_como_zero():
    oferta = parsear_busca(_FIXTURE)[0]
    assert oferta.frete_cotado is True
    assert oferta.frete == Decimal("0.00")


def test_parse_sem_frete_gratis_nao_inventa_frete():
    # RN09: sem cotação, frete_cotado=False e não chuta valor.
    oferta = parsear_busca(_FIXTURE)[1]
    assert oferta.frete_cotado is False
    assert oferta.frete is None
    assert oferta.em_estoque is False  # available_quantity == 0


def test_parse_sem_juros_so_quando_taxa_zero():
    com_juros, sem_juros = parsear_busca(_FIXTURE)[1], parsear_busca(_FIXTURE)[0]
    assert sem_juros.sem_juros is True   # rate == 0
    assert com_juros.sem_juros is False  # rate > 0


def test_parse_estrutura_inesperada_vira_coletor_quebrado():
    with pytest.raises(ColetorQuebrado):
        parsear_busca({"foo": "bar"})  # sem "results"


# ---------- Comportamento de rede (simulado com respx) ----------

@respx.mock
def test_busca_ok_devolve_ofertas():
    respx.get(_URL).mock(return_value=httpx.Response(200, json=_FIXTURE))
    ofertas = asyncio.run(ColetorMercadoLivre().buscar("notebook asus vivobook 15"))
    assert len(ofertas) == 2


@respx.mock
def test_busca_vazia_devolve_lista_vazia_nao_erro():
    # Vazio ≠ erro (contrato §12).
    respx.get(_URL).mock(return_value=httpx.Response(200, json={"results": []}))
    ofertas = asyncio.run(ColetorMercadoLivre().buscar("produto inexistente"))
    assert ofertas == []


@respx.mock
def test_erro_5xx_vira_loja_indisponivel():
    respx.get(_URL).mock(return_value=httpx.Response(503))
    with pytest.raises(LojaIndisponivel):
        asyncio.run(ColetorMercadoLivre().buscar("qualquer"))


@respx.mock
def test_403_sem_token_vira_loja_indisponivel_nao_quebrado():
    # 403 = falta de acesso/token, não parser quebrado → não aciona o canary.
    respx.get(_URL).mock(return_value=httpx.Response(403, json={"error": "forbidden"}))
    with pytest.raises(LojaIndisponivel):
        asyncio.run(ColetorMercadoLivre().buscar("qualquer"))


@respx.mock
def test_timeout_vira_loja_indisponivel():
    respx.get(_URL).mock(side_effect=httpx.TimeoutException("demorou"))
    with pytest.raises(LojaIndisponivel):
        asyncio.run(ColetorMercadoLivre().buscar("qualquer"))


@respx.mock
def test_resposta_nao_json_vira_coletor_quebrado():
    respx.get(_URL).mock(return_value=httpx.Response(200, text="<html>erro</html>"))
    with pytest.raises(ColetorQuebrado):
        asyncio.run(ColetorMercadoLivre().buscar("qualquer"))
