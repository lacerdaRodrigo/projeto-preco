"""Composição dos extratores: escolhe COMO tirar a identidade do título.

A regra de precedência num lugar só (reusada pelo CLI e pela API): tenta o LLM
(quando há chave) e, se ele falhar ou não vier, cai na heurística determinística.
Recebe só primitivos (chave/url/modelo), não a Config da app — mantém o adaptador
desacoplado de quem o configura.
"""

from __future__ import annotations

from adapters.extratores.llm import ExtratorLLM
from adapters.extratores.texto import extrair_do_titulo
from domain.referencia import ReferenciaProduto


def extrair_identidade_do_titulo(
    titulo: str,
    *,
    nvidia_api_key: str | None = None,
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1",
    nvidia_model: str = "qwen/qwen2.5-72b-instruct",
) -> ReferenciaProduto | None:
    """Título → ReferenciaProduto. LLM primeiro (se houver chave), heurística depois.

    O LLM já degrada pra `None` em qualquer falha (rede, JSON inválido, sem
    identidade), então aqui é só a precedência — o resultado da heurística é o
    piso garantido quando o LLM não entrega.
    """
    if nvidia_api_key:
        ref = ExtratorLLM(nvidia_api_key, nvidia_base_url, nvidia_model).extrair(titulo)
        if ref is not None:
            return ref
    return extrair_do_titulo(titulo)
