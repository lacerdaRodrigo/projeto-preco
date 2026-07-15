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
    _ancora,
    _e_dominio_br,
    _e_link_de_produto,
    _loja_br_conhecida,
    _loja_plausivelmente_br,
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
    # O Zoom resolveu a página BR (domínio casa) → preço CONFIRMADO da página.
    zoom = next(o for o in ofertas if o.vendedor == "Zoom")
    assert zoom.url == direto
    assert zoom.preco == Decimal("449.90")  # preço da PÁGINA, não do Google
    assert zoom.titulo == "Echo Dot 5 Geração"  # nome da PÁGINA
    assert zoom.preco_confirmado is True
    # As renomadas BR que não resolveram página não somem: entram como vitrine.
    assert any(o.vendedor == "KaBuM!" and o.preco_confirmado is False for o in ofertas)


@respx.mock
def test_pagina_br_sem_preco_vira_vitrine():
    # Achou a página BR mas sem preço, e sem scrape → NÃO some: entra com o preço
    # de vitrine do Google Shopping, marcado (a página .br já verifica que é BR).
    respx.post(_URL).mock(return_value=httpx.Response(200, json=_FIXTURE))
    direto = "https://www.zoom.com.br/produto/echo-dot-5-alexa"
    respx.post(_URL_ORGANICA).mock(
        return_value=httpx.Response(200, json={"organic": [{"link": direto}]})
    )
    respx.get(direto).mock(return_value=httpx.Response(200, html="<html>sem preço</html>"))
    coletor = ColetorGoogleShopping("chave-fake", usar_scrape=False)
    ofertas = asyncio.run(coletor.buscar("echo dot 5"))
    zoom = next(o for o in ofertas if o.vendedor == "Zoom")
    assert zoom.preco_confirmado is False
    assert zoom.preco == Decimal("443.33")  # preço de vitrine do Google Shopping
    assert zoom.url == direto  # a página BR foi resolvida mesmo assim


_SCRAPE_JSONLD = {
    "jsonld": {
        "@type": "Product",
        "name": "Purificador Electrolux PE12G",
        "offers": {"@type": "Offer", "price": "632.31"},
    }
}


@respx.mock
def test_loja_bloqueada_confirma_preco_via_scrape():
    # httpx dá 403 (anti-bot), mas o Serper scrape renderiza e devolve o preço
    # REAL no jsonld → a loja entra com preço CONFIRMADO (não vitrine).
    respx.post(_URL).mock(return_value=httpx.Response(200, json=_FIXTURE))
    direto = "https://www.zoom.com.br/produto/echo-dot-5-alexa"  # casa a loja "Zoom"
    respx.post(_URL_ORGANICA).mock(
        return_value=httpx.Response(200, json={"organic": [{"link": direto}]})
    )
    respx.get(direto).mock(return_value=httpx.Response(403, html="bloqueado"))
    respx.post("https://scrape.serper.dev").mock(
        return_value=httpx.Response(200, json=_SCRAPE_JSONLD)
    )
    ofertas = asyncio.run(ColetorGoogleShopping("chave-fake").buscar("echo dot 5"))
    zoom = next(o for o in ofertas if o.vendedor == "Zoom")
    assert zoom.preco == Decimal("632.31")  # preço do scrape, confirmado
    assert zoom.titulo == "Purificador Electrolux PE12G"
    assert zoom.url == direto


@respx.mock
def test_scrape_sem_preco_vira_vitrine():
    # Página BR achada, mas nem httpx nem scrape leram preço (ex.: tela de login)
    # → não some: vira vitrine (marcada).
    respx.post(_URL).mock(return_value=httpx.Response(200, json=_FIXTURE))
    direto = "https://www.zoom.com.br/produto/echo-dot-5-alexa"
    respx.post(_URL_ORGANICA).mock(
        return_value=httpx.Response(200, json={"organic": [{"link": direto}]})
    )
    respx.get(direto).mock(return_value=httpx.Response(403))
    respx.post("https://scrape.serper.dev").mock(
        return_value=httpx.Response(200, json={"text": "Faça login", "metadata": {}})
    )
    ofertas = asyncio.run(ColetorGoogleShopping("chave-fake").buscar("echo dot 5"))
    zoom = next(o for o in ofertas if o.vendedor == "Zoom")
    assert zoom.preco_confirmado is False
    assert zoom.preco == Decimal("443.33")


@respx.mock
def test_pagina_nao_resolve_loja_br_conhecida_vira_vitrine():
    # Orgânico não acha a página do produto (só lista/categoria). Loja BR RENOMADA
    # não some: entra como VITRINE (a IA valida a identidade depois). Sem isto,
    # produto pouco indexado voltava 0 loja. Comparador/loja desconhecida fica fora.
    respx.post(_URL).mock(return_value=httpx.Response(200, json=_FIXTURE))
    lista = "https://www.zoom.com.br/smart-speaker"  # categoria, não produto
    respx.post(_URL_ORGANICA).mock(
        return_value=httpx.Response(200, json={"organic": [{"link": lista}]})
    )
    ofertas = asyncio.run(ColetorGoogleShopping("chave-fake").buscar("echo dot 5"))
    lojas = {o.vendedor for o in ofertas}
    assert "KaBuM!" in lojas and "Carrefour" in lojas  # renomadas entram
    assert "Zoom" not in lojas  # comparador, não é loja → fora
    assert all(o.preco_confirmado is False for o in ofertas)  # todas vitrine


@respx.mock
def test_sem_pagina_e_loja_desconhecida_fica_de_fora():
    # Resolução falha (500) para todas. Loja BR conhecida entra como vitrine; loja
    # fora da lista (provável estrangeira: eBay/Amazon-EUA/asus.com) fica de fora.
    respx.post(_URL).mock(return_value=httpx.Response(200, json=_FIXTURE))
    respx.post(_URL_ORGANICA).mock(return_value=httpx.Response(500))
    ofertas = asyncio.run(ColetorGoogleShopping("chave-fake").buscar("echo dot 5"))
    lojas = {o.vendedor for o in ofertas}
    assert "KaBuM!" in lojas and "Carrefour" in lojas and "Mercado Livre" in lojas
    assert "Zoom" not in lojas


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


def test_ancora_encurta_a_query_de_resolucao():
    # A resolução do link usa só a âncora (marca+modelo), não as specs — senão o
    # orgânico não acha a página do produto.
    assert _ancora("Asus TUF Gaming A15 RTX 3050 512GB") == "Asus TUF Gaming A15"
    assert _ancora("Motorola Moto G67") == "Motorola Moto G67"


def test_loja_br_conhecida_reconhece_renomadas():
    assert _loja_br_conhecida("Casas Bahia - Seller")  # substring + sufixo
    assert _loja_br_conhecida("KaBuM!")
    assert _loja_br_conhecida("Magazine Luiza")
    assert _loja_br_conhecida("Carrefour")
    assert not _loja_br_conhecida("Zoom")  # comparador, não é loja
    assert not _loja_br_conhecida("eBay")  # estrangeira
    assert not _loja_br_conhecida("Desertcart")
    assert not _loja_br_conhecida(None)


def test_loja_plausivelmente_br_barra_nome_estrangeiro():
    assert _loja_plausivelmente_br("KaBuM!")
    assert _loja_plausivelmente_br("Casas Bahia")
    assert _loja_plausivelmente_br("Amazon.com.br - Retail")
    assert _loja_plausivelmente_br(None)  # sem nome → deixa o matcher julgar
    assert not _loja_plausivelmente_br("Máy tính Tiến Tân")  # vietnamita (U+1EBF)


def test_e_dominio_br_barra_loja_estrangeira():
    # Conserta o Amazon: "Amazon.com.br" às vezes resolve pro amazon.com (EUA).
    assert _e_dominio_br("https://www.amazon.com.br/Echo/dp/B09")
    assert _e_dominio_br("https://www.kabum.com.br/produto/1/echo")
    assert _e_dominio_br("https://produto.mercadolivre.com.br/MLB-123-echo-_JM")
    assert not _e_dominio_br("https://www.amazon.com/Echo/dp/B09")  # EUA
    assert not _e_dominio_br("https://maytinh.example.vn/p/1")  # estrangeira


def test_e_link_de_produto():
    assert _e_link_de_produto("https://www.kabum.com.br/produto/460471/echo")
    assert _e_link_de_produto("https://loja.com.br/echo-dot-5-preto-123/p")
    assert _e_link_de_produto("https://www.amazon.com.br/Echo/dp/B09B8VGCR8")
    assert _e_link_de_produto("https://www.amazon.com.br/gp/product/B09B8VGCR8")
    # Mercado Livre (/p/MLB...) e Magazine Luiza (/p/241.../) → são produto:
    assert _e_link_de_produto("https://www.mercadolivre.com.br/echo-dot/p/MLB123")
    assert _e_link_de_produto("https://www.magazineluiza.com.br/echo/p/241203500/te/")
    # Mercado Livre forma clássica (/MLB-...-_JM, sem /p/) — a maioria das ofertas:
    assert _e_link_de_produto("https://produto.mercadolivre.com.br/MLB-123456789-echo-dot-5-_JM")
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
