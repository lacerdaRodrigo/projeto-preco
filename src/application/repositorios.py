"""As PORTAS de persistência (§9): o núcleo fala com estas interfaces, nunca com
SQLite/Supabase direto. Trocar de banco = nova implementação, zero mudança aqui.

Três regras que estas portas carregam:
- **Escopo por conta (RN16):** todo método recebe `conta_id` e só enxerga/mexe
  no que é daquela conta. É a 1ª barreira de isolamento (o RLS é a 2ª, §27).
- **Idempotência (RN11):** `salvar_snapshot_se_mudou` só grava se algo mudou.
- **Rastreabilidade:** snapshot guarda url (via SKU) + timestamp.

Puro: só Protocols e um erro. Sem driver de banco.
"""

from __future__ import annotations

from typing import Protocol

from domain.produto import Produto
from domain.sku import SKU, SnapshotPreco


class AcessoForaDaConta(Exception):
    """Tentou mexer em dado de OUTRA conta (violação de isolamento, RN16).

    Mensagem sem PII: nunca inclui e-mail/CEP/dado pessoal (LGPD, §27)."""


class RepositorioProduto(Protocol):
    """Persistência de produtos, sempre escopada por conta."""

    def salvar(self, produto: Produto, conta_id: int) -> Produto:
        """Grava e devolve o produto com `id` preenchido."""
        ...

    def obter(self, produto_id: int, conta_id: int) -> Produto | None:
        """Um produto da conta, ou None se não existe/não é dela."""
        ...

    def produtos_ativos(self, conta_id: int) -> list[Produto]:
        """Os produtos `status='ativo'` da conta (o que a pipeline coleta)."""
        ...


class RepositorioSKU(Protocol):
    """Persistência de SKUs (oferta casada), 1 por produto+loja (RN01)."""

    def salvar_ou_atualizar(self, sku: SKU, conta_id: int) -> SKU:
        """Cria ou atualiza o SKU do par (produto, loja); devolve com `id`."""
        ...

    def de_produto(self, produto_id: int, conta_id: int) -> list[SKU]:
        """Os SKUs de um produto da conta."""
        ...


class RepositorioSnapshot(Protocol):
    """Histórico de preços (série temporal por SKU, §17)."""

    def ultimo_snapshot(self, sku_id: int, conta_id: int) -> SnapshotPreco | None:
        """O snapshot mais recente do SKU, ou None se ainda não houver."""
        ...

    def salvar_snapshot_se_mudou(
        self, snapshot: SnapshotPreco, conta_id: int
    ) -> SnapshotPreco | None:
        """Grava só se algo mudou vs. o último (RN11).

        Devolve o snapshot salvo (com `id`), ou None se nada mudou (não gravou).
        Rodar 2x com o mesmo dado não duplica.
        """
        ...
