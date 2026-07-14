"""Testes do fallback por slug da URL (PLANO §1b) — puro, sem rede.

Quando a loja bloqueia a leitura da página, o nome do produto ainda está no
endereço. Cobre os casos reais que bloquearam (ML, Magalu).
"""

from adapters.extratores.texto import extrair_do_slug


def test_slug_do_magalu():
    url = ("https://www.magazineluiza.com.br/smartphone-motorola-moto-g67-5g-256gb"
           "-12gb-4gb-ram-8gb-ram-boost/p/241203500/te/motg/?utm_source=google")
    ref = extrair_do_slug(url)
    assert ref is not None
    assert ref.titulo == "smartphone motorola moto g67 5g 256gb 12gb 4gb ram 8gb ram boost"
    # A URL fica (rastreável), mas sem os parâmetros de rastreio.
    assert ref.url.endswith("/te/motg/")
    assert "utm_source" not in ref.url


def test_slug_do_mercado_livre():
    url = ("https://www.mercadolivre.com.br/bicicleta-gts-feel-aro-29-24v-freio-disco"
           "-cor-preto/p/MLB54841628?gclid=xyz")
    ref = extrair_do_slug(url)
    assert ref is not None
    assert ref.titulo == "bicicleta gts feel aro 29 24v freio disco cor preto"
    # Ignora o id da loja (MLB54841628 não tem hífen) e pega o segmento descritivo.


def test_slug_puxa_ean_se_estiver_na_url():
    url = "https://loja.com.br/produto-legal-7899888777666/p"
    ref = extrair_do_slug(url)
    assert ref is not None and ref.ean == "7899888777666"


def test_url_sem_slug_descritivo_devolve_none():
    # Só ids/segmentos sem hífen → não dá título → None (cai pro --titulo).
    assert extrair_do_slug("https://loja.com.br/p/241203500") is None
    assert extrair_do_slug("https://loja.com.br/") is None
