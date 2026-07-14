"""Extrator por título colado (PLANO §1b) — o fallback de ÚLTIMA opção.

Quando não dá pra ler a URL (loja bloqueou, sem dado estruturado), eu colo o
título que copiei. Aqui o título JÁ É a identidade: vira o nome do produto, e o
matching compara sobre ele (a similaridade textual usa o título inteiro, então
marca/modelo/atributos escritos ali contam mesmo sem virar campo separado).

Por cima, a gente puxa só o sinal FORTE e inequívoco: um EAN (13 dígitos) escrito
no texto — o portão forte do matching. Código de modelo NÃO é extraído aqui de
propósito: por regex ele se confunde com specs ("512GB-SSD") e daria palpite
errado; ele continua no título e o matcher o usa como token. Conservador: na
dúvida, não chuta (dado não-confiável).
"""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

from adapters.extratores.heuristica import extrair_identidade
from domain.referencia import ReferenciaProduto

# Um EAN-13 isolado no texto (o padrão de código de barras no varejo BR).
_EAN = re.compile(r"\b(\d{13})\b")


def extrair_do_titulo(titulo: str) -> ReferenciaProduto | None:
    """Título colado → ReferenciaProduto. Vazio → None.

    Sem `url` (não veio de uma página) e sem `preco` (a busca é que vai achar os
    preços nas lojas). Só carrega a identidade: o título + um EAN, se houver.
    """
    limpo = titulo.strip()
    if not limpo:
        return None
    ident = extrair_identidade(limpo)
    achado = _EAN.search(limpo)
    return ReferenciaProduto(
        titulo=limpo,
        url="",
        ean=achado.group(1) if achado else None,
        marca=ident.marca,
        modelo=ident.modelo,
        categoria=ident.categoria,
    )


def extrair_do_slug(url: str) -> ReferenciaProduto | None:
    """URL → ReferenciaProduto tirando o título do próprio endereço (o "slug").

    Quando a loja bloqueia a leitura da página (ML, Magalu), o nome do produto
    ainda está ali na URL: `.../smartphone-motorola-moto-g67-5g-256gb/p/241203500`.
    Pega o segmento mais descritivo (o mais longo com hífen — ids não têm hífen),
    troca `-`/`_` por espaço e usa como título. Sem segmento assim → None.

    Diferente de `extrair_do_titulo`, aqui a gente TEM a URL de origem, então ela
    fica na referência (rastreável) — mas sem os parâmetros de rastreio.
    """
    partes = urlparse(url)
    candidatos = [seg for seg in partes.path.split("/") if "-" in seg or "_" in seg]
    if not candidatos:
        return None
    titulo = re.sub(r"[-_]+", " ", max(candidatos, key=len)).strip()
    titulo = re.sub(r"\s+", " ", titulo)
    if not titulo:
        return None
    ident = extrair_identidade(titulo)
    achado = _EAN.search(titulo)
    url_sem_rastreio = urlunparse(partes._replace(query="", fragment=""))
    return ReferenciaProduto(
        titulo=titulo,
        url=url_sem_rastreio,
        ean=achado.group(1) if achado else None,
        marca=ident.marca,
        modelo=ident.modelo,
        categoria=ident.categoria,
    )
