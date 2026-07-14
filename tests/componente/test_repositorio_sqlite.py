"""Testes do adaptador SQLite (§9/§23).

Cobrem as três promessas das portas: escopo por conta (RN16 — segurança),
idempotência (RN11) e dinheiro exato (Decimal, nunca float).
"""

from datetime import datetime
from decimal import Decimal

import pytest

from adapters.repositorios.sqlite import (
    RepositorioProdutoSQLite,
    RepositorioSKUSQLite,
    RepositorioSnapshotSQLite,
    conectar,
)
from application.repositorios import AcessoForaDaConta
from domain import SKU, Produto, SnapshotPreco

CONTA = 1
OUTRA_CONTA = 2


@pytest.fixture
def con():
    conexao = conectar(":memory:")
    yield conexao
    conexao.close()


def _snapshot(sku_id: int, preco: str) -> SnapshotPreco:
    return SnapshotPreco(
        sku_id=sku_id, preco=Decimal(preco), coletado_em=datetime(2026, 7, 11, 10, 0)
    )


# ---------- Produto: round-trip ----------

def test_salva_e_le_produto_preservando_tipos(con):
    repo = RepositorioProdutoSQLite(con)
    produto = Produto(
        nome="Echo Dot 5",
        categoria="eletronicos",
        marca="Amazon",
        preco_referencia=Decimal("299.90"),
        palavras_proibidas=("capa",),
        atributos={"cor": "preto"},
    )

    salvo = repo.salvar(produto, CONTA)
    assert salvo.id is not None

    lido = repo.obter(salvo.id, CONTA)
    assert lido is not None
    assert lido.nome == "Echo Dot 5"
    assert lido.preco_referencia == Decimal("299.90")  # Decimal, não float
    assert lido.palavras_proibidas == ("capa",)
    assert lido.atributos == {"cor": "preto"}


def test_produtos_ativos_ignora_inativos(con):
    repo = RepositorioProdutoSQLite(con)
    repo.salvar(Produto(nome="Ativo", categoria="x"), CONTA)
    repo.salvar(Produto(nome="Arquivado", categoria="x", status="inativo"), CONTA)

    ativos = repo.produtos_ativos(CONTA)
    assert [p.nome for p in ativos] == ["Ativo"]


# ---------- SKU: 1 por produto+loja (RN01) ----------

def test_sku_e_upsert_por_produto_e_loja(con):
    repo_p = RepositorioProdutoSQLite(con)
    repo_s = RepositorioSKUSQLite(con)
    produto = repo_p.salvar(Produto(nome="P", categoria="x"), CONTA)

    repo_s.salvar_ou_atualizar(
        SKU(produto_id=produto.id, loja_id=10, url="u1", titulo_original="t1",
            score_match=0.9),
        CONTA,
    )
    # Mesma loja de novo: atualiza, não cria um segundo (RN01).
    repo_s.salvar_ou_atualizar(
        SKU(produto_id=produto.id, loja_id=10, url="u2", titulo_original="t2",
            score_match=0.95),
        CONTA,
    )

    skus = repo_s.de_produto(produto.id, CONTA)
    assert len(skus) == 1
    assert skus[0].url == "u2"  # ficou o mais recente


# ---------- Snapshot: idempotência (RN11) ----------

def test_snapshot_nao_duplica_quando_nada_muda(con):
    sku = _prepara_sku(con)
    repo = RepositorioSnapshotSQLite(con)

    primeiro = repo.salvar_snapshot_se_mudou(_snapshot(sku.id, "100.00"), CONTA)
    repetido = repo.salvar_snapshot_se_mudou(_snapshot(sku.id, "100.00"), CONTA)

    assert primeiro is not None
    assert repetido is None  # nada mudou → não gravou (RN11)


def test_snapshot_grava_quando_preco_muda(con):
    sku = _prepara_sku(con)
    repo = RepositorioSnapshotSQLite(con)

    repo.salvar_snapshot_se_mudou(_snapshot(sku.id, "100.00"), CONTA)
    mudou = repo.salvar_snapshot_se_mudou(_snapshot(sku.id, "89.90"), CONTA)

    assert mudou is not None
    ultimo = repo.ultimo_snapshot(sku.id, CONTA)
    assert ultimo.preco == Decimal("89.90")  # Decimal exato


# ---------- Isolamento por conta (RN16) — SEGURANÇA ----------

def test_uma_conta_nao_enxerga_produto_da_outra(con):
    repo = RepositorioProdutoSQLite(con)
    salvo = repo.salvar(Produto(nome="Secreto", categoria="x"), CONTA)

    # A outra conta não pode ler, mesmo sabendo o id.
    assert repo.obter(salvo.id, OUTRA_CONTA) is None
    assert repo.produtos_ativos(OUTRA_CONTA) == []


def test_nao_grava_sku_em_produto_de_outra_conta(con):
    repo_p = RepositorioProdutoSQLite(con)
    repo_s = RepositorioSKUSQLite(con)
    produto = repo_p.salvar(Produto(nome="Meu", categoria="x"), CONTA)

    with pytest.raises(AcessoForaDaConta):
        repo_s.salvar_ou_atualizar(
            SKU(produto_id=produto.id, loja_id=10, url="u", titulo_original="t",
                score_match=0.9),
            OUTRA_CONTA,
        )


def test_nao_grava_snapshot_em_sku_de_outra_conta(con):
    sku = _prepara_sku(con)  # criado na CONTA
    repo = RepositorioSnapshotSQLite(con)

    with pytest.raises(AcessoForaDaConta):
        repo.salvar_snapshot_se_mudou(_snapshot(sku.id, "100.00"), OUTRA_CONTA)


# ---------- helpers ----------

def _prepara_sku(con) -> SKU:
    produto = RepositorioProdutoSQLite(con).salvar(
        Produto(nome="P", categoria="x"), CONTA
    )
    return RepositorioSKUSQLite(con).salvar_ou_atualizar(
        SKU(produto_id=produto.id, loja_id=10, url="u", titulo_original="t",
            score_match=0.9),
        CONTA,
    )
