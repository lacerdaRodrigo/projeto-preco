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
import unicodedata
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
_URL_SCRAPE = "https://scrape.serper.dev"  # renderiza a página (fura anti-bot; 2 créditos)
# 40 resultados = leque largo de lojas numa busca (custa 2 créditos dos 2.500).
_NUM_RESULTADOS = 40
# Quantos orgânicos pedir pra achar o link direto da loja. Mais candidatos =
# mais chance de confirmar a loja renomada (o 1º resultado às vezes é lista/blog).
_NUM_ORGANICOS = 10
# UA de navegador pra ler a página do produto (algumas lojas bloqueiam o agente
# padrão de bibliotecas). Coleta educada, sem enganar — só evita bloqueio bobo.
_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125"
# Cabeçalhos de navegador de verdade: sem Accept/Accept-Language algumas lojas
# devolvem 403/desafio já na 1ª requisição. Manda o httpx confirmar mais lojas
# de graça, antes de cair pro scrape (que custa 2 créditos).
_HEADERS_NAVEGADOR = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


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
        usar_scrape: bool = True,
    ) -> None:
        if not api_key:
            raise ValueError("ColetorGoogleShopping exige SERPER_API_KEY")
        self._api_key = api_key
        self._timeout_s = timeout_s
        # Resolver o link direto gasta ~1 crédito por loja. Ligado por padrão
        # (o link do shopping é morto); desligável em teste/uso econômico.
        self._resolver_links = resolver_links_diretos
        # Fallback de preço via Serper scrape quando a loja bloqueia o httpx
        # (ML, Magalu). Renderiza a página e devolve o JSON-LD; +2 créditos/loja.
        self._usar_scrape = usar_scrape

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
        """Descobrir no Serper → tentar CONFIRMAR o preço na página da loja BR.

        Para cada loja (dedup por `vendedor`): acha a página BR do produto e lê o
        preço ao vivo. Confirmou → entra com o preço REAL (`preco_confirmado`).
        Não confirmou (loja bloqueou, sem página, sem dado estruturado) → NÃO some:
        entra com o preço de vitrine do Google Shopping, marcado como não-confirmado
        (a UI avisa). Assim a comparação traz as lojas BR de verdade, sem esconder
        de onde veio o preço. Quem julga se a oferta é o produto certo é o matcher.
        """
        fontes = list({o.vendedor for o in ofertas if o.vendedor})
        resolvidos = await asyncio.gather(
            *(self._resolver_loja(cliente, descricao, fonte) for fonte in fontes),
            return_exceptions=True,
        )
        # mapa: loja → (url_produto | None, preco_real | None, nome_real | None)
        mapa = {
            fonte: dados
            for fonte, dados in zip(fontes, resolvidos)
            if isinstance(dados, tuple)
        }
        novas: list[OfertaBruta] = []
        for oferta in ofertas:
            if not _loja_plausivelmente_br(oferta.vendedor):
                continue  # nome fora do alfabeto PT (vietnamita/CJK) → fora
            url, preco, nome = mapa.get(oferta.vendedor or "", (None, None, None))
            if url is None:
                # Página .br não resolveu. Se é loja BR RENOMADA, mantém como vitrine
                # (o link já é a busca escopada na loja, que abre); a IA valida se é
                # o produto certo. Senão, provável estrangeira (eBay, asus.com…) → fora.
                if _loja_br_conhecida(oferta.vendedor):
                    novas.append(replace(oferta, preco_confirmado=False))
                continue
            if preco is not None:
                # Confirmado: preço + título vêm da PÁGINA BR (produto real). O
                # título do Google é ruidoso/errado às vezes ("S25" numa de S26).
                novas.append(replace(
                    oferta, url=url, preco=preco,
                    titulo=nome or oferta.titulo, preco_confirmado=True,
                ))
            else:
                # Achou a página BR mas não leu o preço (bloqueio/sem dado):
                # mantém o preço de vitrine do Google Shopping, marcado.
                novas.append(replace(oferta, url=url, preco_confirmado=False))
        return novas

    async def _resolver_loja(
        self, cliente: httpx.AsyncClient, descricao: str, fonte: str
    ) -> tuple[str | None, Any, str | None]:
        """(url do produto BR | None, preço confirmado | None, nome | None).

        Sempre devolve tupla (nunca None): quem chama decide manter com vitrine
        quando o preço não confirma."""
        url = await self._link_direto(cliente, descricao, fonte)
        if url is None:
            return (None, None, None)
        preco, nome = await self._ler_pagina(cliente, url)
        return (url, preco, nome)

    async def _ler_pagina(
        self, cliente: httpx.AsyncClient, url: str
    ) -> tuple[Any | None, str | None]:
        """Lê preço e nome ao vivo da página do produto (schema.org). Falha → (None, None).

        Duas tentativas: (1) httpx direto (grátis) — resolve as lojas abertas;
        (2) se não veio preço (loja bloqueou com 403/desafio, ex.: ML/Magalu),
        cai no Serper scrape, que renderiza a página e fura o anti-bot (+2
        créditos). Assim o preço vem CONFIRMADO mesmo das lojas grandes.
        """
        try:
            resposta = await cliente.get(
                url, headers=_HEADERS_NAVEGADOR, follow_redirects=True
            )
            if resposta.status_code == 200:
                preco, nome = _extrair_da_pagina(resposta.text)
                if preco is not None:
                    return preco, nome
        except httpx.HTTPError:
            pass  # bloqueio/rede → tenta o scrape abaixo

        if self._usar_scrape:
            return await self._ler_via_scrape(cliente, url)
        return None, None

    async def _ler_via_scrape(
        self, cliente: httpx.AsyncClient, url: str
    ) -> tuple[Any | None, str | None]:
        """Preço e nome via Serper scrape (renderiza a página; fura anti-bot).

        Devolve o `jsonld` já parseado (dict) — reusamos o mesmo parser do
        schema.org. Sem preço estruturado → (None, None) e a loja é descartada
        (preço tem que ser confirmado, nunca vitrine)."""
        try:
            resposta = await cliente.post(
                _URL_SCRAPE, headers=self._headers, json={"url": url}
            )
        except httpx.HTTPError:
            return None, None
        if resposta.status_code != 200:
            return None, None
        try:
            corpo = resposta.json()
        except ValueError:
            return None, None
        jsonld = corpo.get("jsonld") if isinstance(corpo, dict) else None
        if jsonld is None:
            return None, None
        return _preco_e_nome_de_objeto(jsonld)

    async def _link_direto(
        self, cliente: httpx.AsyncClient, descricao: str, fonte: str
    ) -> str | None:
        """Busca `descricao fonte` e devolve o 1º link que é a PÁGINA DO PRODUTO.

        Duas exigências (senão retorna None e a loja é descartada):
        1. domínio combina com o `source` (não cair em loja errada);
        2. é página de produto, não lista/busca (o usuário quer o produto exato,
           não "818 resultados").
        """
        # Query CURTA (âncora: marca+modelo, sem as specs) resolve mais páginas de
        # produto — "Asus TUF Gaming A15 RTX 3050 512GB Casas Bahia" é específico
        # demais pro orgânico; "Asus TUF Gaming A15 Casas Bahia" acha a página.
        resposta = await cliente.post(
            _URL_ORGANICA,
            headers=self._headers,
            json={
                "q": f"{_ancora(descricao)} {fonte}",
                "gl": "br", "hl": "pt-br", "num": _NUM_ORGANICOS,
            },
        )
        if resposta.status_code != 200:
            return None
        organicos = resposta.json().get("organic")
        if not isinstance(organicos, list):
            return None
        for item in organicos:
            link = item.get("link") if isinstance(item, dict) else None
            if (
                link
                and _e_dominio_br(str(link))  # só loja BR (Amazon.com dos EUA fora)
                and _dominio_combina(str(link), fonte)
                and _e_link_de_produto(str(link))
            ):
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
_MARCAS_PRODUTO = ("/produto/", "/produtos/", "/dp/", "/gp/product/", "/item/", "/pd/")

# Mercado Livre forma CLÁSSICA (não-catálogo): produto.mercadolivre.com.br/MLB-
# 123456789-nome-_JM — sem /p/, então os padrões acima não pegam. É a maioria das
# ofertas do ML; sem isto o ML caía quase sempre. Casa o código MLB no caminho.
_ML_PRODUTO = re.compile(r"/mlb-?\d")


def _ancora(descricao: str, n: int = 4) -> str:
    """Os primeiros ``n`` tokens da busca — a âncora (marca+modelo) sem as specs.

    Resolver o link direto com a query inteira over-constringe o orgânico (a loja
    não titula com todas as specs); a âncora curta acha a página do produto."""
    return " ".join(descricao.split()[:n])


# Lojas BR renomadas (nome do vendedor no Google Shopping). REDE DE SEGURANÇA:
# quando a página do produto não resolve no orgânico (o Google não indexou a
# página exata daquela loja), uma loja BR conhecida ainda ENTRA como vitrine — a
# IA valida se é o produto certo depois. Sem isto, produto pouco indexado voltava
# 0 loja. Comparado sem acento/minúsculo, por substring. Estender à vontade.
_LOJAS_BR_CONHECIDAS = frozenset({
    "casas bahia", "casasbahia", "carrefour", "magazine luiza", "magazineluiza",
    "magalu", "mercado livre", "mercadolivre", "amazon", "kabum", "shopee",
    "fast shop",
    "fastshop", "ponto", "pontofrio", "americanas", "extra", "shoptime",
    "submarino", "girafa", "kalunga", "nissei", "brastemp", "compra certa",
    "compracerta", "consul", "electrolux", "samsung", "positivo", "dell", "havan",
    "leroy merlin", "madeiramadeira", "webcontinental", "gazin", "colombo",
    "terabyte", "pichau", "efacil", "ricardo eletro", "fnac", "lg eletronics",
})


def _nome_normalizado(nome: str) -> str:
    """Minúsculo e sem acento, pra comparar nome de loja de forma estável."""
    decomposto = unicodedata.normalize("NFKD", nome.lower())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def _loja_br_conhecida(nome: str | None) -> bool:
    """O vendedor é uma loja BR renomada? (rede de segurança quando a página não
    resolve). Substring sobre o nome normalizado — 'Casas Bahia - Seller' casa."""
    if not nome:
        return False
    alvo = _nome_normalizado(nome)
    return any(loja in alvo for loja in _LOJAS_BR_CONHECIDAS)


def _loja_plausivelmente_br(nome: str | None) -> bool:
    """O nome da loja cabe no alfabeto português? (barra loja estrangeira).

    Sem domínio pra checar o país (a oferta pode não ter resolvido link), o sinal
    é o próprio nome: PT usa ASCII + acentos do Latin-1 (≤ U+00FF, "Casas Bahia",
    "Nissei"). Nomes com caracteres além disso — vietnamita "Tiến" (U+1EBF), CJK —
    são de loja estrangeira que vazou no Google Shopping. Sem nome → mantém (o
    matcher ainda julga)."""
    if not nome:
        return True
    return all(ord(c) <= 0xFF for c in nome)


def _e_dominio_br(url: str) -> bool:
    """O link é de uma loja brasileira? (domínio termina em .br).

    Conserta o vazamento de loja estrangeira: "Amazon.com.br" no Google Shopping
    às vezes resolve pro `amazon.com` dos EUA (preço em dólar) — o token "amazon"
    combina, mas o país está errado. E-commerce BR usa .com.br/.br; exigir isso
    barra o produto errado sem depender de manter lista de domínios."""
    return urlparse(url).netloc.lower().endswith(".br")


def _e_link_de_produto(url: str) -> bool:
    """É a página de UM produto (não uma lista/busca com vários)?

    Conservador de propósito: na dúvida, descarta. Antes trazer menos lojas, mas
    cada link abrindo o produto certo — que é o que o usuário pediu (relaxar isso
    p/ slug puro foi testado ao vivo e trouxe páginas erradas → descartes).
    """
    partes = urlparse(url)
    if "google.com" in partes.netloc:  # link de busca não é produto
        return False
    caminho = partes.path.lower()
    # "/p/" cobre Mercado Livre catálogo (/p/MLB...), Magazine Luiza (/p/241.../) e afins.
    if any(marca in caminho for marca in _MARCAS_PRODUTO) or "/p/" in caminho:
        return True
    # Mercado Livre forma clássica (/MLB-123...-_JM), sem /p/ — a maioria das ofertas.
    if "mercadolivre" in partes.netloc.lower() and _ML_PRODUTO.search(caminho):
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
    return _preco_e_nome_de_objeto(dados)


def _preco_e_nome_de_objeto(dados: Any) -> tuple[Decimal | None, str | None]:
    """Preço e nome de um JSON-LD JÁ parseado (dict/lista). Reusado pelo scrape
    do Serper, que devolve o `jsonld` como objeto pronto (não texto)."""
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


# Apelidos de loja: o `source` do shopping nem sempre é o domínio. Mapeia o nome
# comercial → um pedaço que aparece no domínio. É config (estender = 1 linha).
_APELIDOS_LOJA: dict[str, str] = {
    "magalu": "magazineluiza",
    "mercadolivre": "mercadolivre",
    "mercado livre": "mercadolivre",
    "casas bahia": "casasbahia",
    "ponto": "pontofrio",
    "ponto frio": "pontofrio",
    "americanas": "americanas",
    "girafa": "girafa",
    "kabum": "kabum",
}
# Palavras genéricas de nome de loja que não identificam o domínio (não casar por elas).
_STOPWORDS_LOJA = frozenset({
    "loja", "lojas", "com", "online", "oficial", "store", "shop", "shopping",
    "supermercado", "brasil", "br", "the", "retail", "www", "site",
})


def _ascii(texto: str) -> str:
    """minúsculo e sem acento, convertido pra base (ô→o), não apagado."""
    decomposto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def _dominio_combina(link: str, fonte: str) -> bool:
    """O domínio do link plausivelmente é a loja `fonte`?

    Robusto a duas coisas que derrubavam lojas boas: (1) acento no nome
    ("TudoBônus"→tudobonus), convertido pra base em vez de apagado; (2) apelido
    comercial ("Magalu"→magazineluiza), via mapa. Casa se um token significativo
    do nome (≥4 chars, fora as palavras genéricas) aparece no domínio.
    """
    fonte_ascii = _ascii(fonte)
    dominio = _ascii(urlparse(link).netloc).removeprefix("www.")
    dominio_alnum = re.sub(r"[^a-z0-9]", "", dominio)

    # Apelido bate direto? ("magalu" → "magazineluiza" no domínio)
    apelido = _APELIDOS_LOJA.get(fonte_ascii.strip())
    if apelido and apelido in dominio_alnum:
        return True

    # Senão, algum token significativo do nome aparece no domínio?
    tokens = [t for t in re.split(r"[^a-z0-9]+", fonte_ascii) if len(t) >= 4]
    for token in tokens:
        if token in _STOPWORDS_LOJA:
            continue
        if token in dominio_alnum:
            return True
    return False


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
