"""Adaptador de persistência em SQLite (stdlib `sqlite3`) para o V1.

Escolhas que valem explicar:
- **Queries sempre parametrizadas** (`?`), nunca SQL concatenado — barra SQL
  injection com dado de loja, que é não-confiável (CLAUDE.md/§27).
- **Dinheiro guardado como TEXT** (a string exata do Decimal), nunca REAL —
  REAL é float e reintroduziria o erro de arredondamento.
- **`conta_id` em todo acesso** (RN16): SKU e snapshot herdam a conta pelo
  produto (via JOIN), então mexer neles exige provar que o produto é da conta.
- **Idempotência** (RN11) mora no `salvar_snapshot_se_mudou`.

Tudo atrás das portas de `application.repositorios` — trocar por Supabase depois
não toca no núcleo.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from decimal import Decimal

from application.repositorios import AcessoForaDaConta
from domain.dinheiro import dinheiro
from domain.produto import Produto
from domain.sku import SKU, SnapshotPreco

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS produto (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conta_id INTEGER NOT NULL,
    nome TEXT NOT NULL,
    categoria TEXT NOT NULL,
    marca TEXT, modelo TEXT, ean TEXT, cor TEXT,
    preco_referencia TEXT,
    palavras_obrigatorias TEXT NOT NULL DEFAULT '[]',
    palavras_proibidas TEXT NOT NULL DEFAULT '[]',
    modelos_equivalentes TEXT NOT NULL DEFAULT '[]',
    atributos TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'ativo',
    hot INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sku (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    produto_id INTEGER NOT NULL REFERENCES produto(id) ON DELETE CASCADE,
    loja_id INTEGER NOT NULL,
    loja_origem TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL,
    titulo_original TEXT NOT NULL,
    score_match REAL NOT NULL,
    vendedor_oficial INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ativo',
    -- Identidade da oferta = (produto, loja, loja de origem). A `loja_origem`
    -- distingue as N lojas que um agregador (Google Shopping) traz numa busca só.
    UNIQUE (produto_id, loja_id, loja_origem)
);
CREATE TABLE IF NOT EXISTS snapshot_preco (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku_id INTEGER NOT NULL REFERENCES sku(id) ON DELETE CASCADE,
    preco TEXT NOT NULL,
    preco_avista TEXT, desconto_pix TEXT, frete TEXT,
    frete_cotado INTEGER NOT NULL DEFAULT 0,
    prazo_dias INTEGER, parcelas INTEGER,
    sem_juros INTEGER NOT NULL DEFAULT 0,
    em_estoque INTEGER NOT NULL DEFAULT 1,
    coletado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_produto_conta_status ON produto (conta_id, status);
CREATE INDEX IF NOT EXISTS ix_snapshot_sku_data ON snapshot_preco (sku_id, coletado_em);
"""

# Campos que definem "a oferta mudou" (RN11). `coletado_em` NÃO entra: o
# timestamp muda sempre, senão nunca seria idempotente.
_CAMPOS_OFERTA = (
    "preco",
    "preco_avista",
    "desconto_pix",
    "frete",
    "frete_cotado",
    "prazo_dias",
    "parcelas",
    "sem_juros",
    "em_estoque",
)


def conectar(caminho: str = ":memory:") -> sqlite3.Connection:
    """Abre a conexão, liga as FKs e cria o esquema (idempotente)."""
    conexao = sqlite3.connect(caminho)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA foreign_keys = ON")
    conexao.executescript(_ESQUEMA)
    conexao.commit()
    return conexao


# ---------- conversões dinheiro/JSON <-> TEXT ----------

def _txt(valor: Decimal | None) -> str | None:
    return str(valor) if valor is not None else None


def _dec(texto: str | None) -> Decimal | None:
    return dinheiro(texto) if texto is not None else None


# ---------- Produto ----------

class RepositorioProdutoSQLite:
    """Implementa `application.repositorios.RepositorioProduto`."""

    def __init__(self, conexao: sqlite3.Connection) -> None:
        self._con = conexao

    def salvar(self, produto: Produto, conta_id: int) -> Produto:
        cur = self._con.execute(
            """INSERT INTO produto
               (conta_id, nome, categoria, marca, modelo, ean, cor,
                preco_referencia, palavras_obrigatorias, palavras_proibidas,
                modelos_equivalentes, atributos, status, hot)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                conta_id,
                produto.nome,
                produto.categoria,
                produto.marca,
                produto.modelo,
                produto.ean,
                produto.cor,
                _txt(produto.preco_referencia),
                json.dumps(list(produto.palavras_obrigatorias)),
                json.dumps(list(produto.palavras_proibidas)),
                json.dumps(list(produto.modelos_equivalentes)),
                json.dumps(produto.atributos),
                produto.status,
                int(produto.hot),
            ),
        )
        self._con.commit()
        # dataclass é frozen: devolve uma cópia com o id que o banco gerou.
        from dataclasses import replace

        return replace(produto, id=cur.lastrowid)

    def obter(self, produto_id: int, conta_id: int) -> Produto | None:
        linha = self._con.execute(
            "SELECT * FROM produto WHERE id = ? AND conta_id = ?",
            (produto_id, conta_id),
        ).fetchone()
        return _linha_para_produto(linha) if linha else None

    def produtos_ativos(self, conta_id: int) -> list[Produto]:
        linhas = self._con.execute(
            "SELECT * FROM produto WHERE conta_id = ? AND status = 'ativo' ORDER BY id",
            (conta_id,),
        ).fetchall()
        return [_linha_para_produto(linha) for linha in linhas]

    def arquivar(self, produto_id: int, conta_id: int) -> bool:
        """Arquiva o produto (RF17): some da lista, mas o histórico fica no banco.
        Escopado por conta (RN16). Devolve False se não existir nessa conta."""
        cursor = self._con.execute(
            "UPDATE produto SET status = 'arquivado' WHERE id = ? AND conta_id = ?",
            (produto_id, conta_id),
        )
        self._con.commit()
        return cursor.rowcount > 0


def _linha_para_produto(linha: sqlite3.Row) -> Produto:
    return Produto(
        id=linha["id"],
        nome=linha["nome"],
        categoria=linha["categoria"],
        marca=linha["marca"],
        modelo=linha["modelo"],
        ean=linha["ean"],
        cor=linha["cor"],
        preco_referencia=_dec(linha["preco_referencia"]),
        palavras_obrigatorias=tuple(json.loads(linha["palavras_obrigatorias"])),
        palavras_proibidas=tuple(json.loads(linha["palavras_proibidas"])),
        modelos_equivalentes=tuple(json.loads(linha["modelos_equivalentes"])),
        atributos=json.loads(linha["atributos"]),
        status=linha["status"],
        hot=bool(linha["hot"]),
    )


# ---------- SKU ----------

class RepositorioSKUSQLite:
    """Implementa `application.repositorios.RepositorioSKU`."""

    def __init__(self, conexao: sqlite3.Connection) -> None:
        self._con = conexao

    def salvar_ou_atualizar(self, sku: SKU, conta_id: int) -> SKU:
        # Isolamento (RN16): o produto do SKU tem de ser da conta.
        _exige_produto_da_conta(self._con, sku.produto_id, conta_id)

        # RN01: 1 SKU por (produto, loja, loja de origem). Insere ou atualiza.
        self._con.execute(
            """INSERT INTO sku
                 (produto_id, loja_id, loja_origem, url, titulo_original,
                  score_match, vendedor_oficial, status)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT (produto_id, loja_id, loja_origem) DO UPDATE SET
                 url = excluded.url,
                 titulo_original = excluded.titulo_original,
                 score_match = excluded.score_match,
                 vendedor_oficial = excluded.vendedor_oficial,
                 status = excluded.status""",
            (
                sku.produto_id,
                sku.loja_id,
                sku.loja_origem,
                sku.url,
                sku.titulo_original,
                sku.score_match,
                int(sku.vendedor_oficial),
                sku.status,
            ),
        )
        self._con.commit()
        linha = self._con.execute(
            "SELECT id FROM sku WHERE produto_id = ? AND loja_id = ? AND loja_origem = ?",
            (sku.produto_id, sku.loja_id, sku.loja_origem),
        ).fetchone()
        from dataclasses import replace

        return replace(sku, id=linha["id"])

    def de_produto(self, produto_id: int, conta_id: int) -> list[SKU]:
        linhas = self._con.execute(
            """SELECT s.* FROM sku s
               JOIN produto p ON p.id = s.produto_id
               WHERE s.produto_id = ? AND p.conta_id = ?
               ORDER BY s.id""",
            (produto_id, conta_id),
        ).fetchall()
        return [_linha_para_sku(linha) for linha in linhas]


def _linha_para_sku(linha: sqlite3.Row) -> SKU:
    return SKU(
        id=linha["id"],
        produto_id=linha["produto_id"],
        loja_id=linha["loja_id"],
        loja_origem=linha["loja_origem"],
        url=linha["url"],
        titulo_original=linha["titulo_original"],
        score_match=linha["score_match"],
        vendedor_oficial=bool(linha["vendedor_oficial"]),
        status=linha["status"],
    )


# ---------- Snapshot ----------

class RepositorioSnapshotSQLite:
    """Implementa `application.repositorios.RepositorioSnapshot`."""

    def __init__(self, conexao: sqlite3.Connection) -> None:
        self._con = conexao

    def ultimo_snapshot(self, sku_id: int, conta_id: int) -> SnapshotPreco | None:
        linha = self._con.execute(
            """SELECT sn.* FROM snapshot_preco sn
               JOIN sku s ON s.id = sn.sku_id
               JOIN produto p ON p.id = s.produto_id
               WHERE sn.sku_id = ? AND p.conta_id = ?
               ORDER BY sn.coletado_em DESC, sn.id DESC
               LIMIT 1""",
            (sku_id, conta_id),
        ).fetchone()
        return _linha_para_snapshot(linha) if linha else None

    def salvar_snapshot_se_mudou(
        self, snapshot: SnapshotPreco, conta_id: int
    ) -> SnapshotPreco | None:
        # Isolamento (RN16): o SKU do snapshot tem de ser de um produto da conta.
        _exige_sku_da_conta(self._con, snapshot.sku_id, conta_id)

        anterior = self.ultimo_snapshot(snapshot.sku_id, conta_id)
        if anterior is not None and _mesma_oferta(anterior, snapshot):
            return None  # nada mudou → não grava (RN11)

        cur = self._con.execute(
            """INSERT INTO snapshot_preco
                 (sku_id, preco, preco_avista, desconto_pix, frete, frete_cotado,
                  prazo_dias, parcelas, sem_juros, em_estoque, coletado_em)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                snapshot.sku_id,
                _txt(snapshot.preco),
                _txt(snapshot.preco_avista),
                _txt(snapshot.desconto_pix),
                _txt(snapshot.frete),
                int(snapshot.frete_cotado),
                snapshot.prazo_dias,
                snapshot.parcelas,
                int(snapshot.sem_juros),
                int(snapshot.em_estoque),
                snapshot.coletado_em.isoformat(),
            ),
        )
        self._con.commit()
        from dataclasses import replace

        return replace(snapshot, id=cur.lastrowid)


def _linha_para_snapshot(linha: sqlite3.Row) -> SnapshotPreco:
    return SnapshotPreco(
        id=linha["id"],
        sku_id=linha["sku_id"],
        preco=dinheiro(linha["preco"]),
        preco_avista=_dec(linha["preco_avista"]),
        desconto_pix=_dec(linha["desconto_pix"]),
        frete=_dec(linha["frete"]),
        frete_cotado=bool(linha["frete_cotado"]),
        prazo_dias=linha["prazo_dias"],
        parcelas=linha["parcelas"],
        sem_juros=bool(linha["sem_juros"]),
        em_estoque=bool(linha["em_estoque"]),
        coletado_em=datetime.fromisoformat(linha["coletado_em"]),
    )


def _mesma_oferta(a: SnapshotPreco, b: SnapshotPreco) -> bool:
    """True se os dois snapshots representam a mesma oferta (ignora id/timestamp)."""
    return all(getattr(a, campo) == getattr(b, campo) for campo in _CAMPOS_OFERTA)


# ---------- guardas de isolamento por conta (RN16) ----------

def _exige_produto_da_conta(con: sqlite3.Connection, produto_id: int, conta_id: int) -> None:
    achou = con.execute(
        "SELECT 1 FROM produto WHERE id = ? AND conta_id = ?",
        (produto_id, conta_id),
    ).fetchone()
    if achou is None:
        raise AcessoForaDaConta("produto não pertence à conta")


def _exige_sku_da_conta(con: sqlite3.Connection, sku_id: int, conta_id: int) -> None:
    achou = con.execute(
        """SELECT 1 FROM sku s
           JOIN produto p ON p.id = s.produto_id
           WHERE s.id = ? AND p.conta_id = ?""",
        (sku_id, conta_id),
    ).fetchone()
    if achou is None:
        raise AcessoForaDaConta("SKU não pertence à conta")
