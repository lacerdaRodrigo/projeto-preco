"""Dinheiro no domínio: sempre ``Decimal``, nunca ``float``.

Por quê: ``float`` guarda os números de um jeito aproximado (binário), então
``0.1 + 0.2`` já dá ``0.30000000000000004``. Em preço isso é inaceitável — um
centavo errado quebra o ranking. ``Decimal`` faz a conta como a gente faz no
papel (base 10), sem surpresa. Ver PRD §10 ("dinheiro em numeric, nunca float").
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# Dinheiro no Brasil tem 2 casas (centavos). Arredondamento "meio pra cima"
# é o comum no comércio (R$ 1,005 vira R$ 1,01).
CENTAVOS = Decimal("0.01")

# Zero reutilizável, já como Decimal (evita criar Decimal("0") o tempo todo).
ZERO = Decimal("0")


def dinheiro(valor: str | int | Decimal) -> Decimal:
    """Converte um valor em dinheiro (``Decimal`` com 2 casas).

    Aceita ``str`` ("19.90"), ``int`` (20) ou ``Decimal``. **Recusa ``float``**
    de propósito: quem passa ``float`` já traz o erro de arredondamento embutido,
    então bloqueamos na entrada em vez de deixar o problema se espalhar.

    >>> dinheiro("19.9")
    Decimal('19.90')
    >>> dinheiro(20)
    Decimal('20.00')
    """
    if isinstance(valor, float):
        raise TypeError(
            "dinheiro não aceita float (erro de arredondamento). "
            'Passe str ("19.90"), int ou Decimal.'
        )
    return Decimal(valor).quantize(CENTAVOS, rounding=ROUND_HALF_UP)
