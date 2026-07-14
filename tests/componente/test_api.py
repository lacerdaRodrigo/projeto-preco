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


def test_arquivar_some_da_lista(client):
    criado = client.post(
        "/api/produtos", json={"nome": "Sumir", "categoria": "teste"}
    ).json()
    assert client.delete(f"/api/produtos/{criado['id']}").status_code == 204
    assert client.get("/api/produtos").json() == []  # arquivado não aparece


def test_obter_inexistente_da_404(client):
    assert client.get("/api/produtos/999").status_code == 404
    assert client.delete("/api/produtos/999").status_code == 404
