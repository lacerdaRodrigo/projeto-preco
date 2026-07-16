"""Descoberta de cupons: Serper (busca web) + LLM (extrai códigos), validado por sinais.

Fluxo: busca "cupom {loja} desconto" no Serper → junta os snippets dos sites de
cupom (Cuponomia, Pelando, Méliuz…) → o LLM extrai os códigos candidatos e o que
a fonte disser (desconto, validade, "verificado hoje") → uma lógica determinística
dá o STATUS por sinais (validade vencida = expirado; visto em N fontes / frescor =
provável válido; 1 fonte só = não confirmado).

Fronteiras (CLAUDE.md): rede isolada aqui; o núcleo não importa isto. Dado externo
é **não-confiável** — valida o formato do código, parse defensivo, nunca crava.
Qualquer falha (sem chave, HTTP≠200, JSON inválido) → `[]` (degrada limpo, RN12).
**Nunca toca o checkout** — validade é por sinais, não por aplicar o cupom.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, DecimalException
from urllib.parse import urlparse

import httpx

from application.buscadores import (
    Confianca,
    CupomDescoberto,
    StatusCupom,
)
from domain.cupom import Cupom, TipoDesconto
from domain.dinheiro import ZERO

_URL_SERPER = "https://google.serper.dev/search"

_SISTEMA = (
    "Você extrai cupons de desconto de trechos de sites de cupom brasileiros. "
    "Recebe a LOJA e uma lista de TRECHOS numerados (resultados de busca). "
    "Devolva APENAS um objeto JSON válido, sem texto em volta, sem markdown: "
    '{"cupons": [{"codigo": "", "tipo": "", "desconto": "", "validade": "", '
    '"sinal_frescor": ""}]}. '
    "codigo = o código do cupom em MAIÚSCULAS (ex.: 'NINJA15'); só códigos reais, "
    "não invente. tipo = 'percentual' ou 'fixo'. desconto = só o número (ex.: "
    "'15'). validade = 'AAAA-MM-DD' quando o trecho informar, senão ''. "
    "sinal_frescor = curto, quando o trecho indicar que o cupom foi verificado/"
    "funcionou recentemente (ex.: 'verificado hoje', 'funcionou para 87%'), senão ''."
)


class BuscadorCuponsSerperLLM:
    """Descobre cupons de uma loja via Serper + LLM. Falha → `[]`."""

    def __init__(
        self,
        serper_api_key: str,
        nvidia_api_key: str,
        nvidia_base_url: str = "https://integrate.api.nvidia.com/v1",
        nvidia_model: str = "meta/llama-3.1-8b-instruct",
        timeout_s: float = 30.0,
        hoje: date | None = None,  # injetável nos testes (status por validade)
    ) -> None:
        self._serper_key = serper_api_key
        self._nvidia_key = nvidia_api_key
        self._nvidia_base = nvidia_base_url.rstrip("/")
        self._nvidia_model = nvidia_model
        self._timeout_s = timeout_s
        self._hoje = hoje or date.today()

    async def buscar(self, loja: str) -> list[CupomDescoberto]:
        """Loja → cupons descobertos com status. Sem chave/falha → `[]`."""
        if not (self._serper_key and self._nvidia_key and loja.strip()):
            return []
        async with httpx.AsyncClient(timeout=self._timeout_s) as cliente:
            trechos = await self._buscar_trechos(cliente, loja)
            if not trechos:
                return []
            brutos = await self._extrair(cliente, loja, [t for t, _ in trechos])
        return self._avaliar_todos(brutos, trechos)

    async def _buscar_trechos(
        self, cliente: httpx.AsyncClient, loja: str
    ) -> list[tuple[str, str]]:
        """Serper → lista de (texto, domínio-da-fonte). Falha → []."""
        try:
            resp = await cliente.post(
                _URL_SERPER,
                headers={"X-API-KEY": self._serper_key, "Content-Type": "application/json"},
                json={"q": f"cupom {loja} desconto", "gl": "br", "hl": "pt-br", "num": 10},
            )
        except httpx.HTTPError:
            return []
        if resp.status_code != 200:
            return []
        try:
            corpo = resp.json()
        except ValueError:
            return []
        trechos: list[tuple[str, str]] = []
        caixa = corpo.get("answerBox") if isinstance(corpo, dict) else None
        if isinstance(caixa, dict):
            texto = " ".join(
                str(caixa.get(c, "")) for c in ("title", "answer", "snippet")
            ).strip()
            if texto:
                trechos.append((texto, _dominio(str(caixa.get("link", "")))))
        organicos = corpo.get("organic") if isinstance(corpo, dict) else None
        if isinstance(organicos, list):
            for item in organicos:
                if not isinstance(item, dict):
                    continue
                texto = " ".join(
                    str(item.get(c, "")) for c in ("title", "snippet", "date")
                ).strip()
                if texto:
                    trechos.append((texto, _dominio(str(item.get("link", "")))))
        return trechos

    async def _extrair(
        self, cliente: httpx.AsyncClient, loja: str, textos: list[str]
    ) -> list[dict[str, object]]:
        """LLM extrai os cupons candidatos dos trechos. Falha → []."""
        lista = "\n".join(f"{i}. {t}" for i, t in enumerate(textos))
        pergunta = f"LOJA: {loja}\n\nTRECHOS:\n{lista}"
        try:
            resp = await cliente.post(
                f"{self._nvidia_base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._nvidia_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._nvidia_model,
                    "temperature": 0,
                    "max_tokens": 1200,
                    "messages": [
                        {"role": "system", "content": _SISTEMA},
                        {"role": "user", "content": pergunta},
                    ],
                },
            )
        except httpx.HTTPError:
            return []
        if resp.status_code != 200:
            return []
        try:
            conteudo = resp.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            return []
        dados = _extrair_json(str(conteudo))
        cupons = dados.get("cupons") if isinstance(dados, dict) else None
        return [c for c in cupons if isinstance(c, dict)] if isinstance(cupons, list) else []

    def _avaliar_todos(
        self, brutos: list[dict[str, object]], trechos: list[tuple[str, str]]
    ) -> list[CupomDescoberto]:
        textos = [t.lower() for t, _ in trechos]
        dominios = [d for _, d in trechos]
        vistos: set[str] = set()
        descobertos: list[CupomDescoberto] = []
        for bruto in brutos:
            codigo = _codigo(bruto.get("codigo"))
            if codigo is None or codigo in vistos:
                continue
            vistos.add(codigo)
            # Corroboração determinística: em quantas FONTES (domínios) o código aparece.
            fontes = {
                dominios[i]
                for i, texto in enumerate(textos)
                if codigo.lower() in texto and dominios[i]
            }
            tem_frescor = bool(_str(bruto.get("sinal_frescor")))
            validade = _data(bruto.get("validade"))
            cupom = Cupom(
                codigo=codigo,
                desconto=_decimal(bruto.get("desconto")),
                tipo=_tipo(bruto.get("tipo")),
                valor_min=ZERO,
                validade=validade,
            )
            status, confianca, evidencias = self._avaliar(
                validade, len(fontes), tem_frescor, _str(bruto.get("sinal_frescor"))
            )
            # Guarda anti-clickbait: "até 70% OFF" vira código genérico com % alto.
            # Desconto percentual absurdo não auto-aplica (não inventa preço falso).
            if (
                status is StatusCupom.PROVAVEL_VALIDO
                and cupom.tipo is TipoDesconto.PERCENTUAL
                and cupom.desconto >= Decimal("50")
            ):
                status = StatusCupom.NAO_CONFIRMADO
                confianca = Confianca.BAIXA
                evidencias = [*evidencias, "desconto alto — provável clickbait, confira"]
            descobertos.append(CupomDescoberto(cupom, status, confianca, evidencias))
        return descobertos

    def _avaliar(
        self, validade: date | None, fontes: int, tem_frescor: bool, frescor_txt: str | None
    ) -> tuple[StatusCupom, Confianca, list[str]]:
        """Traduz os sinais em status + confiança + evidências (determinístico)."""
        if validade is not None and validade < self._hoje:
            return (
                StatusCupom.EXPIRADO,
                Confianca.BAIXA,
                [f"expirou em {validade:%d/%m/%Y}"],
            )
        ev = [f"visto em {fontes} fonte(s)"] if fontes else ["1 menção"]
        if validade is not None:
            ev.append(f"expira {validade:%d/%m/%Y}")
        if fontes >= 3:
            return StatusCupom.PROVAVEL_VALIDO, Confianca.ALTA, ev
        if fontes >= 2:
            return StatusCupom.PROVAVEL_VALIDO, Confianca.MEDIA, ev
        if tem_frescor:
            return StatusCupom.PROVAVEL_VALIDO, Confianca.MEDIA, ev + [frescor_txt or "verificado recente"]
        return StatusCupom.NAO_CONFIRMADO, Confianca.BAIXA, ev


def _dominio(url: str) -> str:
    """Domínio da fonte (pra contar corroboração por site distinto)."""
    return urlparse(url).netloc.lower().removeprefix("www.")


def _extrair_json(texto: str) -> dict[str, object] | None:
    """Pega o objeto JSON da resposta, tolerando cercas/texto em volta."""
    inicio = texto.find("{")
    fim = texto.rfind("}")
    if inicio == -1 or fim <= inicio:
        return None
    try:
        dados = json.loads(texto[inicio : fim + 1])
    except (ValueError, TypeError):
        return None
    return dados if isinstance(dados, dict) else None


def _codigo(valor: object) -> str | None:
    """Código de cupom válido (A-Z0-9, 4–20). Qualquer outra coisa → None."""
    if not isinstance(valor, str):
        return None
    limpo = valor.strip().upper()
    if 4 <= len(limpo) <= 20 and limpo.isalnum() and any(c.isalpha() for c in limpo):
        return limpo
    return None


def _str(valor: object) -> str | None:
    if not isinstance(valor, str):
        return None
    return valor.strip() or None


def _tipo(valor: object) -> TipoDesconto:
    return TipoDesconto.FIXO if _str(valor) == "fixo" else TipoDesconto.PERCENTUAL


def _decimal(valor: object) -> Decimal:
    """Número do desconto; qualquer coisa inválida → 0 (não desconta)."""
    texto = _str(valor) if isinstance(valor, str) else str(valor) if valor is not None else None
    if not texto:
        return ZERO
    texto = texto.replace("%", "").replace("R$", "").replace(",", ".").strip()
    try:
        return Decimal(texto)
    except (DecimalException, ValueError):
        return ZERO


def _data(valor: object) -> date | None:
    """Validade em ISO (AAAA-MM-DD). Formato inesperado → None."""
    texto = _str(valor)
    if not texto:
        return None
    try:
        return date.fromisoformat(texto[:10])
    except ValueError:
        return None
