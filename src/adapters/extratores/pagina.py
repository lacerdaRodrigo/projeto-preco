"""Extrator por página (PLANO §1): URL de referência → ReferenciaProduto.

Leitor GENÉRICO (não um coletor por loja): lê o schema.org/JSON-LD, o dado
estruturado que o Google praticamente obriga toda loja séria a expor. Por isso
aceita URL de qualquer loja — e quando a loja o expõe, o EAN/modelo do móvel
aparece no HTML mesmo sem estar no título (desengata a "âncora").

Dado de loja é NÃO-CONFIÁVEL (CLAUDE.md): tudo é validado, nunca cru. Degradação
(RN12): loja bloqueou (403/captcha), sem JSON-LD, ou preço absurdo → **não
inventa**; devolve None e quem chamou cai pro fallback de título.

`extrair_referencia` é puro (testado contra HTML gravado); a rede fica isolada no
`LeitorDePagina.ler`.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, DecimalException
from html import unescape
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from adapters.extratores.heuristica import extrair_identidade
from domain.dinheiro import ZERO, dinheiro
from domain.referencia import ReferenciaProduto

# Cabeçalhos de navegador de verdade. Só o User-Agent NÃO basta: várias lojas
# (ex.: Zema) devolvem 403 quando falta o Accept/Accept-Language — elas checam o
# conjunto, não só o UA. Não engana ninguém: é uma leitura de 1 página que EU já
# abri no navegador, pedindo do mesmo jeito que o navegador pede.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}

# Chaves de GTIN no schema.org, da mais específica pra genérica. A 1ª preenchida
# vira o EAN — o portão forte do matching.
_CHAVES_GTIN = ("gtin13", "gtin14", "gtin12", "gtin8", "gtin", "ean")

# Parâmetros de rastreio que incham a URL colada (o `srsltid` do Google é o mais
# comum). Tirá-los dá a URL canônica do produto (que abre igual).
_PARAMS_RASTREIO = {
    "srsltid", "gclid", "gclsrc", "gad_source", "gbraid", "wbraid", "fbclid", "_gl",
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
}


class LeitorDePagina:
    """Lê a página de referência (I/O) e devolve a identidade. Degrada em None."""

    def __init__(self, timeout_s: float = 20.0) -> None:
        self._timeout_s = timeout_s

    async def ler(self, url: str) -> ReferenciaProduto | None:
        """Busca a página e extrai a identidade. Falha/bloqueio → None (RN12).

        Não loga a URL (pode conter dado pessoal — LGPD): no erro, só devolve None.
        """
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as cliente:
                resposta = await cliente.get(
                    url,
                    headers=_HEADERS,
                    follow_redirects=True,
                )
        except httpx.HTTPError:
            return None  # timeout/rede/bloqueio → cai pro fallback de título
        if resposta.status_code != 200:
            return None  # 403/404/5xx → idem
        return extrair_referencia(resposta.text, url)


def extrair_referencia(html: str, url: str) -> ReferenciaProduto | None:
    """HTML da página → ReferenciaProduto (puro). Sem título identificável → None.

    Anda a escada de identidade sobre o JSON-LD (schema.org): pega o 1º objeto
    Product e dele tira nome, marca, GTIN, modelo (MPN), cor, categoria e preço.
    Sem nome no JSON-LD, cai no og:title; sem preço, na meta tag Open Graph.
    """
    dados = _produto_do_json_ld(html)

    titulo = _texto(dados.get("name")) or _nome_open_graph(html)
    if not titulo:
        return None  # sem identidade não dá pra rastrear → fallback

    preco = _para_dinheiro(_preco_das_ofertas(dados.get("offers")))
    if preco is None:
        preco = _preco_open_graph(html)

    # JSON-LD manda quando traz o campo; senão, cai na heurística sobre o título
    # (lojas como a Zema servem o preço mas não a marca/modelo estruturados).
    ident = extrair_identidade(titulo)
    return ReferenciaProduto(
        titulo=titulo,
        url=_limpar_url(url),
        preco=preco,
        ean=_gtin(dados),
        marca=_texto(_desembrulhar_nome(dados.get("brand"))) or ident.marca,
        modelo=_texto(dados.get("mpn")) or ident.modelo,
        cor=_texto(dados.get("color")),
        categoria=_texto(dados.get("category")) or ident.categoria,
    )


def _produto_do_json_ld(html: str) -> dict[str, Any]:
    """1º objeto Product dos blocos JSON-LD (achata lista/@graph). {} se não achar.

    JSON-LD é dado externo, não-confiável: qualquer bloco malformado é ignorado
    (nunca estoura), e só objetos dict entram na busca.
    """
    for bloco in re.findall(
        r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.DOTALL
    ):
        try:
            dados = json.loads(bloco)
        except (ValueError, TypeError):
            continue
        fila: list[Any] = dados if isinstance(dados, list) else [dados]
        for obj in list(fila):
            if isinstance(obj, dict) and isinstance(obj.get("@graph"), list):
                fila.extend(obj["@graph"])
        for obj in fila:
            if isinstance(obj, dict) and _e_produto(obj):
                return obj
    return {}


def _e_produto(obj: dict[str, Any]) -> bool:
    """É um objeto Product do schema.org? Aceita @type "Product" ou lista com ele;
    na falta de @type, aceita se tiver nome + ofertas (basta pra identificar)."""
    tipo = obj.get("@type")
    tipos = tipo if isinstance(tipo, list) else [tipo]
    if any(isinstance(t, str) and t.lower() == "product" for t in tipos):
        return True
    return bool(obj.get("name") and obj.get("offers"))


def _preco_das_ofertas(ofertas: Any) -> Any:
    """price/lowPrice de offers (dict, ou lista → 1ª). Sem oferta → None."""
    if isinstance(ofertas, list):
        ofertas = ofertas[0] if ofertas else None
    if isinstance(ofertas, dict):
        return ofertas.get("price") or ofertas.get("lowPrice")
    return None


def _gtin(dados: dict[str, Any]) -> str | None:
    """1º GTIN/EAN preenchido, só dígitos. É a melhor chave de matching (§14)."""
    for chave in _CHAVES_GTIN:
        bruto = _texto(dados.get(chave))
        if bruto:
            digitos = re.sub(r"\D", "", bruto)
            if digitos:
                return digitos
    return None


def _desembrulhar_nome(valor: Any) -> Any:
    """brand pode ser "Acer" ou {"@type":"Brand","name":"Acer"} — pega o nome."""
    if isinstance(valor, dict):
        return valor.get("name")
    return valor


def _texto(valor: Any) -> str | None:
    """Normaliza um campo textual do JSON-LD: str não-vazia (desescapada) ou None."""
    if not isinstance(valor, (str, int, float)):
        return None
    texto = unescape(str(valor)).strip()
    return texto or None


def _nome_open_graph(html: str) -> str | None:
    m = re.search(r'property=["\']og:title["\']\s+content=["\']([^"\']+)', html)
    return unescape(m.group(1)).strip() if m else None


def _preco_open_graph(html: str) -> Decimal | None:
    m = re.search(
        r'property=["\']product:price:amount["\']\s+content=["\']([\d.,]+)', html
    )
    return _para_dinheiro(m.group(1)) if m else None


def _para_dinheiro(valor: Any) -> Decimal | None:
    """Número do JSON-LD/meta → Decimal. Aceita 2459.9, "2459.90", "2.459,00".

    Preço absurdo/nulo (≤ 0) → None: não é preço plausível, não vira referência (RN12).
    """
    if valor is None:
        return None
    texto = str(valor).strip()
    if "," in texto:  # formato BR ("2.459,00"): tira milhar, vírgula vira ponto
        texto = texto.replace(".", "").replace(",", ".")
    try:
        preco = dinheiro(texto)
    except (ValueError, DecimalException):
        return None
    return preco if preco > ZERO else None


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
