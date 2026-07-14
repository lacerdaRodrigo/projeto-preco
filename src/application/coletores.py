"""A PORTA do coletor: o contrato que toda loja honra (§12).

Vive no núcleo (não no adaptador) de propósito: o orquestrador depende desta
abstração, e cada loja a implementa lá em `adapters/coletores/`. Assim dá pra ter
N lojas sem o núcleo saber que elas existem — a dependência aponta pra dentro.

Puro: só define a forma (Protocol) e os erros tipados. Sem httpx, sem rede.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from domain.oferta import OfertaBruta


class ErroColetor(Exception):
    """Base de todos os erros de coleta. Isola a falha de UMA loja (RN08)."""


class LojaIndisponivel(ErroColetor):
    """Falha transitória (timeout, 5xx, rate-limit) → vale retry com backoff."""


class ProdutoNaoEncontrado(ErroColetor):
    """Reservado: busca sem resultado. Pelo contrato, vazio devolve `[]`, não
    exceção — existe para coletores que precisem distinguir 'produto some' de
    'busca vazia'. O coletor do ML devolve `[]`."""


class ColetorQuebrado(ErroColetor):
    """O parse falhou ou veio absurdo (a loja mudou o formato). Vira
    `coletor_degradado`, não grava (RN12); é o que o canary vigia."""


@runtime_checkable
class Coletor(Protocol):
    """A forma que todo coletor de loja tem. Responsabilidade única: buscar em
    UMA loja e devolver ofertas brutas — nada de matching, preço ou banco (§12).
    """

    loja_id: int  # id da loja no catálogo (o SKU herda daqui)
    nome: str  # ex.: "Mercado Livre"
    tipo: str  # marketplace | varejo | tech | casa
    fonte: str  # api | scrape  (API-first; scrape é último recurso)
    rate_limit_ms: int  # pausa mínima entre chamadas (coleta educada)

    async def buscar(self, descricao: str, cep: str | None = None) -> list[OfertaBruta]:
        """Busca `descricao` na loja e devolve ofertas cruas.

        Contrato: sem estado; vazio devolve `[]` (não exceção); erros são os
        tipados acima; sem CEP não inventa frete (`frete_cotado=False`, RN09).
        """
        ...
