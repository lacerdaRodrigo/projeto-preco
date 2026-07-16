"""Regras de negócio de cashback (PRD §16 e RN14)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from domain.dinheiro import ZERO, dinheiro


@dataclass(frozen=True)
class Cashback:
    """Representa um cashback oferecido para compras em uma loja (AME, Méliuz, bancos)."""

    fonte: str
    percentual: Decimal
    teto: Decimal | None = None
    condicao: str | None = None

    def is_elegivel(self, condicoes_usuario: list[str]) -> bool:
        """Cashback só conta se você atende à condição (ex.: cliente_inter) — RN14."""
        if not self.condicao:
            return True
        return self.condicao in condicoes_usuario

    def calcular_valor(self, valor_pago: Decimal) -> Decimal:
        """Calcula quanto de dinheiro voltará, respeitando o teto da promoção."""
        valor_calculado = valor_pago * (self.percentual / Decimal("100"))
        
        if self.teto is not None and valor_calculado > self.teto:
            return dinheiro(self.teto)
            
        return dinheiro(valor_calculado)


def avaliar_melhor_cashback(
    cashbacks: list[Cashback],
    valor_pago: Decimal,
    condicoes_usuario: list[str],
) -> tuple[Cashback | None, Decimal]:
    """Retorna o cashback que gera o maior retorno financeiro para o usuário (RN14)."""
    melhor_cashback = None
    maior_valor = ZERO

    for cashback in cashbacks:
        if cashback.is_elegivel(condicoes_usuario):
            valor = cashback.calcular_valor(valor_pago)
            if valor > maior_valor:
                maior_valor = valor
                melhor_cashback = cashback

    return melhor_cashback, maior_valor
