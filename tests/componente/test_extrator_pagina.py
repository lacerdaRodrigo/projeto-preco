"""Testes do extrator por página (HTML gravado + respx; nunca ao vivo).

Cobre a escada de identidade (código forte → marca → atributos no título) com os
dois exemplos do PLANO — notebook (tem código) e mesa (só atributos) — e a
degradação (RN12): bloqueio/sem dado/preço absurdo → None (fallback de título).
"""

import asyncio
from decimal import Decimal

import httpx
import respx

from adapters.extratores.pagina import LeitorDePagina, extrair_referencia

# --- Exemplo 1 do PLANO: notebook (identidade por CÓDIGO) --------------------
_HTML_NOTEBOOK = """<html><head>
<script type="application/ld+json">
{"@type":"Product",
 "name":"Notebook Acer Aspire 5 A515-45-R2A3 Ryzen 5 8GB 512GB SSD",
 "brand":{"@type":"Brand","name":"Acer"},
 "gtin13":"7899888777666","mpn":"A515-45-R2A3","color":"Prata",
 "category":"Informática > Notebooks",
 "offers":{"@type":"Offer","price":"2459.00","priceCurrency":"BRL"}}
</script></head><body>...</body></html>"""

# --- Exemplo 2 do PLANO: mesa 4 cadeiras (identidade por ATRIBUTOS) -----------
_HTML_MESA = """<html><head>
<script type="application/ld+json">
{"@graph":[
 {"@type":"BreadcrumbList"},
 {"@type":"Product",
  "name":"Conjunto Sala de Jantar Madesa Lily Mesa 4 Cadeiras Preto",
  "brand":"Madesa",
  "offers":[{"@type":"Offer","price":"899.90"}]}
]}
</script></head><body>...</body></html>"""


def test_notebook_extrai_identidade_por_codigo():
    ref = extrair_referencia(_HTML_NOTEBOOK, "https://loja.com.br/produto/aspire-5")
    assert ref is not None
    assert ref.titulo.startswith("Notebook Acer Aspire 5 A515-45-R2A3")
    assert ref.marca == "Acer"
    assert ref.ean == "7899888777666"  # GTIN — portão forte
    assert ref.modelo == "A515-45-R2A3"  # MPN
    assert ref.cor == "Prata"
    assert ref.preco == Decimal("2459.00")


def test_mesa_extrai_identidade_por_atributos_no_titulo():
    # Sem código forte: a identidade vive no título ("4 Cadeiras Preto") + marca.
    ref = extrair_referencia(_HTML_MESA, "https://loja.com.br/produto/conjunto-lily")
    assert ref is not None
    assert ref.marca == "Madesa"
    assert ref.ean is None and ref.modelo is None  # móvel não tem código
    assert "4 Cadeiras" in ref.titulo and "Preto" in ref.titulo
    assert ref.preco == Decimal("899.90")  # offers como lista → 1ª


def test_referencia_vira_produto_pronto_pro_matching():
    ref = extrair_referencia(_HTML_NOTEBOOK, "https://loja.com.br/produto/aspire-5")
    assert ref is not None
    produto = ref.para_produto()
    assert produto.nome == ref.titulo
    assert produto.marca == "Acer"
    assert produto.ean == "7899888777666"
    assert produto.modelo == "A515-45-R2A3"
    assert produto.categoria == "Informática > Notebooks"
    assert produto.preco_referencia == Decimal("2459.00")


def test_gtin_e_normalizado_para_so_digitos():
    html = """<script type="application/ld+json">
    {"@type":"Product","name":"X","gtin13":"789-988 877.7666",
     "offers":{"price":"10.00"}}</script>"""
    ref = extrair_referencia(html, "https://loja.com.br/p/x")
    assert ref is not None and ref.ean == "7899888777666"


def test_cai_no_og_title_quando_json_ld_nao_tem_nome():
    html = ('<meta property="og:title" content="Cadeira Gamer &amp; Apoio">'
            '<script type="application/ld+json">'
            '{"@type":"Product","offers":{"price":"599.00"}}</script>')
    ref = extrair_referencia(html, "https://loja.com.br/p/cadeira")
    assert ref is not None
    assert ref.titulo == "Cadeira Gamer & Apoio"  # desescapa entidade HTML
    assert ref.preco == Decimal("599.00")


def test_preco_pela_meta_open_graph_formato_br():
    html = ('<meta property="product:price:amount" content="1.234,56">'
            '<script type="application/ld+json">'
            '{"@type":"Product","name":"Mesa"}</script>')
    ref = extrair_referencia(html, "https://loja.com.br/p/mesa")
    assert ref is not None and ref.preco == Decimal("1234.56")


def test_url_e_limpa_de_rastreio():
    ref = extrair_referencia(
        _HTML_NOTEBOOK,
        "https://loja.com.br/produto/aspire-5?srsltid=AbC&utm_source=google",
    )
    assert ref is not None
    assert ref.url == "https://loja.com.br/produto/aspire-5"


def test_sem_titulo_nao_identifica_devolve_none():
    # Página sem JSON-LD de produto e sem og:title → não dá pra identificar → None
    # (quem chamou cai pro fallback de título colado).
    assert extrair_referencia("<html><body>promoção</body></html>", "u") is None


def test_preco_absurdo_e_ignorado_mas_identidade_fica():
    # Preço ≤ 0 não é plausível (RN12): descarta o preço, mantém a identidade.
    html = """<script type="application/ld+json">
    {"@type":"Product","name":"Notebook X","offers":{"price":"0"}}</script>"""
    ref = extrair_referencia(html, "https://loja.com.br/p/x")
    assert ref is not None
    assert ref.titulo == "Notebook X"
    assert ref.preco is None


def test_json_ld_malformado_nao_estoura():
    html = ('<script type="application/ld+json">{ isso não é json }</script>'
            '<meta property="og:title" content="Produto Y">')
    ref = extrair_referencia(html, "https://loja.com.br/p/y")
    assert ref is not None and ref.titulo == "Produto Y"


# --- Leitor de rede (respx): degradação nunca deixa a falha vazar (RN12) ------

@respx.mock
def test_leitor_le_pagina_ok():
    url = "https://loja.com.br/produto/aspire-5"
    respx.get(url).mock(return_value=httpx.Response(200, html=_HTML_NOTEBOOK))
    ref = asyncio.run(LeitorDePagina().ler(url))
    assert ref is not None and ref.modelo == "A515-45-R2A3"


@respx.mock
def test_leitor_bloqueado_403_degrada_para_none():
    url = "https://www.amazon.com.br/dp/B0XYZ"
    respx.get(url).mock(return_value=httpx.Response(403, html="Robot Check"))
    assert asyncio.run(LeitorDePagina().ler(url)) is None


@respx.mock
def test_leitor_erro_de_rede_degrada_para_none():
    url = "https://loja-fora-do-ar.com.br/p/x"
    respx.get(url).mock(side_effect=httpx.ConnectError("sem rede"))
    assert asyncio.run(LeitorDePagina().ler(url)) is None
