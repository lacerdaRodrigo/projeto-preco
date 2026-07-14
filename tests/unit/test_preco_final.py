"""Testes da fórmula do preço final (§16) — o mais crítico do domínio.

Cada teste prova UMA regra da fórmula, com números fáceis de conferir de cabeça.
"""

from decimal import Decimal

from domain import calcular_preco_final, dinheiro


def test_sem_a_vista_sem_frete_usa_o_preco_normal():
    final = calcular_preco_final(preco=dinheiro("100"))
    assert final == Decimal("100.00")


def test_preco_a_vista_vence_o_de_vitrine():
    # Havendo à vista (PIX/boleto), a base é ele, não a vitrine (RN02/RN10).
    final = calcular_preco_final(preco=dinheiro("100"), preco_avista=dinheiro("90"))
    assert final == Decimal("90.00")


def test_frete_so_entra_quando_cotado():
    # Com CEP → frete cotado → soma (RN09).
    final = calcular_preco_final(
        preco=dinheiro("100"), frete=dinheiro("15"), frete_cotado=True
    )
    assert final == Decimal("115.00")


def test_frete_informado_mas_nao_cotado_e_ignorado():
    # Sem CEP: mesmo tendo um valor de frete, não soma — compara sem frete.
    final = calcular_preco_final(
        preco=dinheiro("100"), frete=dinheiro("15"), frete_cotado=False
    )
    assert final == Decimal("100.00")


def test_cupom_desconta_da_base():
    final = calcular_preco_final(preco=dinheiro("100"), desconto_cupom=dinheiro("10"))
    assert final == Decimal("90.00")


def test_cashback_abate_do_custo_liquido():
    final = calcular_preco_final(preco=dinheiro("100"), cashback=dinheiro("5"))
    assert final == Decimal("95.00")


def test_ordem_completa_do_paragrafo_16():
    # base à vista 90 − cupom 10 + frete 15 − cashback 5 = 90.
    final = calcular_preco_final(
        preco=dinheiro("100"),
        preco_avista=dinheiro("90"),
        desconto_cupom=dinheiro("10"),
        frete=dinheiro("15"),
        frete_cotado=True,
        cashback=dinheiro("5"),
    )
    assert final == Decimal("90.00")


def test_cupom_maior_que_o_produto_nao_vira_preco_negativo():
    # Guarda defensiva: dado de loja é não-confiável (CLAUDE.md).
    final = calcular_preco_final(preco=dinheiro("100"), desconto_cupom=dinheiro("150"))
    assert final == Decimal("0.00")


def test_resultado_e_decimal_com_centavos():
    final = calcular_preco_final(preco=dinheiro("10"), cashback=dinheiro("0.1"))
    assert final == Decimal("9.90")
    assert isinstance(final, Decimal)
