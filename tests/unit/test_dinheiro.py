"""Testes do ajudante de dinheiro: sempre Decimal, nunca float."""

from decimal import Decimal

import pytest

from domain.dinheiro import dinheiro


def test_converte_string_para_decimal_com_duas_casas():
    assert dinheiro("19.9") == Decimal("19.90")


def test_converte_inteiro_para_decimal_com_duas_casas():
    assert dinheiro(20) == Decimal("20.00")


def test_recusa_float_para_evitar_erro_de_arredondamento():
    # float é proibido de propósito: já traz o erro embutido (0.1 + 0.2 != 0.3).
    with pytest.raises(TypeError):
        dinheiro(19.90)


def test_arredonda_meio_para_cima():
    # R$ 1,005 vira R$ 1,01 (padrão do comércio).
    assert dinheiro("1.005") == Decimal("1.01")


def test_soma_de_dinheiros_nao_tem_erro_binario():
    # O motivo de existir este módulo: com float isto daria 0.30000000000000004.
    assert dinheiro("0.1") + dinheiro("0.2") == Decimal("0.30")
