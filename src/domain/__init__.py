"""Núcleo de domínio: entidades e regras puras (sem rede, banco ou UI).

Reexporta os nomes principais para o resto do sistema importar de um lugar só:
``from domain import Produto, calcular_preco_final``.
"""

from domain.dinheiro import ZERO, dinheiro
from domain.oferta import OfertaBruta
from domain.preco_final import calcular_preco_final
from domain.produto import Produto
from domain.referencia import ReferenciaProduto
from domain.sku import SKU, SnapshotPreco

__all__ = [
    "SKU",
    "ZERO",
    "OfertaBruta",
    "Produto",
    "ReferenciaProduto",
    "SnapshotPreco",
    "calcular_preco_final",
    "dinheiro",
]
