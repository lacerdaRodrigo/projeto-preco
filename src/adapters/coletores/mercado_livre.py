"""Coletor do Mercado Livre via API oficial de busca (§12/§13, API-first).

Só busca e parseia — nada de matching, preço ou banco (fronteiras do §12).
O parse (`parsear_busca`) é uma função PURA, testada contra JSON gravado; a rede
fica isolada no `buscar`, que mapeia as falhas para os erros tipados da porta.
"""

from __future__ import annotations

from decimal import DecimalException
from typing import Any

import httpx

from application.coletores import ColetorQuebrado, LojaIndisponivel
from domain.dinheiro import ZERO, dinheiro
from domain.oferta import OfertaBruta

# Endpoint público de busca do site brasileiro (MLB).
_URL_BUSCA = "https://api.mercadolibre.com/sites/MLB/search"


class ColetorMercadoLivre:
    """Implementa a porta `Coletor` para o Mercado Livre."""

    nome = "Mercado Livre"
    tipo = "marketplace"
    fonte = "api"
    rate_limit_ms = 500

    def __init__(
        self, token: str | None = None, timeout_s: float = 10.0, loja_id: int = 1
    ) -> None:
        # `token` (opcional) vai no cabeçalho quando o endpoint exigir auth.
        # Sem estado entre chamadas — nada de guardar resultado (contrato §12).
        self._token = token
        self._timeout_s = timeout_s
        self.loja_id = loja_id

    async def buscar(self, descricao: str, cep: str | None = None) -> list[OfertaBruta]:
        cabecalhos = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as cliente:
                resposta = await cliente.get(
                    _URL_BUSCA,
                    params={"q": descricao, "limit": 50},
                    headers=cabecalhos,
                )
        except httpx.TimeoutException as e:
            raise LojaIndisponivel(f"timeout no Mercado Livre: {e}") from e
        except httpx.TransportError as e:  # conexão caiu, DNS, etc.
            raise LojaIndisponivel(f"falha de rede no Mercado Livre: {e}") from e

        # Acesso indisponível a nós: 5xx/429 (transitório) ou 401/403 (falta o
        # token de acesso). Nenhum é "parser quebrado" → não é ColetorQuebrado.
        if resposta.status_code in (401, 403, 429) or resposta.status_code >= 500:
            raise LojaIndisponivel(
                f"acesso indisponível (HTTP {resposta.status_code}) — "
                "a busca do ML pode exigir ML_ACCESS_TOKEN"
            )
        # Qualquer outro não-200 é inesperado → coletor pode ter quebrado.
        if resposta.status_code != 200:
            raise ColetorQuebrado(f"HTTP {resposta.status_code} no Mercado Livre")

        try:
            corpo = resposta.json()
        except ValueError as e:  # veio algo que não é JSON
            raise ColetorQuebrado(f"resposta não-JSON do Mercado Livre: {e}") from e

        return parsear_busca(corpo)


def parsear_busca(corpo: Any) -> list[OfertaBruta]:
    """Transforma o JSON de busca do ML numa lista de `OfertaBruta` (pura).

    - Estrutura inesperada (loja mudou o formato) → `ColetorQuebrado` (RN12).
    - Item individual sem preço válido → é pulado (resiliente), não derruba o resto.
    - Busca sem resultados → `[]` (vazio ≠ erro).
    """
    if not isinstance(corpo, dict) or not isinstance(corpo.get("results"), list):
        raise ColetorQuebrado("JSON do Mercado Livre sem 'results' (formato mudou?)")

    ofertas: list[OfertaBruta] = []
    for item in corpo["results"]:
        oferta = _parsear_item(item)
        if oferta is not None:
            ofertas.append(oferta)
    return ofertas


def _parsear_item(item: Any) -> OfertaBruta | None:
    """Um resultado do ML → `OfertaBruta`, ou `None` se for absurdo (pula)."""
    if not isinstance(item, dict):
        return None

    titulo = item.get("title")
    url = item.get("permalink")
    if not titulo or not url:
        return None

    # Dinheiro via str, nunca float (senão herda o erro de arredondamento).
    try:
        preco = dinheiro(str(item["price"]))
    except (KeyError, TypeError, ValueError, DecimalException):
        return None
    if preco <= ZERO:  # preço nulo/absurdo não entra (RN12)
        return None

    frete_gratis = bool(item.get("shipping", {}).get("free_shipping"))
    parcelamento = item.get("installments") or {}
    vendedor = item.get("seller") or {}

    return OfertaBruta(
        titulo=str(titulo),
        preco=preco,
        url=str(url),
        ean=_extrair_ean(item.get("attributes")),
        # Frete grátis: sabemos que é zero (cotado). Senão, ML só cota no carrinho
        # → não inventa frete (frete_cotado=False, RN09).
        frete=ZERO if frete_gratis else None,
        frete_cotado=frete_gratis,
        parcelas=parcelamento.get("quantity"),
        sem_juros=parcelamento.get("rate") == 0,
        em_estoque=int(item.get("available_quantity") or 0) > 0,
        vendedor=vendedor.get("nickname"),
        vendedor_oficial=vendedor.get("official_store_id") is not None,
    )


def _extrair_ean(atributos: Any) -> str | None:
    """Procura o GTIN/EAN entre os atributos do anúncio (quando existe)."""
    if not isinstance(atributos, list):
        return None
    for atributo in atributos:
        if isinstance(atributo, dict) and atributo.get("id") in ("GTIN", "EAN"):
            valor = atributo.get("value_name")
            if valor:
                return str(valor)
    return None
