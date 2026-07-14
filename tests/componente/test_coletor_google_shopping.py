"""Testes do coletor Google Shopping/Serper (JSON gravado + respx; nunca ao vivo)."""

import asyncio
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from adapters.coletores.google_shopping import (
    ColetorGoogleShopping,
    _e_link_de_produto,
    _extrair_da_pagina,
    _extrair_preco,
    _limpar_url,
    _parsear_preco_br,
    parsear_busca,
)
from application.coletores import ColetorQuebrado, LojaIndisponivel

_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "google_shopping_busca.json").read_text(
        encoding="utf-8"
    )
)
_URL = "https://google.serper.dev/shopping"
_URL_ORGANICA = "https://google.serper.dev/search"


def test_parse_traz_uma_oferta_por_loja():
    ofertas = parsear_busca(_FIXTURE)
    assert len(ofertas) == 6
    # A loja de origem (source) vai no vendedor — é o que separa os SKUs depois.
    lojas = [o.vendedor for o in ofertas]
    assert "Mercado Livre" in lojas and "KaBuM!" in lojas and "Carrefour" in lojas


def test_parse_preco_com_espaco_nao_quebravel_e_sufixo_agora():
    # "R$\xa0327,85 agora" — nbsp entre R$ e o número, e o sufixo " agora".
    primeira = parsear_busca(_FIXTURE)[0]
    assert primeira.vendedor == "Mercado Livre"
    assert primeira.preco == Decimal("327.85")


def test_parse_campos_basicos():
    o = parsear_busca(_FIXTURE, "echo dot 5")[0]
    assert o.titulo  # veio da loja
    # O link do shopping é morto: o fallback é uma busca escopada pela loja.
    assert o.url.startswith("https://www.google.com/search?q=")
    assert "Mercado" in o.url  # escopado pela loja de origem (source)
    assert o.frete_cotado is False  # Google Shopping não cota frete (RN09)
    assert o.em_estoque is True


@pytest.mark.parametrize(
    "bruto,esperado",
    [
        ("R$\xa0327,85 agora", Decimal("327.85")),
        ("R$ 489,00", Decimal("489.00")),
        ("R$ 1.234,56", Decimal("1234.56")),  # ponto de milhar BR
        ("R$ 10.999,90 agora", Decimal("10999.90")),
        ("Consulte o preço", None),  # sem valor → None (item é pulado)
        (None, None),
    ],
)
def test_parsear_preco_br(bruto, esperado):
    assert _parsear_preco_br(bruto) == esperado


def test_parse_estrutura_inesperada_quebra():
    with pytest.raises(ColetorQuebrado):
        parsear_busca({"organic": []})  # sem 'shopping'


def test_parse_busca_vazia_devolve_lista_vazia():
    assert parsear_busca({"shopping": []}) == []


def test_construtor_exige_chave():
    with pytest.raises(ValueError):
        ColetorGoogleShopping("")


@respx.mock
def test_busca_ok():
    respx.post(_URL).mock(return_value=httpx.Response(200, json=_FIXTURE))
    # Sem resolver link direto: testa só o encanamento do shopping.
    coletor = ColetorGoogleShopping("chave-fake", resolver_links_diretos=False)
    ofertas = asyncio.run(coletor.buscar("echo dot 5"))
    assert len(ofertas) == 6


_HTML_COM_PRECO = """<html><head>
<script type="application/ld+json">
{"@type":"Product","name":"Echo Dot 5 Geração","offers":{"@type":"Offer","price":"449.90"}}
</script></head><body>Echo Dot 5</body></html>"""


@respx.mock
def test_verifica_link_preco_e_nome_na_pagina_do_produto():
    # Descobrir no Serper → página do produto do Zoom → lê preço E nome REAIS dela.
    respx.post(_URL).mock(return_value=httpx.Response(200, json=_FIXTURE))
    direto = "https://www.zoom.com.br/produto/echo-dot-5-alexa"
    respx.post(_URL_ORGANICA).mock(
        return_value=httpx.Response(200, json={"organic": [{"link": direto}]})
    )
    respx.get(direto).mock(return_value=httpx.Response(200, html=_HTML_COM_PRECO))
    ofertas = asyncio.run(ColetorGoogleShopping("chave-fake").buscar("echo dot 5"))
    # Só o Zoom casou (domínio) e teve preço confirmado.
    assert [o.vendedor for o in ofertas] == ["Zoom"]
    assert ofertas[0].url == direto
    assert ofertas[0].preco == Decimal("449.90")  # preço da PÁGINA, não do Google
    assert ofertas[0].titulo == "Echo Dot 5 Geração"  # nome da PÁGINA, não do Google


@respx.mock
def test_pagina_sem_preco_descarta_loja():
    # Achou a página do produto, mas ela não expõe o preço → descarta.
    respx.post(_URL).mock(return_value=httpx.Response(200, json=_FIXTURE))
    direto = "https://www.zoom.com.br/produto/echo-dot-5-alexa"
    respx.post(_URL_ORGANICA).mock(
        return_value=httpx.Response(200, json={"organic": [{"link": direto}]})
    )
    respx.get(direto).mock(return_value=httpx.Response(200, html="<html>sem preço</html>"))
    ofertas = asyncio.run(ColetorGoogleShopping("chave-fake").buscar("echo dot 5"))
    assert ofertas == []


@respx.mock
def test_lista_de_busca_e_descartada():
    # Se o orgânico for uma LISTA (vários produtos), a loja é descartada.
    respx.post(_URL).mock(return_value=httpx.Response(200, json=_FIXTURE))
    lista = "https://www.zoom.com.br/smart-speaker"  # categoria, não produto
    respx.post(_URL_ORGANICA).mock(
        return_value=httpx.Response(200, json={"organic": [{"link": lista}]})
    )
    ofertas = asyncio.run(ColetorGoogleShopping("chave-fake").buscar("echo dot 5"))
    assert ofertas == []  # nenhuma virou página de produto


@respx.mock
def test_resolucao_falha_descarta_loja():
    # Falha na resolução → não traz link ruim: descarta a loja.
    respx.post(_URL).mock(return_value=httpx.Response(200, json=_FIXTURE))
    respx.post(_URL_ORGANICA).mock(return_value=httpx.Response(500))
    ofertas = asyncio.run(ColetorGoogleShopping("chave-fake").buscar("echo dot 5"))
    assert ofertas == []


def test_extrair_preco():
    # JSON-LD com offers.price (o padrão mais comum).
    assert _extrair_preco(_HTML_COM_PRECO) == Decimal("449.90")
    # JSON-LD dentro de @graph, com lowPrice e número (não string).
    grafo = """<script type="application/ld+json">
    {"@graph":[{"@type":"Product","offers":{"lowPrice":533.45}}]}</script>"""
    assert _extrair_preco(grafo) == Decimal("533.45")
    # Meta tag Open Graph como fallback, com formato BR.
    meta = '<meta property="product:price:amount" content="1.234,56">'
    assert _extrair_preco(meta) == Decimal("1234.56")
    # Sem preço estruturado → None (loja é descartada).
    assert _extrair_preco("<html>Echo Dot por um bom preço</html>") is None


def test_extrair_da_pagina_pega_preco_e_nome():
    preco, nome = _extrair_da_pagina(_HTML_COM_PRECO)
    assert preco == Decimal("449.90")
    assert nome == "Echo Dot 5 Geração"  # nome do produto na página
    # Sem JSON-LD name, cai no og:title (e desescapa entidades HTML).
    og = ('<meta property="og:title" content="Galaxy S26 Ultra 512GB &amp; Alexa">'
          '<script type="application/ld+json">{"offers":{"price":"9999.00"}}</script>')
    preco, nome = _extrair_da_pagina(og)
    assert preco == Decimal("9999.00")
    assert nome == "Galaxy S26 Ultra 512GB & Alexa"


def test_limpar_url_tira_rastreio():
    # Tira o srsltid (e utm_*), mantém o caminho do produto → URL canônica.
    suja = "https://infocellshop.com.br/produtos/echo-dot-5/?srsltid=AbC123&utm_source=x"
    assert _limpar_url(suja) == "https://infocellshop.com.br/produtos/echo-dot-5/"
    # Sem query → intocada.
    limpa = "https://www.kabum.com.br/produto/460471/echo-dot-5"
    assert _limpar_url(limpa) == limpa
    # Mantém query que NÃO é rastreio (ex.: variação de produto).
    com_sku = "https://loja.com.br/produto/echo?cor=preto"
    assert _limpar_url(com_sku) == com_sku


def test_e_link_de_produto():
    assert _e_link_de_produto("https://www.kabum.com.br/produto/460471/echo")
    assert _e_link_de_produto("https://loja.com.br/echo-dot-5-preto-123/p")
    assert _e_link_de_produto("https://www.amazon.com.br/Echo/dp/B09B8VGCR8")
    # Listas/buscas → não são produto:
    assert not _e_link_de_produto("https://lista.mercadolivre.com.br/echo-dot-5")
    assert not _e_link_de_produto("https://br.ebay.com/b/Amazon-Echo-Dot/184435")
    assert not _e_link_de_produto("https://shopee.com.br/list/Alexa")
    assert not _e_link_de_produto("https://www.google.com/search?q=echo+dot+5")


@respx.mock
def test_erro_5xx_vira_indisponivel():
    respx.post(_URL).mock(return_value=httpx.Response(503))
    with pytest.raises(LojaIndisponivel):
        asyncio.run(ColetorGoogleShopping("chave-fake").buscar("echo"))


@respx.mock
def test_chave_invalida_vira_quebrado():
    respx.post(_URL).mock(return_value=httpx.Response(403))
    with pytest.raises(ColetorQuebrado):
        asyncio.run(ColetorGoogleShopping("chave-ruim").buscar("echo"))
