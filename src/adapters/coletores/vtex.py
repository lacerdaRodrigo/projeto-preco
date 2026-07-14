"""Coletor GENÉRICO para lojas VTEX (§12) — uma classe, milhares de lojas BR.

A VTEX é a plataforma de e-commerce mais usada no varejo brasileiro (Americanas,
Casas Bahia, Fast Shop, Vivara, Submarino...). Todas expõem o **mesmo** catálogo
público, sem chave nem login: `/api/catalog_system/pub/products/search`. Então
basta parametrizar o domínio — o resto do formato é idêntico.

Só busca e parseia (fronteiras do §12). Parse puro, testado contra JSON gravado.
"""

from __future__ import annotations

from decimal import DecimalException
from typing import Any

import httpx

from application.coletores import ColetorQuebrado, LojaIndisponivel
from domain.dinheiro import ZERO, dinheiro
from domain.oferta import OfertaBruta

_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125"


class ColetorVTEX:
    """Coletor de UMA loja VTEX, identificada pelo domínio."""

    fonte = "api"
    rate_limit_ms = 800

    def __init__(
        self,
        dominio: str,
        loja_id: int,
        nome: str,
        tipo: str = "varejo",
        timeout_s: float = 12.0,
    ) -> None:
        self.dominio = dominio
        self.loja_id = loja_id
        self.nome = nome
        self.tipo = tipo
        self._timeout_s = timeout_s

    async def buscar(self, descricao: str, cep: str | None = None) -> list[OfertaBruta]:
        url = f"https://{self.dominio}/api/catalog_system/pub/products/search"
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as cliente:
                resposta = await cliente.get(
                    url,
                    params={"ft": descricao, "_from": 0, "_to": 19},
                    headers={"User-Agent": _USER_AGENT},
                )
        except httpx.TimeoutException as e:
            raise LojaIndisponivel(f"timeout em {self.nome}: {e}") from e
        except httpx.TransportError as e:
            raise LojaIndisponivel(f"falha de rede em {self.nome}: {e}") from e

        # 401/403 costuma ser anti-bot (bloqueio de IP), 5xx/429 transitório.
        if resposta.status_code in (401, 403, 429) or resposta.status_code >= 500:
            raise LojaIndisponivel(f"acesso indisponível (HTTP {resposta.status_code})")
        # VTEX devolve 206 (Partial Content) em busca com faixa — também é OK.
        if resposta.status_code not in (200, 206):
            raise ColetorQuebrado(f"HTTP {resposta.status_code} em {self.nome}")

        try:
            corpo = resposta.json()
        except ValueError as e:
            raise ColetorQuebrado(f"resposta não-JSON de {self.nome}: {e}") from e

        return parsear_busca(corpo, self.dominio)


def parsear_busca(corpo: Any, dominio: str) -> list[OfertaBruta]:
    """JSON de busca VTEX (uma lista de produtos) → lista de `OfertaBruta` (pura)."""
    if not isinstance(corpo, list):
        raise ColetorQuebrado("resposta VTEX não é uma lista de produtos (formato mudou?)")

    ofertas: list[OfertaBruta] = []
    for item in corpo:
        oferta = _parsear_item(item, dominio)
        if oferta is not None:
            ofertas.append(oferta)
    return ofertas


def _parsear_item(produto: Any, dominio: str) -> OfertaBruta | None:
    if not isinstance(produto, dict):
        return None
    titulo = produto.get("productName")
    if not titulo:
        return None

    escolha = _melhor_oferta(produto.get("items"))
    if escolha is None:
        return None
    vendedor, oferta_comercial, ean = escolha

    try:
        preco = dinheiro(str(oferta_comercial.get("Price")))
    except (TypeError, ValueError, DecimalException):
        return None
    if preco <= ZERO:
        return None

    return OfertaBruta(
        titulo=str(titulo),
        preco=preco,
        url=produto.get("link") or f"https://{dominio}/{produto.get('linkText', '')}/p",
        ean=ean,
        em_estoque=bool(oferta_comercial.get("IsAvailable")),
        vendedor=vendedor.get("sellerName"),
        # Na VTEX o vendedor "1" é a própria loja (1P); os demais são marketplace.
        vendedor_oficial=str(vendedor.get("sellerId")) == "1",
    )


def _melhor_oferta(itens: Any) -> tuple[dict, dict, str | None] | None:
    """Escolhe o melhor (seller, oferta_comercial, ean) entre os SKUs do produto.

    Prefere um seller com produto disponível; se nenhum, aceita o primeiro com
    preço (para registrar o item mesmo fora de estoque). Devolve None se não há
    nenhuma oferta com preço.
    """
    if not isinstance(itens, list):
        return None
    reserva: tuple[dict, dict, str | None] | None = None
    for sku in itens:
        if not isinstance(sku, dict):
            continue
        ean = sku.get("ean") or None
        for vendedor in sku.get("sellers") or []:
            if not isinstance(vendedor, dict):
                continue
            oferta = vendedor.get("commertialOffer")
            if not isinstance(oferta, dict) or oferta.get("Price") in (None, 0):
                continue
            candidato = (vendedor, oferta, ean)
            if oferta.get("IsAvailable"):
                return candidato  # disponível vence na hora
            reserva = reserva or candidato
    return reserva


def lojas_vtex_padrao() -> list[ColetorVTEX]:
    """Lojas VTEX de eletrônico/varejo confirmadas respondendo com JSON público.

    Escolhidas por TESTE: os gigantes (Americanas, Casas Bahia, Fast Shop) bloqueiam
    o catálogo com anti-bot mesmo de IP residencial, então ficam de fora do padrão.
    Estas respondem e trazem preço real. ids de loja: KaBuM! usa 2; VTEX a partir de 3.
    Adicionar loja = uma linha aqui, sem tocar em mais nada.
    """
    return [
        ColetorVTEX("www.webcontinental.com.br", loja_id=3, nome="Webcontinental"),
        ColetorVTEX("www.novomundo.com.br", loja_id=4, nome="Novo Mundo"),
        ColetorVTEX("www.fujioka.com.br", loja_id=5, nome="Fujioka"),
        ColetorVTEX("www.lojasmm.com", loja_id=6, nome="Lojas MM"),
    ]
