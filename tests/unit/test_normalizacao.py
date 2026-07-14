"""Testes da normalização de títulos (§14, etapa 3)."""

from domain.matching import config_padrao, normalizar
from domain.matching.normalizacao import extrair_capacidades, tokenizar

CFG = config_padrao()


def test_minusculas_e_sem_acento():
    assert normalizar("Notebook Ação Preço", CFG) == "notebook acao preco"


def test_cola_unidade_ao_numero():
    assert normalizar("512 GB", CFG) == "512gb"


def test_traduz_cor_do_ingles():
    assert normalizar("Galaxy Black", CFG) == "galaxy preto"


def test_remove_ruido():
    # "frete grátis" e "sem juros" somem; sobra a identidade do produto.
    texto = normalizar("Echo Dot 5 frete grátis sem juros", CFG)
    assert "frete" not in texto
    assert "juros" not in texto
    assert "echo dot 5" in texto


def test_polegadas_viram_pol():
    assert normalizar('Smart TV 55"', CFG) == "smart tv 55pol"


def test_dois_titulos_diferentes_convergem():
    # O objetivo da normalização: títulos "diferentes" ficam comparáveis.
    a = normalizar("Samsung Galaxy S25 Ultra 512GB Preto", CFG)
    b = normalizar("Galaxy S25 Ultra Black 512 GB", CFG)
    assert tokenizar(a) & tokenizar(b) >= {"galaxy", "s25", "ultra", "512gb", "preto"}


def test_extrai_capacidades():
    assert extrair_capacidades("notebook 16gb ssd 1tb") == {"16gb", "1tb"}
