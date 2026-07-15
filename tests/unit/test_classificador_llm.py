"""Testes do ClassificadorLLM — o juiz de identidade por IA.

A rede é SEMPRE mockada (respx): nunca bate no NVIDIA de verdade. Cobre o caminho
feliz (JSON em lote → vereditos alinhados), o parse defensivo (índice fora, tipo
errado) e a degradação limpa (HTTP≠200, JSON inválido → tudo `None`).
"""

import httpx
import respx

from adapters.classificadores import ClassificadorLLM
from application.classificadores import VereditoIdentidade
from domain.oferta import OfertaBruta
from domain.produto import Produto

_URL = "https://integrate.api.nvidia.com/v1/chat/completions"


def _produto() -> Produto:
    return Produto(
        id=1,
        nome="Fone de Ouvido Bluetooth JBL Wave Buds",
        categoria="eletronicos",
        marca="JBL",
        modelo="Wave Buds",
    )


def _oferta(titulo: str) -> OfertaBruta:
    from decimal import Decimal

    return OfertaBruta(titulo=titulo, preco=Decimal("1"), url="http://x")


def _resposta(conteudo: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"content": conteudo}}]}
    )


def _classificador() -> ClassificadorLLM:
    return ClassificadorLLM("nvapi-fake", model="modelo-teste")


@respx.mock
def test_classifica_lote_alinhado_ao_input():
    conteudo = (
        '{"resultados": ['
        '{"i": 0, "mesmo": true, "motivo": "mesmo fone"},'
        '{"i": 1, "mesmo": false, "motivo": "geração diferente: Buds 2"},'
        '{"i": 2, "mesmo": false, "motivo": "linha diferente: Wave 200"}]}'
    )
    respx.post(_URL).mock(return_value=_resposta(conteudo))

    ofertas = [
        _oferta("Fone JBL Wave Buds"),
        _oferta("Fone JBL Wave Buds 2 ANC"),
        _oferta("Fone JBL Wave 200 TWS"),
    ]
    vereditos = _classificador().classificar(_produto(), ofertas)

    assert vereditos[0] == VereditoIdentidade(True, "mesmo fone")
    assert vereditos[1] == VereditoIdentidade(False, "geração diferente: Buds 2")
    assert vereditos[2] == VereditoIdentidade(False, "linha diferente: Wave 200")


@respx.mock
def test_indice_fora_ou_tipo_errado_vira_none():
    # i=5 não existe (só 1 oferta); "mesmo" como string não é confiável.
    conteudo = (
        '{"resultados": ['
        '{"i": 5, "mesmo": true, "motivo": "fora"},'
        '{"i": 0, "mesmo": "sim", "motivo": "tipo errado"}]}'
    )
    respx.post(_URL).mock(return_value=_resposta(conteudo))

    vereditos = _classificador().classificar(_produto(), [_oferta("Fone JBL Wave Buds")])
    assert vereditos == [None]


@respx.mock
def test_http_erro_degrada_para_none():
    respx.post(_URL).mock(return_value=httpx.Response(500))
    ofertas = [_oferta("a"), _oferta("b")]
    assert _classificador().classificar(_produto(), ofertas) == [None, None]


@respx.mock
def test_json_invalido_degrada_para_none():
    respx.post(_URL).mock(return_value=_resposta("desculpe, não consigo responder"))
    assert _classificador().classificar(_produto(), [_oferta("a")]) == [None]


def test_lista_vazia_nao_chama_rede():
    # Sem ofertas, nem toca na rede (respx não instalado aqui = garante isso).
    assert _classificador().classificar(_produto(), []) == []


def test_sem_chave_recusa_construcao():
    import pytest

    with pytest.raises(ValueError, match="chave"):
        ClassificadorLLM("")
