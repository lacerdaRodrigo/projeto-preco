"""Coletor de DEMONSTRAÇÃO (sandbox) — API pública aberta, sem token.

Serve para ver o sistema rodando de ponta a ponta com dados que vêm pela rede,
sem a parede de autenticação das lojas reais. **Não é uma loja BR de verdade** —
é um sandbox (dummyjson.com). Honra o mesmo contrato `Coletor`, então o dia que
você tiver o token de uma loja real, é só trocar o coletor, nada mais muda.
"""

from __future__ import annotations

from decimal import DecimalException
from typing import Any

import httpx

from application.coletores import ColetorQuebrado, LojaIndisponivel
from domain.dinheiro import ZERO, dinheiro
from domain.oferta import OfertaBruta

_URL_BUSCA = "https://dummyjson.com/products/search"


class ColetorSandbox:
    """Implementa a porta `Coletor` contra uma API pública de demonstração."""

    loja_id = 99
    nome = "Loja Demo (sandbox)"
    tipo = "marketplace"
    fonte = "api"
    rate_limit_ms = 200

    def __init__(self, timeout_s: float = 10.0) -> None:
        self._timeout_s = timeout_s

    async def buscar(self, descricao: str, cep: str | None = None) -> list[OfertaBruta]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as cliente:
                resposta = await cliente.get(
                    _URL_BUSCA, params={"q": descricao, "limit": 20}
                )
        except httpx.TimeoutException as e:
            raise LojaIndisponivel(f"timeout na loja demo: {e}") from e
        except httpx.TransportError as e:
            raise LojaIndisponivel(f"falha de rede na loja demo: {e}") from e

        if resposta.status_code in (401, 403, 429) or resposta.status_code >= 500:
            raise LojaIndisponivel(f"acesso indisponível (HTTP {resposta.status_code})")
        if resposta.status_code != 200:
            raise ColetorQuebrado(f"HTTP {resposta.status_code} na loja demo")

        try:
            corpo = resposta.json()
        except ValueError as e:
            raise ColetorQuebrado(f"resposta não-JSON da loja demo: {e}") from e

        return parsear_busca(corpo)


def parsear_busca(corpo: Any) -> list[OfertaBruta]:
    """JSON de busca do sandbox → lista de `OfertaBruta` (pura, testável)."""
    if not isinstance(corpo, dict) or not isinstance(corpo.get("products"), list):
        raise ColetorQuebrado("JSON da loja demo sem 'products' (formato mudou?)")

    ofertas: list[OfertaBruta] = []
    for item in corpo["products"]:
        oferta = _parsear_item(item)
        if oferta is not None:
            ofertas.append(oferta)
    return ofertas


def _parsear_item(item: Any) -> OfertaBruta | None:
    if not isinstance(item, dict):
        return None
    titulo = item.get("title")
    ident = item.get("id")
    if not titulo or ident is None:
        return None
    try:
        preco = dinheiro(str(item["price"]))
    except (KeyError, TypeError, ValueError, DecimalException):
        return None
    if preco <= ZERO:
        return None
    return OfertaBruta(
        titulo=str(titulo),
        preco=preco,
        url=f"https://dummyjson.com/products/{ident}",
        em_estoque=int(item.get("stock") or 0) > 0,
    )
