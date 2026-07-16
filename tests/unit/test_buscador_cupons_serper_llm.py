"""Testes do BuscadorCuponsSerperLLM — descoberta de cupons por sinais.

Serper e NVIDIA são SEMPRE mockados (respx): nunca bate na rede real. Cobre o
status por sinais (corroboração entre fontes, validade vencida, 1 fonte só), o
parse defensivo (código inválido) e a degradação (sem chave, HTTP erro → []).
"""

import asyncio
import json
from datetime import date
from decimal import Decimal

import httpx
import respx

from adapters.cupons import BuscadorCuponsSerperLLM
from application.buscadores import Confianca, StatusCupom

_SERPER = "https://google.serper.dev/search"
_NVIDIA = "https://integrate.api.nvidia.com/v1/chat/completions"


def _buscador(**kw):
    return BuscadorCuponsSerperLLM(
        serper_api_key="serper-fake",
        nvidia_api_key="nvapi-fake",
        nvidia_model="modelo-teste",
        hoje=date(2026, 7, 15),
        **kw,
    )


def _serper_resp(organicos):
    return httpx.Response(200, json={"organic": organicos})


def _llm_resp(cupons):
    conteudo = json.dumps({"cupons": cupons})
    return httpx.Response(200, json={"choices": [{"message": {"content": conteudo}}]})


def _rodar(loja="KaBuM!"):
    return asyncio.run(_buscador().buscar(loja))


@respx.mock
def test_visto_em_duas_fontes_vira_provavel_valido():
    respx.post(_SERPER).mock(return_value=_serper_resp([
        {"title": "Cupom KaBuM NINJA15", "snippet": "use NINJA15 e ganhe 15%",
         "link": "https://www.cuponomia.com.br/kabum"},
        {"title": "NINJA15 funcionando", "snippet": "cupom NINJA15 KaBuM",
         "link": "https://www.pelando.com.br/kabum"},
    ]))
    respx.post(_NVIDIA).mock(return_value=_llm_resp([
        {"codigo": "NINJA15", "tipo": "percentual", "desconto": "15", "validade": "", "sinal_frescor": ""},
    ]))

    achados = _rodar()
    assert len(achados) == 1
    d = achados[0]
    assert d.cupom.codigo == "NINJA15"
    assert d.cupom.desconto == Decimal("15")
    assert d.status is StatusCupom.PROVAVEL_VALIDO
    assert d.confianca is Confianca.MEDIA  # 2 fontes
    assert d.aplicavel is True


@respx.mock
def test_extrai_categorias_do_cupom():
    respx.post(_SERPER).mock(return_value=_serper_resp([
        {"title": "CEL10 celular", "snippet": "CEL10 para celulares", "link": "https://cuponomia.com.br/a"},
        {"title": "CEL10", "snippet": "cupom CEL10", "link": "https://pelando.com.br/b"},
    ]))
    respx.post(_NVIDIA).mock(return_value=_llm_resp([
        {"codigo": "CEL10", "tipo": "percentual", "desconto": "10",
         "categorias": ["celular", "eletronicos"], "sinal_frescor": ""},
    ]))
    d = _rodar()[0]
    assert d.cupom.categorias == ("celular", "eletronicos")
    assert d.cupom.aplica_na_categoria("celular") is True
    assert d.cupom.aplica_na_categoria("geladeira") is False


@respx.mock
def test_validade_vencida_vira_expirado():
    respx.post(_SERPER).mock(return_value=_serper_resp([
        {"title": "VELHO10", "snippet": "cupom VELHO10", "link": "https://cuponomia.com.br/x"},
    ]))
    respx.post(_NVIDIA).mock(return_value=_llm_resp([
        {"codigo": "VELHO10", "tipo": "percentual", "desconto": "10",
         "validade": "2025-01-01", "sinal_frescor": ""},
    ]))

    d = _rodar()[0]
    assert d.status is StatusCupom.EXPIRADO
    assert d.aplicavel is False


@respx.mock
def test_uma_fonte_sem_frescor_vira_nao_confirmado():
    respx.post(_SERPER).mock(return_value=_serper_resp([
        {"title": "SOLO20", "snippet": "cupom SOLO20", "link": "https://siteqmquer.com/x"},
    ]))
    respx.post(_NVIDIA).mock(return_value=_llm_resp([
        {"codigo": "SOLO20", "tipo": "percentual", "desconto": "20", "validade": "", "sinal_frescor": ""},
    ]))

    d = _rodar()[0]
    assert d.status is StatusCupom.NAO_CONFIRMADO
    assert d.confianca is Confianca.BAIXA
    assert d.aplicavel is False


@respx.mock
def test_uma_fonte_com_frescor_vira_provavel_valido():
    respx.post(_SERPER).mock(return_value=_serper_resp([
        {"title": "FRESH5", "snippet": "cupom FRESH5", "link": "https://cuponomia.com.br/x"},
    ]))
    respx.post(_NVIDIA).mock(return_value=_llm_resp([
        {"codigo": "FRESH5", "tipo": "percentual", "desconto": "5", "validade": "",
         "sinal_frescor": "verificado hoje"},
    ]))

    d = _rodar()[0]
    assert d.status is StatusCupom.PROVAVEL_VALIDO
    assert any("verificado" in e for e in d.evidencias)


@respx.mock
def test_desconto_percentual_absurdo_nao_auto_aplica():
    # "até 70% OFF" vira código genérico; % alto = provável clickbait → não aplica.
    respx.post(_SERPER).mock(return_value=_serper_resp([
        {"title": "CUPOM70", "snippet": "cupom CUPOM70", "link": "https://cuponomia.com.br/a"},
        {"title": "CUPOM70", "snippet": "CUPOM70 KaBuM", "link": "https://pelando.com.br/b"},
    ]))
    respx.post(_NVIDIA).mock(return_value=_llm_resp([
        {"codigo": "CUPOM70", "tipo": "percentual", "desconto": "70", "sinal_frescor": "verificado hoje"},
    ]))
    d = _rodar()[0]
    assert d.status is StatusCupom.NAO_CONFIRMADO  # apesar de 2 fontes + frescor
    assert d.aplicavel is False


@respx.mock
def test_codigo_invalido_e_filtrado():
    respx.post(_SERPER).mock(return_value=_serper_resp([
        {"title": "x", "snippet": "algo", "link": "https://cuponomia.com.br/x"},
    ]))
    respx.post(_NVIDIA).mock(return_value=_llm_resp([
        {"codigo": "ab", "tipo": "percentual", "desconto": "10"},       # curto demais
        {"codigo": "12345678", "tipo": "fixo", "desconto": "50"},        # só dígitos
    ]))
    assert _rodar() == []


@respx.mock
def test_http_erro_no_serper_degrada_para_vazio():
    respx.post(_SERPER).mock(return_value=httpx.Response(500))
    assert _rodar() == []


@respx.mock
def test_llm_json_invalido_degrada_para_vazio():
    respx.post(_SERPER).mock(return_value=_serper_resp([
        {"title": "x", "snippet": "y", "link": "https://cuponomia.com.br/x"},
    ]))
    respx.post(_NVIDIA).mock(return_value=httpx.Response(
        200, json={"choices": [{"message": {"content": "desculpe, sem json"}}]}
    ))
    assert _rodar() == []


def test_sem_chave_nao_bate_na_rede():
    # Sem respx: se tocasse a rede, estouraria. Sem chave → [] direto.
    b = BuscadorCuponsSerperLLM(serper_api_key="", nvidia_api_key="")
    assert asyncio.run(b.buscar("KaBuM!")) == []
