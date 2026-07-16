
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

from datetime import datetime
from typing import Protocol

from application.buscadores import CupomDescoberto
from domain.cashback import Cashback
from domain.cupom import Cupom
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


class RepositorioCupom(Protocol):
    """Cupons por loja: manuais (você digita) + descobertos (buscador)."""

    def ativos_por_loja(self, loja_nome: str) -> list[Cupom]:
        """Aplicáveis no preço: manuais + descobertos prováveis-válidos."""
        ...

    def descobertos_por_loja(self, loja_nome: str) -> list[CupomDescoberto]:
        """Todos os descobertos da loja (qualquer status), pra carteira/UI."""
        ...

    def visto_em(self, loja_nome: str) -> datetime | None:
        """Última descoberta da loja (pro TTL do cache); None se nunca."""
        ...

    def todos(self) -> list[tuple[str, Cupom]]:
        """Todos os cupons cadastrados, agrupados por loja."""
        ...

    def listar_carteira(
        self,
    ) -> tuple[list[tuple[str, Cupom]], list[tuple[str, CupomDescoberto]]]:
        """Pra tela Carteira: (manuais, descobertos) separados por origem."""
        ...

    def salvar(self, loja_nome: str, cupom: Cupom) -> None:
        """Salva/atualiza um cupom MANUAL na loja."""
        ...

    def salvar_descoberto(
        self, loja_nome: str, descoberto: CupomDescoberto, quando: datetime
    ) -> None:
        """Upsert de um cupom DESCOBERTO (não sobrescreve manual)."""
        ...

    def remover(self, loja_nome: str, codigo: str) -> bool:
        """Remove o cupom (loja+código); devolve se removeu algo."""
        ...


class RepositorioCashback(Protocol):
    """Busca cashbacks disponíveis."""

    def ativos_por_loja(self, loja_nome: str) -> list[Cashback]:
        """Cashbacks ativos para a loja especificada."""
        ...

    def todos(self) -> list[tuple[str, Cashback]]:
        """Todos os cashbacks cadastrados, agrupados por loja."""
        ...

    def salvar(self, loja_nome: str, cashback: Cashback) -> None:
        """Salva ou atualiza um cashback na loja."""
        ...

    def remover(self, loja_nome: str, fonte: str) -> bool:
        """Remove o cashback (loja+fonte); devolve se removeu algo."""
        ...
