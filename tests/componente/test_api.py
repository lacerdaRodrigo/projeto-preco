"""Testes do adaptador web (FastAPI) — CRUD de produto sobre um banco temporário.

Não bate em rede nem no banco real: cada teste usa um SQLite próprio (via
DATABASE_URL apontando pro tmp_path). O endpoint de busca (que usa rede) fica de
fora daqui — a lógica de coleta já é testada em test_buscar_produto/coletores.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    # Sem LLM no teste: o /rastrear usa a heurística (offline, determinístico).
    # Nunca bater em serviço real — a extração por LLM é testada com mock em
    # test_extrator_llm.py.
    monkeypatch.setenv("NVIDIA_API_KEY", "")
    from interface.api import app

    return TestClient(app)


def test_cadastrar_listar_e_obter(client):
    novo = {"nome": "Echo Dot 5", "categoria": "eletronicos", "marca": "Amazon"}
    resp = client.post("/api/produtos", json=novo)
    assert resp.status_code == 201
    criado = resp.json()
    assert criado["id"] >= 1
    assert criado["nome"] == "Echo Dot 5"

    lista = client.get("/api/produtos").json()
    assert [p["nome"] for p in lista] == ["Echo Dot 5"]

    detalhe = client.get(f"/api/produtos/{criado['id']}").json()
    assert detalhe["produto"]["marca"] == "Amazon"
    assert detalhe["ofertas"] == []  # sem busca ainda


def test_preco_referencia_e_palavras(client):
    novo = {
        "nome": "Galaxy S26 Ultra",
        "categoria": "smartphones",
        "preco_referencia": "8.999,90",  # formato BR do formulário
        "palavras_obrigatorias": ["S26", "Ultra"],
        "palavras_proibidas": ["capa", "S25"],
    }
    criado = client.post("/api/produtos", json=novo).json()
    assert criado["preco_referencia"] == "8999.90"
    assert criado["palavras_obrigatorias"] == ["S26", "Ultra"]


def test_preco_referencia_invalido_da_400(client):
    resp = client.post(
        "/api/produtos",
        json={"nome": "X", "categoria": "y", "preco_referencia": "abc"},
    )
    assert resp.status_code == 400


def test_rastrear_por_titulo_extrai_identidade(client):
    """Entrada título-first: cola o título, o backend extrai marca/modelo/categoria."""
    resp = client.post(
        "/api/rastrear",
        json={"titulo": "Smartphone Motorola Moto G67 5G 256GB 8GB RAM"},
    )
    assert resp.status_code == 201
    criado = resp.json()
    assert criado["nome"] == "Smartphone Motorola Moto G67 5G 256GB 8GB RAM"
    assert criado["marca"] == "Motorola"
    assert criado["modelo"] == "Moto G67"
    # entra na lista de monitorados como qualquer produto
    assert [p["id"] for p in client.get("/api/produtos").json()] == [criado["id"]]


def test_rastrear_aplica_refinamentos_opcionais(client):
    """Preço de referência (BR) e palavras não vêm do título — entram por cima."""
    criado = client.post(
        "/api/rastrear",
        json={
            "titulo": "Notebook Dell Inspiron 15",
            "categoria": "informatica",
            "preco_referencia": "3.499,90",
            "palavras_obrigatorias": ["Inspiron", "15"],
            "palavras_proibidas": ["usado"],
        },
    ).json()
    assert criado["categoria"] == "informatica"  # sobrescreve a detectada
    assert criado["preco_referencia"] == "3499.90"
    assert criado["palavras_obrigatorias"] == ["Inspiron", "15"]


def test_rastrear_titulo_vazio_da_400(client):
    resp = client.post("/api/rastrear", json={"titulo": "   "})
    assert resp.status_code == 400


def test_arquivar_some_da_lista(client):
    criado = client.post(
        "/api/produtos", json={"nome": "Sumir", "categoria": "teste"}
    ).json()
    assert client.delete(f"/api/produtos/{criado['id']}").status_code == 204
    assert client.get("/api/produtos").json() == []  # arquivado não aparece


def test_obter_inexistente_da_404(client):
    assert client.get("/api/produtos/999").status_code == 404
    assert client.delete("/api/produtos/999").status_code == 404
