"""SKU e SnapshotPreco — a oferta JÁ casada ao meu produto e seu histórico.

- ``SKU``: uma oferta que o matching aceitou (score ≥ 0.85) como sendo o meu
  produto numa loja específica. 1 por (produto, loja) — RN01.
- ``SnapshotPreco``: uma foto do preço daquele SKU num instante. A série desses
  snapshots é o histórico (PRD §17). Cada um é rastreável (url via SKU + quando).

Puro: sem rede/banco. Os ``id``/``*_id`` existem para o repositório ligar as
peças depois, mas o núcleo não sabe QUAL banco é. Ver PRD §10.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class SKU:
    """Oferta de uma loja já confirmada como sendo o meu produto (RN01)."""

    produto_id: int
    loja_id: int
    url: str
    titulo_original: str  # o título como veio da loja (rastreabilidade)
    score_match: float  # o quão confiante o matching ficou (≥ 0.85 aceita)
    # A loja de origem que dá identidade ao SKU. Para coletores de 1 loja, é o
    # nome dela; para agregadores (Google Shopping), é o `source` de cada oferta
    # — assim uma busca com N lojas vira N SKUs, sem colapsar num só (RN01).
    loja_origem: str = ""
    vendedor_oficial: bool = False
    status: str = "ativo"
    id: int | None = None  # None enquanto não foi salvo


@dataclass(frozen=True)
class SnapshotPreco:
    """Uma foto do preço de um SKU num instante (série temporal — PRD §17)."""

    sku_id: int
    preco: Decimal
    coletado_em: datetime

    # Mesmos campos de preço/entrega da oferta, congelados neste instante.
    preco_avista: Decimal | None = None
    desconto_pix: Decimal | None = None
    frete: Decimal | None = None
    frete_cotado: bool = False
    prazo_dias: int | None = None
    parcelas: int | None = None
    sem_juros: bool = False
    em_estoque: bool = True

    id: int | None = None  # None enquanto não foi salvo
