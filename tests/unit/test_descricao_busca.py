"""Testes da query de busca (PLANO §4/§6) — enxuta pela âncora, não verbosa."""

from domain import Produto
from application.buscar_produto import _descricao_de


def test_com_ancora_busca_enxuta_por_marca_e_modelo():
    # O título é verboso, mas a busca sai pela âncora (nenhuma loja titula igual
    # a string inteira).
    produto = Produto(
        nome="Smartphone Motorola Moto G67 5G 256GB 12GB Câmera 50MP Tela AMOLED",
        categoria="celular",
        marca="Motorola",
        modelo="Moto G67",
    )
    assert _descricao_de(produto) == "Motorola Moto G67"


def test_part_number_entra_na_busca():
    produto = Produto(nome="Notebook Acer Aspire 5 ...", categoria="notebook",
                      marca="Acer", modelo="A515-45-R2A3")
    assert _descricao_de(produto) == "Acer A515-45-R2A3"


def test_notebook_leva_specs_na_busca():
    # Notebook: "Asus Gaming A15" casa com dezenas de configs → a query leva o
    # discriminador forte (GPU) + armazenamento, sem virar a string inteira.
    produto = Produto(
        nome="Notebook Asus TUF Gaming A15 Ryzen 7 16GB 512GB RTX 3050",
        categoria="notebook", marca="Asus", modelo="Gaming A15",
        atributos={"gpu": "RTX 3050", "armazenamento": "512GB"},
    )
    assert _descricao_de(produto) == "Asus Gaming A15 RTX 3050 512GB"


def test_notebook_sem_specs_fica_so_na_ancora():
    # Sem atributos extraídos, cai no comportamento de sempre (marca + modelo).
    produto = Produto(nome="Notebook Asus TUF Gaming A15", categoria="notebook",
                      marca="Asus", modelo="Gaming A15")
    assert _descricao_de(produto) == "Asus Gaming A15"


def test_sem_ancora_cai_no_nome_completo():
    # Móvel sem part-number: não há âncora → busca pelo nome (o que identifica).
    produto = Produto(nome="Conjunto Madesa Lily Mesa 4 Cadeiras Preto",
                      categoria="geral", marca="Madesa")
    assert _descricao_de(produto) == "Conjunto Madesa Lily Mesa 4 Cadeiras Preto Madesa"
