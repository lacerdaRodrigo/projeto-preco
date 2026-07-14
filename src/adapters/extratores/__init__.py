"""Extratores: leem a página de um produto que EU achei → ReferenciaProduto.

A "porta da frente" do rastreador (PLANO §1). Genéricos por schema.org/JSON-LD
(não um coletor por loja), então aceitam URL de qualquer loja que exponha dado
estruturado. Rede isolada aqui; o parse é puro e testado contra HTML gravado.
"""

from adapters.extratores.pagina import LeitorDePagina, extrair_referencia
from adapters.extratores.texto import extrair_do_slug, extrair_do_titulo

__all__ = [
    "LeitorDePagina",
    "extrair_do_slug",
    "extrair_do_titulo",
    "extrair_referencia",
]
