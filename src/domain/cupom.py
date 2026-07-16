"""Regras de negócio de cupons de desconto (PRD §15)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from domain.dinheiro import ZERO, dinheiro


class TipoDesconto(str, Enum):
    FIXO = "fixo"
    PERCENTUAL = "percentual"


@dataclass(frozen=True)
class Cupom:
    """Representa um cupom de desconto oferecido por uma loja."""

    codigo: str
    desconto: Decimal
    tipo: TipoDesconto
    valor_min: Decimal = ZERO
    validade: date | None = None
    primeira_compra: bool = False
    # Categorias em que o cupom vale (ex.: ("celular", "eletronicos")). VAZIO =
    # geral (vale pra tudo). PRD §15 "categorias aceitas". Guardadas em minúsculo.
    categorias: tuple[str, ...] = ()

    def is_valido(
        self, valor_base: Decimal, data_atual: date, is_primeira_compra: bool = False
    ) -> bool:
        """Verifica se o cupom é aplicável neste momento para esta base de preço."""
        if self.validade and data_atual > self.validade:
            return False
        if valor_base < self.valor_min:
            return False
        if self.primeira_compra and not is_primeira_compra:
            return False
        return True

    def aplica_na_categoria(self, categoria: str | None) -> bool:
        """O cupom vale para um produto desta categoria? Cupom sem categorias =
        geral (vale pra tudo). Produto sem categoria → não bloqueia (na dúvida,
        deixa passar; é só desconto, e vai marcado 'não confirmado' se descoberto)."""
        if not self.categorias or not categoria:
            return True
        alvo = categoria.strip().lower()
        return any(alvo == c or alvo in c or c in alvo for c in self.categorias)

    def calcular_desconto(self, valor_base: Decimal) -> Decimal:
        """Calcula o valor nominal do desconto (nunca maior que o próprio produto)."""
        if self.tipo == TipoDesconto.FIXO:
            return dinheiro(min(self.desconto, valor_base))
        else:  # PERCENTUAL
            calculado = valor_base * (self.desconto / Decimal("100"))
            return dinheiro(min(calculado, valor_base))


def avaliar_melhor_cupom(
    cupons: list[Cupom],
    valor_base: Decimal,
    data_atual: date,
    is_primeira_compra: bool = False,
) -> tuple[Cupom | None, Decimal]:
    """Dado um conjunto de cupons, retorna o mais vantajoso e o valor descontado (RN13)."""
    melhor_cupom = None
    maior_desconto = ZERO

    for cupom in cupons:
        if cupom.is_valido(valor_base, data_atual, is_primeira_compra):
            desconto = cupom.calcular_desconto(valor_base)
            if desconto > maior_desconto:
                maior_desconto = desconto
                melhor_cupom = cupom

    return melhor_cupom, maior_desconto
