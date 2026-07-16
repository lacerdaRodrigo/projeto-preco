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

from application.buscadores import Confianca, CupomDescoberto, StatusCupom
from application.repositorios import AcessoForaDaConta
from domain.dinheiro import dinheiro
from domain.produto import Produto
from domain.sku import SKU, SnapshotPreco
from domain.cupom import Cupom
from domain.cashback import Cashback

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

CREATE TABLE IF NOT EXISTS cupom (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_origem TEXT NOT NULL,
    codigo TEXT NOT NULL,
    desconto TEXT NOT NULL,
    tipo TEXT NOT NULL,
    valor_min TEXT NOT NULL DEFAULT '0',
    validade TEXT,
    primeira_compra INTEGER NOT NULL DEFAULT 0,
    -- Descoberta automática: 'manual' (você digitou) vs 'descoberto' (buscador).
    origem TEXT NOT NULL DEFAULT 'manual',
    status TEXT,          -- provavel_valido | nao_confirmado | expirado (descoberto)
    confianca TEXT,       -- alta | media | baixa
    evidencias TEXT,      -- JSON: ["visto em 3 sites", ...]
    descoberto_em TEXT,   -- ISO; usado pra TTL do cache
    categorias TEXT,      -- JSON: ["celular","eletronicos"]; vazio/null = geral
    UNIQUE (loja_origem, codigo)
);

CREATE TABLE IF NOT EXISTS cashback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_origem TEXT NOT NULL,
    fonte TEXT NOT NULL,
    percentual TEXT NOT NULL,
    teto TEXT,
    condicao TEXT,
    UNIQUE (loja_origem, fonte)
);
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


# Colunas acrescentadas à tabela `cupom` depois que ela já existia (descoberta de
# cupons). `CREATE TABLE IF NOT EXISTS` não altera tabela existente, então a gente
# adiciona por ALTER, idempotente (pula a que já existe). SQLite sem PII aqui.
_COLUNAS_CUPOM_NOVAS = (
    ("origem", "TEXT NOT NULL DEFAULT 'manual'"),
    ("status", "TEXT"),
    ("confianca", "TEXT"),
    ("evidencias", "TEXT"),
    ("descoberto_em", "TEXT"),
    ("categorias", "TEXT"),
)


def _migrar(conexao: sqlite3.Connection) -> None:
    """Migrações leves pra bancos criados antes de colunas novas."""
    existentes = {
        linha["name"] for linha in conexao.execute("PRAGMA table_info(cupom)")
    }
    for nome, definicao in _COLUNAS_CUPOM_NOVAS:
        if nome not in existentes:
            conexao.execute(f"ALTER TABLE cupom ADD COLUMN {nome} {definicao}")


def conectar(caminho: str = ":memory:") -> sqlite3.Connection:
    """Abre a conexão, liga as FKs e cria o esquema (idempotente)."""
    conexao = sqlite3.connect(caminho)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA foreign_keys = ON")
    conexao.executescript(_ESQUEMA)
    _migrar(conexao)
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


# ---------- Cupom e Cashback ----------

class RepositorioCupomSQLite:
    def __init__(self, conexao: sqlite3.Connection) -> None:
        self._con = conexao

    def ativos_por_loja(self, loja_nome: str) -> list[Cupom]:
        # Aplicáveis no preço: manuais (você confia) + descobertos PROVÁVEL-VÁLIDOS.
        # Descoberto expirado/não-confirmado não desconta (só aparece na carteira).
        linhas = self._con.execute(
            "SELECT * FROM cupom WHERE loja_origem = ? "
            "AND (origem = 'manual' OR status = ?)",
            (loja_nome, StatusCupom.PROVAVEL_VALIDO.value),
        ).fetchall()
        return [_linha_para_cupom(linha) for linha in linhas]

    def descobertos_por_loja(self, loja_nome: str) -> list[CupomDescoberto]:
        """Todos os cupons DESCOBERTOS da loja (qualquer status) — pra carteira/UI."""
        linhas = self._con.execute(
            "SELECT * FROM cupom WHERE loja_origem = ? AND origem = 'descoberto' "
            "ORDER BY status, codigo",
            (loja_nome,),
        ).fetchall()
        return [_linha_para_descoberto(linha) for linha in linhas]

    def visto_em(self, loja_nome: str) -> datetime | None:
        """Quando a loja foi descoberta pela última vez (pro TTL do cache)."""
        linha = self._con.execute(
            "SELECT MAX(descoberto_em) AS m FROM cupom "
            "WHERE loja_origem = ? AND origem = 'descoberto'",
            (loja_nome,),
        ).fetchone()
        return datetime.fromisoformat(linha["m"]) if linha and linha["m"] else None

    def todos(self) -> list[tuple[str, Cupom]]:
        linhas = self._con.execute("SELECT * FROM cupom ORDER BY loja_origem").fetchall()
        return [(linha["loja_origem"], _linha_para_cupom(linha)) for linha in linhas]

    def listar_carteira(
        self,
    ) -> tuple[list[tuple[str, Cupom]], list[tuple[str, CupomDescoberto]]]:
        """Tudo pra tela Carteira: (manuais, descobertos) já separados por origem."""
        linhas = self._con.execute(
            "SELECT * FROM cupom ORDER BY loja_origem, codigo"
        ).fetchall()
        manuais: list[tuple[str, Cupom]] = []
        descobertos: list[tuple[str, CupomDescoberto]] = []
        for linha in linhas:
            loja = linha["loja_origem"]
            if linha["origem"] == "descoberto":
                descobertos.append((loja, _linha_para_descoberto(linha)))
            else:
                manuais.append((loja, _linha_para_cupom(linha)))
        return manuais, descobertos

    def salvar(self, loja_nome: str, cupom: Cupom) -> None:
        # Manual: você digitou → confiável. Marca origem='manual' e limpa os campos
        # de descoberta (se antes era descoberto, vira manual ao re-salvar).
        self._con.execute(
            """INSERT INTO cupom
                 (loja_origem, codigo, desconto, tipo, valor_min, validade,
                  primeira_compra, origem, status, confianca, evidencias,
                  descoberto_em, categorias)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'manual', NULL, NULL, NULL, NULL, ?)
               ON CONFLICT (loja_origem, codigo) DO UPDATE SET
                 desconto = excluded.desconto,
                 tipo = excluded.tipo,
                 valor_min = excluded.valor_min,
                 validade = excluded.validade,
                 primeira_compra = excluded.primeira_compra,
                 categorias = excluded.categorias,
                 origem = 'manual',
                 status = NULL, confianca = NULL, evidencias = NULL, descoberto_em = NULL""",
            (
                loja_nome,
                cupom.codigo,
                _txt(cupom.desconto),
                cupom.tipo.value,
                _txt(cupom.valor_min),
                cupom.validade.isoformat() if cupom.validade else None,
                int(cupom.primeira_compra),
                json.dumps(list(cupom.categorias)),
            ),
        )
        self._con.commit()

    def salvar_descoberto(
        self, loja_nome: str, descoberto: CupomDescoberto, quando: datetime
    ) -> None:
        """Upsert de um cupom DESCOBERTO. Nunca sobrescreve um manual (guarda no
        WHERE): o que você digitou tem prioridade sobre o que o buscador achou."""
        c = descoberto.cupom
        self._con.execute(
            """INSERT INTO cupom
                 (loja_origem, codigo, desconto, tipo, valor_min, validade,
                  primeira_compra, origem, status, confianca, evidencias,
                  descoberto_em, categorias)
               VALUES (?, ?, ?, ?, ?, ?, 0, 'descoberto', ?, ?, ?, ?, ?)
               ON CONFLICT (loja_origem, codigo) DO UPDATE SET
                 desconto = excluded.desconto,
                 tipo = excluded.tipo,
                 validade = excluded.validade,
                 status = excluded.status,
                 confianca = excluded.confianca,
                 evidencias = excluded.evidencias,
                 descoberto_em = excluded.descoberto_em,
                 categorias = excluded.categorias
               WHERE cupom.origem = 'descoberto'""",
            (
                loja_nome,
                c.codigo,
                _txt(c.desconto),
                c.tipo.value,
                _txt(c.valor_min),
                c.validade.isoformat() if c.validade else None,
                descoberto.status.value,
                descoberto.confianca.value,
                json.dumps(descoberto.evidencias),
                quando.isoformat(),
                json.dumps(list(c.categorias)),
            ),
        )
        self._con.commit()

    def remover(self, loja_nome: str, codigo: str) -> bool:
        cur = self._con.execute(
            "DELETE FROM cupom WHERE loja_origem = ? AND codigo = ?",
            (loja_nome, codigo),
        )
        self._con.commit()
        return cur.rowcount > 0


def _linha_para_descoberto(linha: sqlite3.Row) -> CupomDescoberto:
    ev = linha["evidencias"]
    return CupomDescoberto(
        cupom=_linha_para_cupom(linha),
        status=StatusCupom(linha["status"]) if linha["status"] else StatusCupom.NAO_CONFIRMADO,
        confianca=Confianca(linha["confianca"]) if linha["confianca"] else Confianca.BAIXA,
        evidencias=json.loads(ev) if ev else [],
    )


def _linha_para_cupom(linha: sqlite3.Row) -> Cupom:
    from domain.cupom import TipoDesconto
    validade_str = linha["validade"]
    cats = linha["categorias"] if "categorias" in linha.keys() else None
    return Cupom(
        codigo=linha["codigo"],
        desconto=_dec(linha["desconto"]) or Decimal("0"),
        tipo=TipoDesconto(linha["tipo"]),
        valor_min=_dec(linha["valor_min"]) or Decimal("0"),
        validade=datetime.fromisoformat(validade_str).date() if validade_str else None,
        primeira_compra=bool(linha["primeira_compra"]),
        categorias=tuple(json.loads(cats)) if cats else (),
    )

class RepositorioCashbackSQLite:
    def __init__(self, conexao: sqlite3.Connection) -> None:
        self._con = conexao

    def ativos_por_loja(self, loja_nome: str) -> list[Cashback]:
        linhas = self._con.execute(
            "SELECT * FROM cashback WHERE loja_origem = ?",
            (loja_nome,),
        ).fetchall()
        return [_linha_para_cashback(linha) for linha in linhas]

    def todos(self) -> list[tuple[str, Cashback]]:
        linhas = self._con.execute("SELECT * FROM cashback ORDER BY loja_origem").fetchall()
        return [(linha["loja_origem"], _linha_para_cashback(linha)) for linha in linhas]

    def salvar(self, loja_nome: str, cashback: Cashback) -> None:
        self._con.execute(
            """INSERT INTO cashback
                 (loja_origem, fonte, percentual, teto, condicao)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (loja_origem, fonte) DO UPDATE SET
                 percentual = excluded.percentual,
                 teto = excluded.teto,
                 condicao = excluded.condicao""",
            (
                loja_nome,
                cashback.fonte,
                _txt(cashback.percentual),
                _txt(cashback.teto),
                cashback.condicao,
            ),
        )
        self._con.commit()

    def remover(self, loja_nome: str, fonte: str) -> bool:
        cur = self._con.execute(
            "DELETE FROM cashback WHERE loja_origem = ? AND fonte = ?",
            (loja_nome, fonte),
        )
        self._con.commit()
        return cur.rowcount > 0


def _linha_para_cashback(linha: sqlite3.Row) -> Cashback:
    return Cashback(
        fonte=linha["fonte"],
        percentual=_dec(linha["percentual"]) or Decimal("0"),
        teto=_dec(linha["teto"]),
        condicao=linha["condicao"]
    )
