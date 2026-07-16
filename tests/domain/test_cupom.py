from datetime import date
from decimal import Decimal

from domain.cupom import Cupom, TipoDesconto, avaliar_melhor_cupom
from domain.dinheiro import ZERO, dinheiro


def test_cupom_invalido_por_data():
    hoje = date(2025, 1, 10)
    cupom = Cupom(
        codigo="VENCIDO", 
        desconto=Decimal("10"), 
        tipo=TipoDesconto.FIXO, 
        validade=date(2025, 1, 9)
    )
    assert not cupom.is_valido(dinheiro("100"), hoje)


def test_cupom_invalido_por_valor_minimo():
    hoje = date(2025, 1, 10)
    cupom = Cupom(
        codigo="MINIMO100", 
        desconto=Decimal("10"), 
        tipo=TipoDesconto.FIXO, 
        valor_min=dinheiro("100")
    )
    assert not cupom.is_valido(dinheiro("99.99"), hoje)


def test_cupom_invalido_por_primeira_compra():
    hoje = date(2025, 1, 10)
    cupom = Cupom(
        codigo="BEMVINDO", 
        desconto=Decimal("10"), 
        tipo=TipoDesconto.FIXO, 
        primeira_compra=True
    )
    assert not cupom.is_valido(dinheiro("100"), hoje, is_primeira_compra=False)


def test_cupom_valido_sempre():
    hoje = date(2025, 1, 10)
    cupom = Cupom(
        codigo="SEMPRE", 
        desconto=Decimal("10"), 
        tipo=TipoDesconto.FIXO
    )
    assert cupom.is_valido(dinheiro("100"), hoje)


def test_calcular_desconto_fixo():
    cupom = Cupom("10OFF", dinheiro("10"), TipoDesconto.FIXO)
    assert cupom.calcular_desconto(dinheiro("50")) == dinheiro("10")
    # Não pode dar desconto maior que o valor da compra
    assert cupom.calcular_desconto(dinheiro("5")) == dinheiro("5")


def test_calcular_desconto_percentual():
    cupom = Cupom("10PORCENTO", Decimal("10"), TipoDesconto.PERCENTUAL)
    assert cupom.calcular_desconto(dinheiro("50")) == dinheiro("5")


def test_avaliar_melhor_cupom_retorna_o_mais_vantajoso():
    hoje = date(2025, 1, 10)
    c1 = Cupom("10OFF", dinheiro("10"), TipoDesconto.FIXO)
    c2 = Cupom("20PORCENTO", Decimal("20"), TipoDesconto.PERCENTUAL) # Dá R$ 20.00 num produto de 100
    c3 = Cupom("50OFF", dinheiro("50"), TipoDesconto.FIXO, valor_min=dinheiro("200")) # Inválido pelo valor_min
    
    melhor, desconto = avaliar_melhor_cupom([c1, c2, c3], dinheiro("100"), hoje)
    
    assert melhor == c2
    assert desconto == dinheiro("20")


def test_avaliar_melhor_cupom_vazio_ou_invalido():
    hoje = date(2025, 1, 10)
    c1 = Cupom("VENCIDO", dinheiro("10"), TipoDesconto.FIXO, validade=date(2025, 1, 1))
    
    melhor, desconto = avaliar_melhor_cupom([c1], dinheiro("100"), hoje)
    assert melhor is None
    assert desconto == ZERO
