"""Coletor Google Shopping via Serper (§12) — comparação real em N lojas de uma vez.

Diferente das lojas (ML/VTEX) que barram a gente por anti-bot, o Serper é um
**agregador**: ele lê o Google Shopping por baixo (proxies, fingerprint de
navegador — problema dele) e nos entrega o resultado pronto. Por isso UMA busca
traz ofertas de **várias lojas** (campo `source`) — o pulo do gato do projeto.

Consequência de design: aqui "1 coletor = N lojas". A loja de origem vai no
`vendedor` de cada `OfertaBruta`; é o maestro que separa o SKU por loja (não
colapsa tudo num só). Ver PLANO passo 5.

Link do produto: o `link` que o shopping devolve é um redirecionamento do Google
que **expira** (cai na home vazia, não no produto). Então resolvemos o link
DIRETO da loja com uma busca orgânica por loja (`descricao + source`), pegando o
1º resultado. Se falhar, cai num link de busca do Google (grátis, sempre abre).

Só busca e parseia (fronteiras do §12). O parse é puro e testado contra JSON
gravado; a rede fica isolada no `buscar`, com erros tipados da porta.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import replace
from html import unescape
from decimal import Decimal, DecimalException
from typing import Any
from urllib.parse import parse_qsl, quote_plus, urlencode, urlparse, urlunparse

import httpx

from application.coletores import ColetorQuebrado, LojaIndisponivel
from domain.dinheiro import ZERO, dinheiro
from domain.oferta import OfertaBruta

_URL_BUSCA = "https://google.serper.dev/shopping"
_URL_ORGANICA = "https://google.serper.dev/search"  # resolve o link direto da loja
# 40 resultados = leque largo de lojas numa busca (custa 2 créditos dos 2.500).
_NUM_RESULTADOS = 40
# UA de navegador pra ler a página do produto (algumas lojas bloqueiam o agente
# padrão de bibliotecas). Coleta educada, sem enganar — só evita bloqueio bobo.
_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125"


class ColetorGoogleShopping:
    """Implementa a porta `Coletor` para o Google Shopping (via Serper)."""

    loja_id = 10  # id do agregador; a loja de verdade vem no `vendedor` (source)
    nome = "Google Shopping"
    tipo = "agregador"
    fonte = "api"
    rate_limit_ms = 1000
    # Sinaliza ao maestro que UMA busca traz N lojas: a identidade do SKU vem do
    # `vendedor` de cada oferta (source), não do coletor. Ver PLANO passo 5.
    agrega_lojas = True

    def __init__(
        self,
        api_key: str,
        timeout_s: float = 20.0,
        resolver_links_diretos: bool = True,
    ) -> None:
        if not api_key:
            raise ValueError("ColetorGoogleShopping exige SERPER_API_KEY")
        self._api_key = api_key
        self._timeout_s = timeout_s
        # Resolver o link direto gasta ~1 crédito por loja. Ligado por padrão
        # (o link do shopping é morto); desligável em teste/uso econômico.
        self._resolver_links = resolver_links_diretos

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-API-KEY": self._api_key, "Content-Type": "application/json"}

    async def buscar(self, descricao: str, cep: str | None = None) -> list[OfertaBruta]:
        # cep ignorado: o Google Shopping não cota frete por CEP (frete_cotado=False).
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as cliente:
                resposta = await cliente.post(
                    _URL_BUSCA,
                    headers=self._headers,
                    json={
                        "q": descricao,
                        "gl": "br",
                        "hl": "pt-br",
                        "location": "Brazil",
                        "num": _NUM_RESULTADOS,
                    },
                )
                # 429 (rate-limit) e 5xx são transitórios → retry vale a pena.
                if resposta.status_code == 429 or resposta.status_code >= 500:
                    raise LojaIndisponivel(
                        f"Serper indisponível (HTTP {resposta.status_code})"
                    )
                # 401/403 = chave errada/sem crédito: não insiste; degradado.
                if resposta.status_code != 200:
                    raise ColetorQuebrado(f"HTTP {resposta.status_code} no Serper")

                try:
                    corpo = resposta.json()
                except ValueError as e:
                    raise ColetorQuebrado(f"resposta não-JSON do Serper: {e}") from e

                ofertas = parsear_busca(corpo, descricao)
                if self._resolver_links:
                    ofertas = await self._verificar_na_loja(cliente, descricao, ofertas)
                return ofertas
        except httpx.TimeoutException as e:
            raise LojaIndisponivel(f"timeout no Serper: {e}") from e
        except httpx.TransportError as e:
            raise LojaIndisponivel(f"falha de rede no Serper: {e}") from e

    async def _verificar_na_loja(
        self, cliente: httpx.AsyncClient, descricao: str, ofertas: list[OfertaBruta]
    ) -> list[OfertaBruta]:
        """Descobrir no Serper → verificar na PÁGINA do produto (link + preço real).

        Para cada loja (dedup por `vendedor`): acha a página do produto e lê o
        preço ao vivo dela. Loja sem página de produto OU sem preço confirmado é
        **descartada** — melhor menos lojas do que preço/link errado.
        """
        fontes = list({o.vendedor for o in ofertas if o.vendedor})
        resolvidos = await asyncio.gather(
            *(self._resolver_loja(cliente, descricao, fonte) for fonte in fontes),
            return_exceptions=True,
        )
        # mapa: loja → (url_produto, preco_real, nome_real)
        mapa = {
            fonte: dados
            for fonte, dados in zip(fontes, resolvidos)
            if isinstance(dados, tuple)
        }
        novas: list[OfertaBruta] = []
        for oferta in ofertas:
            dados = mapa.get(oferta.vendedor or "")
            if dados is None:
                continue  # descartada: sem produto/preço confirmado
            url, preco, nome = dados
            # Título vem da PÁGINA (produto real), não do Google (que traz título
            # ruidoso/errado — ex.: "S25" numa página de S26). Cai pro do Google
            # só se a página não expuser nome.
            titulo = nome or oferta.titulo
            novas.append(replace(oferta, url=url, preco=preco, titulo=titulo))
        return novas

    async def _resolver_loja(
        self, cliente: httpx.AsyncClient, descricao: str, fonte: str
    ) -> tuple[str, Any, str | None] | None:
        """(url do produto, preço real, nome real) — ou None se não confirmar."""
        url = await self._link_direto(cliente, descricao, fonte)
        if url is None:
            return None
        preco, nome = await self._ler_pagina(cliente, url)
        if preco is None:
            return None
        return (url, preco, nome)

    async def _ler_pagina(
        self, cliente: httpx.AsyncClient, url: str
    ) -> tuple[Any | None, str | None]:
        """Lê preço e nome ao vivo da página do produto (schema.org). Falha → (None, None).

        Leitura educada de página pública (UA de navegador, 1 requisição). Se a
        loja não expõe o preço no HTML (ex.: VTEX que carrega via JS), devolve
        preço None e a loja é descartada.
        """
        try:
            resposta = await cliente.get(
                url, headers={"User-Agent": _USER_AGENT}, follow_redirects=True
            )
        except httpx.HTTPError:
            return None, None
        if resposta.status_code != 200:
            return None, None
        return _extrair_da_pagina(resposta.text)

    async def _link_direto(
        self, cliente: httpx.AsyncClient, descricao: str, fonte: str
    ) -> str | None:
        """Busca `descricao fonte` e devolve o 1º link que é a PÁGINA DO PRODUTO.

        Duas exigências (senão retorna None e a loja é descartada):
        1. domínio combina com o `source` (não cair em loja errada);
        2. é página de produto, não lista/busca (o usuário quer o produto exato,
           não "818 resultados").
        """
        resposta = await cliente.post(
            _URL_ORGANICA,
            headers=self._headers,
            json={"q": f"{descricao} {fonte}", "gl": "br", "hl": "pt-br", "num": 5},
        )
        if resposta.status_code != 200:
            return None
        organicos = resposta.json().get("organic")
        if not isinstance(organicos, list):
            return None
        for item in organicos:
            link = item.get("link") if isinstance(item, dict) else None
            if link and _dominio_combina(str(link), fonte) and _e_link_de_produto(str(link)):
                return _limpar_url(str(link))
        return None


def parsear_busca(corpo: Any, descricao: str = "") -> list[OfertaBruta]:
    """JSON do Serper → lista de `OfertaBruta` (pura). Uma oferta por loja.

    `descricao` monta o link de busca de fallback (usado se a resolução do link
    direto não rodar/falhar) — sempre um link que abre, nunca o morto do shopping.
    """
    if not isinstance(corpo, dict) or not isinstance(corpo.get("shopping"), list):
        raise ColetorQuebrado("JSON do Serper sem 'shopping' (formato mudou?)")

    ofertas: list[OfertaBruta] = []
    for item in corpo["shopping"]:
        oferta = _parsear_item(item, descricao)
        if oferta is not None:
            ofertas.append(oferta)
    return ofertas


def _link_de_busca(descricao: str, fonte: str) -> str:
    """Fallback grátis: busca do Google escopada pela loja (sempre abre)."""
    return "https://www.google.com/search?q=" + quote_plus(f"{descricao} {fonte}".strip())


# Parâmetros de rastreio que deixam a URL comprida à toa (e quebram na cópia).
# Tirá-los dá a URL canônica do produto (o `srsltid` do Google é o mais comum).
_PARAMS_RASTREIO = {
    "srsltid", "gclid", "gclsrc", "gad_source", "gbraid", "wbraid", "fbclid", "_gl",
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
}


def _limpar_url(url: str) -> str:
    """Remove parâmetros de rastreio → URL curta e canônica (que abre igual)."""
    partes = urlparse(url)
    if not partes.query:
        return url
    mantidos = [
        (chave, valor)
        for chave, valor in parse_qsl(partes.query, keep_blank_values=True)
        if chave.lower() not in _PARAMS_RASTREIO
    ]
    return urlunparse(partes._replace(query=urlencode(mantidos)))


# Marcas de URL de página de PRODUTO (não de lista/busca). Cobre os padrões mais
# comuns no varejo BR: /produto/, /p/, VTEX terminando em /p, Amazon /dp/, etc.
_MARCAS_PRODUTO = ("/produto/", "/produtos/", "/dp/", "/item/", "/pd/")


def _e_link_de_produto(url: str) -> bool:
    """É a página de UM produto (não uma lista/busca com vários)?

    Conservador de propósito: na dúvida, descarta. Antes trazer menos lojas, mas
    cada link abrindo o produto certo — que é o que o usuário pediu.
    """
    partes = urlparse(url)
    if "google.com" in partes.netloc:  # link de busca não é produto
        return False
    caminho = partes.path.lower()
    if any(marca in caminho for marca in _MARCAS_PRODUTO):
        return True
    # Padrão VTEX (Americanas, WebContinental, etc.): a URL do produto termina em /p.
    return caminho.endswith("/p") or caminho.endswith("/p/")


def _extrair_da_pagina(html: str) -> tuple[Decimal | None, str | None]:
    """Preço E nome do produto ao vivo, dos dados estruturados. Falha → None.

    Do JSON-LD schema.org (`offers.price`/`lowPrice` e `name`, o padrão da maioria
    das lojas); com fallback pra meta tags Open Graph. É parsing de dado
    **não-confiável** (loja externa): tudo validado, nunca cru. O nome vem da
    página (produto real), corrigindo o título ruidoso/errado do Google Shopping.
    """
    preco: Decimal | None = None
    nome: str | None = None
    for bloco in re.findall(
        r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.DOTALL
    ):
        p, n = _preco_e_nome_json_ld(bloco)
        preco = preco or p
        nome = nome or n
        if preco is not None and nome is not None:
            break
    if preco is None:
        meta = re.search(
            r'property=["\']product:price:amount["\']\s+content=["\']([\d.,]+)', html
        )
        preco = _para_dinheiro(meta.group(1)) if meta else None
    if nome is None:
        nome = _nome_open_graph(html)
    return preco, nome


def _extrair_preco(html: str) -> Decimal | None:
    """Só o preço da página (atalho sobre `_extrair_da_pagina`)."""
    return _extrair_da_pagina(html)[0]


def _nome_open_graph(html: str) -> str | None:
    m = re.search(r'property=["\']og:title["\']\s+content=["\']([^"\']+)', html)
    return unescape(m.group(1)).strip() if m else None


def _preco_e_nome_json_ld(bloco: str) -> tuple[Decimal | None, str | None]:
    try:
        dados = json.loads(bloco)
    except (ValueError, TypeError):
        return None, None
    # JSON-LD pode ser objeto, lista ou {"@graph": [...]}. Achata tudo.
    fila: list[Any] = dados if isinstance(dados, list) else [dados]
    for obj in list(fila):
        if isinstance(obj, dict) and isinstance(obj.get("@graph"), list):
            fila.extend(obj["@graph"])
    for obj in fila:
        if not isinstance(obj, dict):
            continue
        ofertas = obj.get("offers")
        if isinstance(ofertas, list):
            ofertas = ofertas[0] if ofertas else None
        if isinstance(ofertas, dict):
            preco = _para_dinheiro(ofertas.get("price") or ofertas.get("lowPrice"))
            if preco is not None:
                # Nome do MESMO produto que tem o preço (o mais confiável).
                bruto = obj.get("name")
                nome = unescape(str(bruto)).strip() if bruto else None
                return preco, nome
    return None, None


def _para_dinheiro(valor: Any) -> Decimal | None:
    """Número do JSON-LD/meta → Decimal. Aceita 449.9, "449.90", "1.234,56"."""
    if valor is None:
        return None
    texto = str(valor).strip()
    # Formato BR ("1.234,56"): tira milhar, vírgula vira ponto.
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        preco = dinheiro(texto)
    except (ValueError, DecimalException):
        return None
    return preco if preco > ZERO else None


def _dominio_combina(link: str, fonte: str) -> bool:
    """O domínio do link plausivelmente é a loja `fonte`?

    Compara o `source` (só letras/números, minúsculo) com o domínio: aceita se a
    raiz do domínio aparece no source, ou o source aparece no domínio (≥ 4 chars).
    Ex.: "Zoom"↔zoom.com.br ✓, "infoCELL"↔homedepot.com ✗.
    """
    alvo = re.sub(r"[^a-z0-9]", "", fonte.lower())
    if len(alvo) < 4:
        return False
    dominio = urlparse(link).netloc.lower().removeprefix("www.")
    raiz = dominio.split(".")[0]
    return (len(raiz) >= 4 and raiz in alvo) or (alvo in dominio)


def _parsear_item(item: Any, descricao: str = "") -> OfertaBruta | None:
    if not isinstance(item, dict):
        return None

    titulo = item.get("title")
    fonte = item.get("source")  # a LOJA de origem (Magalu, KaBuM!, ...)
    if not titulo or not fonte:
        return None
    # O `link` do shopping expira (cai na home do Google), então nem usamos: o
    # link começa como a busca escopada e vira o link direto na resolução.
    url = _link_de_busca(descricao or str(titulo), str(fonte))

    preco = _parsear_preco_br(item.get("price"))
    if preco is None or preco <= ZERO:
        return None

    return OfertaBruta(
        titulo=str(titulo),
        preco=preco,
        url=str(url),
        # Google Shopping não informa frete/à vista/estoque — não inventa (RN09).
        vendedor=str(fonte),
        em_estoque=True,  # listado no shopping = comprável; sem sinal de estoque
    )


# "R$ 1.234,56", "R$\xa0327,85 agora", "R$ 89,90" → Decimal. Formato BR:
# ponto = milhar, vírgula = decimal. Pega o 1º valor monetário (ignora ranges/sufixos).
_PRECO_BR = re.compile(r"R\$\s*([\d.]+,\d{2})")


def _parsear_preco_br(bruto: Any) -> Any | None:
    """Extrai o preço de uma string BR do Google Shopping. Falha → None (pula item)."""
    if not isinstance(bruto, str):
        return None
    achado = _PRECO_BR.search(bruto)
    if not achado:
        return None
    # "1.234,56" → "1234.56": tira o ponto de milhar, vírgula vira ponto decimal.
    normalizado = achado.group(1).replace(".", "").replace(",", ".")
    try:
        return dinheiro(normalizado)
    except (ValueError, DecimalException):
        return None
