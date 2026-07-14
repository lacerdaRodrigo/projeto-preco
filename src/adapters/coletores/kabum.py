"""Coletor do KaBuM! via API pública de catálogo (§12, loja BR real, tech/games).

Diferente do Mercado Livre (que fechou a busca pública), o KaBuM! expõe o mesmo
catálogo que o site dele consome — sem login. Traz preço, **preço à vista**
(PIX/boleto), estoque, frete grátis e se é vendedor próprio ou marketplace.

Só busca e parseia (fronteiras do §12). O parse é puro e testado contra JSON
gravado; a rede fica isolada no `buscar`, com erros tipados da porta.
"""

from __future__ import annotations

from decimal import DecimalException
from typing import Any

import httpx

from application.coletores import ColetorQuebrado, LojaIndisponivel
from domain.dinheiro import ZERO, dinheiro
from domain.oferta import OfertaBruta

_URL_BUSCA = "https://servicespub.prod.api.aws.grupokabum.com.br/catalog/v2/products"
# UA de navegador: a API bloqueia o agente padrão de bibliotecas. Coleta educada,
# sem enganar — só evita o bloqueio automático.
_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125"


class ColetorKabum:
    """Implementa a porta `Coletor` para o KaBuM!."""

    loja_id = 2
    nome = "KaBuM!"
    tipo = "tech"
    fonte = "api"
    rate_limit_ms = 800

    def __init__(self, timeout_s: float = 12.0) -> None:
        self._timeout_s = timeout_s

    async def buscar(self, descricao: str, cep: str | None = None) -> list[OfertaBruta]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as cliente:
                resposta = await cliente.get(
                    _URL_BUSCA,
                    params={"query": descricao, "page_number": 1, "page_size": 20},
                    headers={"User-Agent": _USER_AGENT},
                )
        except httpx.TimeoutException as e:
            raise LojaIndisponivel(f"timeout no KaBuM!: {e}") from e
        except httpx.TransportError as e:
            raise LojaIndisponivel(f"falha de rede no KaBuM!: {e}") from e

        if resposta.status_code in (401, 403, 429) or resposta.status_code >= 500:
            raise LojaIndisponivel(f"acesso indisponível (HTTP {resposta.status_code})")
        if resposta.status_code != 200:
            raise ColetorQuebrado(f"HTTP {resposta.status_code} no KaBuM!")

        try:
            corpo = resposta.json()
        except ValueError as e:
            raise ColetorQuebrado(f"resposta não-JSON do KaBuM!: {e}") from e

        return parsear_busca(corpo)


def parsear_busca(corpo: Any) -> list[OfertaBruta]:
    """JSON de busca do KaBuM! (formato JSON:API) → lista de `OfertaBruta` (pura)."""
    if not isinstance(corpo, dict) or not isinstance(corpo.get("data"), list):
        raise ColetorQuebrado("JSON do KaBuM! sem 'data' (formato mudou?)")

    ofertas: list[OfertaBruta] = []
    for item in corpo["data"]:
        oferta = _parsear_item(item)
        if oferta is not None:
            ofertas.append(oferta)
    return ofertas


def _parsear_item(item: Any) -> OfertaBruta | None:
    if not isinstance(item, dict):
        return None
    ident = item.get("id")
    atributos = item.get("attributes")
    if ident is None or not isinstance(atributos, dict):
        return None

    titulo = atributos.get("title")
    if not titulo:
        return None

    try:
        preco = dinheiro(str(atributos["price"]))
    except (KeyError, TypeError, ValueError, DecimalException):
        return None
    if preco <= ZERO:
        return None

    # Preço à vista (PIX/boleto): só considera se for realmente menor (§16).
    preco_avista, desconto_pix = _avista(atributos, preco)

    frete_gratis = bool(atributos.get("has_free_shipping"))
    marketplace = bool(atributos.get("is_marketplace"))

    return OfertaBruta(
        titulo=str(titulo),
        preco=preco,
        url=_montar_url(ident, atributos.get("product_link")),
        preco_avista=preco_avista,
        desconto_pix=desconto_pix,
        # Frete grátis é cotado como zero; senão, não inventa (RN09).
        frete=ZERO if frete_gratis else None,
        frete_cotado=frete_gratis,
        em_estoque=bool(atributos.get("available")) and int(atributos.get("stock") or 0) > 0,
        vendedor=_vendedor(atributos, marketplace),
        vendedor_oficial=not marketplace,  # 1P do KaBuM! = loja oficial
    )


def _avista(atributos: dict, preco: Any) -> tuple[Any | None, Any | None]:
    try:
        avista = dinheiro(str(atributos["price_with_discount"]))
    except (KeyError, TypeError, ValueError, DecimalException):
        return None, None
    if ZERO < avista < preco:
        return avista, preco - avista
    return None, None


def _montar_url(ident: Any, slug: Any) -> str:
    url = f"https://www.kabum.com.br/produto/{ident}"
    if slug:
        url += f"/{slug}"
    return url


def _vendedor(atributos: dict, marketplace: bool) -> str | None:
    if not marketplace:
        return "KaBuM!"
    dados = atributos.get("marketplace") or {}
    return dados.get("seller_name")
