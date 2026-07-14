"""Testes do fallback por título colado (PLANO §1b) — puro, sem rede."""

from adapters.extratores.texto import extrair_do_titulo


def test_titulo_vira_a_identidade():
    ref = extrair_do_titulo("  Conjunto Madesa Lily Mesa 4 Cadeiras Preto  ")
    assert ref is not None
    assert ref.titulo == "Conjunto Madesa Lily Mesa 4 Cadeiras Preto"  # sem espaços
    assert ref.url == "" and ref.preco is None  # não veio de página
    assert ref.para_produto().nome == "Conjunto Madesa Lily Mesa 4 Cadeiras Preto"


def test_puxa_ean_de_13_digitos_quando_escrito():
    ref = extrair_do_titulo("Echo Dot 5 EAN 7899888777666 Alexa")
    assert ref is not None and ref.ean == "7899888777666"


def test_sem_ean_fica_none_nao_chuta():
    # "A515-45-R2A3" e "512GB" NÃO viram EAN nem código — ficam só no título.
    ref = extrair_do_titulo("Notebook Acer Aspire 5 A515-45-R2A3 8GB 512GB SSD")
    assert ref is not None
    assert ref.ean is None
    assert "A515-45-R2A3" in ref.titulo  # o código sobrevive no título p/ o matcher


def test_titulo_vazio_devolve_none():
    assert extrair_do_titulo("   ") is None
    assert extrair_do_titulo("") is None
