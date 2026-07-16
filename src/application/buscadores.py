"""A PORTA do buscador de cupons: descobrir cupons de uma loja automaticamente.

O Rodrigo não digita cupom — eles vêm DIRETO daqui e já entram no preço. Um
buscador plugável (hoje Serper + LLM) procura cupons públicos de uma loja e devolve
CADA UM com um **status de validação por sinais** (não garantia — só o checkout
confirma, e checkout a gente não toca). O orquestrador depende desta abstração; o
adaptador concreto mora em `adapters/cupons/`.

Puro: só define a forma (Protocol) e os tipos de saída. Sem httpx, sem rede.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from domain.cupom import Cupom


class StatusCupom(str, Enum):
    """Quão confiável é o cupom descoberto — validado por SINAIS, não pelo checkout."""

    PROVAVEL_VALIDO = "provavel_valido"  # visto em várias fontes / verificado recente
    NAO_CONFIRMADO = "nao_confirmado"  # 1 fonte só, sem sinal de frescor
    EXPIRADO = "expirado"  # a fonte informou validade e ela já passou


class Confianca(str, Enum):
    """A força do status (quantos sinais o sustentam)."""

    ALTA = "alta"
    MEDIA = "media"
    BAIXA = "baixa"


@dataclass(frozen=True)
class CupomDescoberto:
    """Um cupom achado na web + a avaliação de validade por sinais.

    Só o melhor `PROVAVEL_VALIDO` é aplicado no preço (marcado "não confirmado");
    `EXPIRADO` não aplica; `NAO_CONFIRMADO` fica listado, não desconta. Nunca é
    validado no checkout (regra do CLAUDE.md)."""

    cupom: Cupom
    status: StatusCupom
    confianca: Confianca
    evidencias: list[str] = field(default_factory=list)  # ["visto em 3 sites", ...]

    @property
    def aplicavel(self) -> bool:
        """Entra no cálculo automático do preço? Só o provável válido."""
        return self.status is StatusCupom.PROVAVEL_VALIDO


@runtime_checkable
class BuscadorDeCupons(Protocol):
    """Descobre cupons públicos de uma loja. Responsabilidade única: procurar e
    avaliar por sinais — nada de aplicar preço, banco ou checkout.

    Contrato: sem estado; nada encontrado devolve `[]` (não exceção); nunca
    levanta — degrada em `[]` (RN12). Nunca toca o checkout da loja.
    """

    async def buscar(self, loja: str) -> list[CupomDescoberto]:
        """Procura cupons da `loja` e devolve cada um com status/confiança."""
        ...
