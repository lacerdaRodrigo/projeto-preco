from decimal import Decimal

from domain.cashback import Cashback, avaliar_melhor_cashback
from domain.dinheiro import ZERO, dinheiro


def test_cashback_elegivel_por_condicao():
    c1 = Cashback("Inter", Decimal("5"), condicao="cliente_inter")
    assert c1.is_elegivel(["cliente_inter", "frequentador"])
    assert not c1.is_elegivel(["cliente_nubank"])
    
    c2 = Cashback("AME", Decimal("10")) # Sem condição requerida
    assert c2.is_elegivel([])


def test_calcular_valor_cashback():
    c = Cashback("Meliuz", Decimal("10"))
    assert c.calcular_valor(dinheiro("150")) == dinheiro("15")


def test_calcular_valor_cashback_com_teto():
    c = Cashback("Meliuz", Decimal("10"), teto=dinheiro("10"))
    # 10% de 150 seria 15, mas o teto amarra em 10
    assert c.calcular_valor(dinheiro("150")) == dinheiro("10")


def test_avaliar_melhor_cashback():
    c1 = Cashback("Inter", Decimal("10"), condicao="cliente_inter")
    c2 = Cashback("Meliuz", Decimal("5"))
    c3 = Cashback("AME", Decimal("20"), teto=dinheiro("5"))
    
    # Usuário sem condições: 
    # Meliuz (5% de 100 = 5) 
    # AME (20% de 100 = 20, teto = 5)
    # Qualquer um dos dois dará 5 (o empate pega o primeiro que chegou no máximo)
    melhor, valor = avaliar_melhor_cashback([c1, c2, c3], dinheiro("100"), [])
    assert valor == dinheiro("5")
    assert melhor in (c2, c3)
    
    # Usuário cliente_inter:
    # Inter vai dar (10% de 100 = 10)
    melhor, valor = avaliar_melhor_cashback([c1, c2, c3], dinheiro("100"), ["cliente_inter"])
    assert melhor == c1
    assert valor == dinheiro("10")


def test_avaliar_melhor_cashback_vazio():
    c1 = Cashback("Inter", Decimal("10"), condicao="cliente_inter")
    
    melhor, valor = avaliar_melhor_cashback([c1], dinheiro("100"), [])
    assert melhor is None
    assert valor == ZERO
