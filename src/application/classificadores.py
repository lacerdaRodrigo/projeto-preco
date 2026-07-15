"""A PORTA do classificador de identidade: a IA que decide "é o mesmo produto?".

A regra de matching fina (mesma marca, linha, modelo E geração — 'Buds' ≠ 'Buds
2', 'Wave 200' ≠ 'Wave Buds') não vive mais no backend por categoria: um
classificador plugável (hoje um LLM) olha o produto-alvo contra cada oferta e diz
mesmo/diferente, seja qual for a categoria. O orquestrador depende desta
abstração; o adaptador concreto mora em `adapters/classificadores/`.

Puro: só define a forma (Protocol) e o veredito. Sem httpx, sem rede.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from domain.oferta import OfertaBruta
from domain.produto import Produto


@dataclass(frozen=True)
class VereditoIdentidade:
    """A opinião da IA sobre UMA oferta: é o mesmo produto que o alvo?"""

    mesmo: bool
    motivo: str  # legível, pro funil ("geração diferente: 'Buds 2'")


@runtime_checkable
class ClassificadorIdentidade(Protocol):
    """Decide, em lote, quais ofertas são o mesmo produto que o alvo.

    Contrato: devolve UMA lista alinhada a `ofertas` (mesmo tamanho, mesma ordem).
    Cada posição é um `VereditoIdentidade` ou `None` — `None` = "sem opinião"
    (falha de rede, JSON inválido, oferta que o modelo não classificou), e aí o
    chamador mantém a decisão determinística. Nunca levanta exceção: degrada em
    `None` (RN12). Roda 1× por busca (lote), não 1× por oferta.
    """

    def classificar(
        self, produto: Produto, ofertas: Sequence[OfertaBruta]
    ) -> list[VereditoIdentidade | None]:
        ...
