"""Testes do comando `rastrear` (a porta da frente, PLANO §1).

CLI de ponta a ponta com CliRunner: a rede é mockada (respx, nunca ao vivo) e o
banco é um arquivo temporário. Cobre o caminho principal (URL), o fallback
(--titulo) e a degradação quando a loja bloqueia.
"""

import httpx
import respx
from typer.testing import CliRunner

from adapters.repositorios.sqlite import RepositorioProdutoSQLite, conectar
from interface.cli import app

runner = CliRunner()

_HTML_NOTEBOOK = """<html><head>
<script type="application/ld+json">
{"@type":"Product",
 "name":"Notebook Acer Aspire 5 A515-45-R2A3 Ryzen 5 8GB 512GB SSD",
 "brand":{"@type":"Brand","name":"Acer"},
 "gtin13":"7899888777666","mpn":"A515-45-R2A3",
 "category":"Informática > Notebooks",
 "offers":{"@type":"Offer","price":"2459.00"}}
</script></head><body>...</body></html>"""


def _env(tmp_path):
    return {"DATABASE_URL": f"sqlite:///{tmp_path / 'precos.db'}"}


@respx.mock
def test_rastrear_url_captura_identidade_e_cadastra(tmp_path):
    url = "https://loja.com.br/produto/aspire-5"
    respx.get(url).mock(return_value=httpx.Response(200, html=_HTML_NOTEBOOK))

    resultado = runner.invoke(app, ["rastrear", url], env=_env(tmp_path))

    assert resultado.exit_code == 0, resultado.output
    assert "A515-45-R2A3" in resultado.output  # modelo capturado
    assert "Acer" in resultado.output  # marca
    assert "buscar" in resultado.output  # aponta o próximo passo
    # Cadastrou de fato, com a identidade rica pronta pro matching.
    con = conectar(str(tmp_path / "precos.db"))
    produtos = RepositorioProdutoSQLite(con).produtos_ativos(1)
    assert len(produtos) == 1
    assert produtos[0].ean == "7899888777666"
    assert produtos[0].modelo == "A515-45-R2A3"


@respx.mock
def test_rastrear_loja_bloqueada_orienta_o_fallback(tmp_path):
    url = "https://www.amazon.com.br/dp/B0XYZ"
    respx.get(url).mock(return_value=httpx.Response(403, html="Robot Check"))

    resultado = runner.invoke(app, ["rastrear", url], env=_env(tmp_path))

    assert resultado.exit_code == 1
    assert "--titulo" in resultado.output  # orienta o fallback


def test_rastrear_fallback_por_titulo_sem_url(tmp_path):
    resultado = runner.invoke(
        app,
        ["rastrear", "--titulo", "Conjunto Madesa Lily Mesa 4 Cadeiras Preto",
         "--categoria", "moveis"],
        env=_env(tmp_path),
    )

    assert resultado.exit_code == 0, resultado.output
    assert "Madesa" in resultado.output
    con = conectar(str(tmp_path / "precos.db"))
    produtos = RepositorioProdutoSQLite(con).produtos_ativos(1)
    assert len(produtos) == 1
    assert produtos[0].categoria == "moveis"  # --categoria sobrescreveu


def test_rastrear_sem_url_e_sem_titulo_erra(tmp_path):
    resultado = runner.invoke(app, ["rastrear"], env=_env(tmp_path))
    assert resultado.exit_code == 1
