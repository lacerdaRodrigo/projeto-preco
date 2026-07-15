"""Testes do extrator heurístico (PLANO §4) — puro, sem rede.

Tira a âncora (marca + modelo + categoria) dos títulos reais que o Rodrigo cola.
Conservador: na dúvida, None — nunca um palpite errado.
"""

import pytest

from adapters.extratores.heuristica import extrair_identidade


def test_moto_g67_linha_mais_token():
    ident = extrair_identidade(
        "Smartphone Motorola Moto G67 5G 256GB 12GB (4GB RAM + 8GB RAM Boost) "
        "Câmera 50MP Sony Lytia 600 Tela 1.5K Extreme Amoled 120Hz"
    )
    assert ident.marca == "Motorola"
    assert ident.modelo == "Moto G67"  # junta a linha ao número do modelo
    assert ident.categoria == "celular"  # "smartphone" -> categoria do matcher


def test_acer_part_number_com_hifen_tem_prioridade():
    ident = extrair_identidade("Notebook Acer Aspire 5 A515-45-R2A3 8GB 512GB SSD 15,6' FHD")
    assert ident.marca == "Acer"
    assert ident.modelo == "A515-45-R2A3"  # part-number vence "Aspire"
    assert ident.categoria == "notebook"


def test_specs_nao_viram_modelo():
    # "5G", "256GB", "120Hz", "50MP" são spec (dígito primeiro), nunca modelo.
    ident = extrair_identidade("Smartphone Motorola Moto G15 256GB 5G 120Hz Verde")
    assert ident.modelo == "Moto G15"


def test_movel_sem_codigo_nao_chuta_modelo():
    ident = extrair_identidade("Conjunto Sala de Jantar Madesa Lily Mesa 4 Cadeiras Preto")
    assert ident.marca == "Madesa"
    assert ident.modelo is None  # móvel não tem part-number; não inventa
    assert ident.categoria is None  # categoria de móvel não está no mapa -> geral depois


def test_marca_mais_cedo_vence():
    # Se aparecer mais de uma marca conhecida, vale a que vem antes.
    ident = extrair_identidade("Notebook Dell com tela Samsung")
    assert ident.marca == "Dell"


def test_titulo_de_slug_minusculo_tambem_funciona():
    # O fallback de slug entrega tudo minúsculo — a heurística tem que funcionar.
    ident = extrair_identidade("smartphone motorola moto g67 5g 256gb 12gb 4gb ram boost")
    assert ident.marca == "Motorola"
    assert ident.modelo == "Moto G67"
    assert ident.categoria == "celular"


def test_notebook_gamer_junta_a_linha_gaming():
    # "gaming"/"tuf" agora são linhas: o número sozinho ("a15") não identifica.
    ident = extrair_identidade(
        "Notebook Asus Tuf Gaming A15 3050 Ryzen 7 16gb 512gb Linux"
    )
    assert ident.marca == "Asus"
    assert ident.modelo == "Gaming A15"
    assert ident.categoria == "notebook"


@pytest.mark.parametrize("titulo", ["", "produto sem marca nem modelo conhecidos", "aro 29 preto"])
def test_sem_ancora_devolve_tudo_none(titulo):
    ident = extrair_identidade(titulo)
    assert ident.marca is None and ident.modelo is None
