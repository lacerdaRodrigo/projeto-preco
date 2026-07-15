"""Entidade OfertaBruta — o que um coletor traz de uma loja, ainda CRU.

"Bruta" porque é dado externo, **não-confiável** (CLAUDE.md): ainda não foi
casada a nenhum produto meu nem validada como preço plausível (RN12). O coletor
devolve uma lista disto; o matching decide se vira um SKU. Ver PRD §12.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class OfertaBruta:
    """Uma oferta como veio da loja, antes de qualquer casamento/validação."""

    # O que toda oferta tem: título, preço de vitrine e o endereço (rastreável).
    titulo: str
    preco: Decimal
    url: str

    # O preço foi CONFIRMADO na página da loja (True) ou é o de vitrine do
    # agregador/Google Shopping, não verificado ao vivo (False)? Coletores que
    # leem a loja direto (KaBuM) trazem True; o agregador marca False quando não
    # conseguiu confirmar na página — a UI avisa "preço de vitrine".
    preco_confirmado: bool = True

    # EAN/GTIN, quando a loja informa: é o portão FORTE do matching (§14) —
    # se bater com o do produto, é match certo. Nem toda oferta traz.
    ean: str | None = None

    # Preço à vista (PIX/boleto), quando a loja informa — pode ser menor que a
    # vitrine. É a base do preço final (PRD §16).
    preco_avista: Decimal | None = None
    desconto_pix: Decimal | None = None

    # Frete: só entra na comparação se foi cotado para um CEP (RN09).
    frete: Decimal | None = None
    frete_cotado: bool = False

    # Informações secundárias (exibidas, mas não mandam no ranking).
    prazo_dias: int | None = None
    parcelas: int | None = None
    sem_juros: bool = False

    # Disponibilidade e quem vende.
    em_estoque: bool = True
    vendedor: str | None = None
    vendedor_oficial: bool = False
