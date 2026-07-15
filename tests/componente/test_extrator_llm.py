"""Testes do ExtratorLLM (respx — nunca a API da NVIDIA ao vivo).

Prova o contrato: JSON do modelo → ReferenciaProduto com specs em `atributos`;
qualquer falha (HTTP, JSON, texto solto) → None, e a composição cai na heurística.
"""

import json

import httpx
import pytest
import respx

from adapters.extratores import extrair_identidade_do_titulo
from adapters.extratores.llm import ExtratorLLM

_URL = "https://integrate.api.nvidia.com/v1/chat/completions"


def _resposta(conteudo: str) -> httpx.Response:
    """Resposta OpenAI-compatível com o conteúdo do assistant."""
    return httpx.Response(200, json={"choices": [{"message": {"content": conteudo}}]})


@respx.mock
def test_extrai_identidade_rica_com_specs():
    conteudo = json.dumps({
        "marca": "Asus", "linha": "TUF Gaming", "modelo": "A15",
        "part_number": "FA507NV", "categoria": "notebook",
        "gpu": "RTX 3050", "cpu": "Ryzen 7", "ram": "16GB",
        "armazenamento": "512GB", "cor": "",
    })
    respx.post(_URL).mock(return_value=_resposta(conteudo))

    ref = ExtratorLLM("nvapi-fake").extrair(
        "Notebook Asus Tuf Gaming A15 3050 Ryzen 7 16gb 512gb Linux"
    )

    assert ref is not None
    assert ref.marca == "Asus"
    assert ref.modelo == "TUF Gaming A15"  # linha + modelo curto
    assert ref.categoria == "notebook"
    assert ref.atributos["gpu"] == "RTX 3050"
    assert ref.atributos["armazenamento"] == "512GB"
    assert ref.atributos["part_number"] == "FA507NV"
    # As specs seguem pro Produto (a busca e o gate de capacidade vão usá-las).
    assert ref.para_produto().atributos["armazenamento"] == "512GB"


@respx.mock
def test_tolera_json_entre_cercas_markdown():
    conteudo = '```json\n{"marca": "Dell", "linha": "Inspiron 15", "modelo": ""}\n```'
    respx.post(_URL).mock(return_value=_resposta(conteudo))

    ref = ExtratorLLM("k").extrair("Notebook Dell Inspiron 15 i5")

    assert ref is not None
    assert ref.marca == "Dell"
    assert ref.modelo == "Inspiron 15"


@respx.mock
def test_http_erro_degrada_para_none():
    respx.post(_URL).mock(return_value=httpx.Response(500))
    assert ExtratorLLM("k").extrair("qualquer título") is None


@respx.mock
def test_resposta_sem_json_degrada_para_none():
    respx.post(_URL).mock(return_value=_resposta("desculpe, não consegui"))
    assert ExtratorLLM("k").extrair("qualquer título") is None


def test_construtor_recusa_sem_chave():
    with pytest.raises(ValueError):
        ExtratorLLM("")


def test_titulo_vazio_nem_chama_a_api():
    # Sem request mockado: se tentasse chamar, respx/httpx acusaria. Não chama.
    assert ExtratorLLM("k").extrair("   ") is None


@respx.mock
def test_composicao_llm_falha_cai_na_heuristica():
    # LLM devolve 500 → a composição usa a heurística e ainda identifica o produto.
    respx.post(_URL).mock(return_value=httpx.Response(500))

    ref = extrair_identidade_do_titulo(
        "Smartphone Motorola Moto G67 5G 256GB",
        nvidia_api_key="nvapi-fake",
    )

    assert ref is not None
    assert ref.marca == "Motorola"
    assert ref.modelo == "Moto G67"


def test_composicao_sem_chave_usa_heuristica_direto():
    ref = extrair_identidade_do_titulo("Smartphone Motorola Moto G67 5G 256GB")
    assert ref is not None
    assert ref.marca == "Motorola"
