"""O resultado de uma decisão de matching — sempre EXPLICÁVEL (§14).

O matcher nunca devolve só "sim/não": devolve o destino, o score e o **porquê**
(qual etapa decidiu). Isso alimenta a fila "revisar" e deixa a gente depurar
("rejeitou porque faltou '512'"). Explicabilidade é requisito, não luxo.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Destino(str, Enum):
    """Para onde a oferta vai depois do matching (RN04)."""

    ACEITA = "aceita"  # score ≥ 0.85 → entra no ranking
    REVISAR = "revisar"  # 0.6–0.85 → segura para eu confirmar
    DESCARTA = "descarta"  # < 0.6, veto ou atributo divergente → fora


class Etapa(str, Enum):
    """Qual portão/pontuador do pipeline tomou a decisão (§14)."""

    EAN = "ean"  # portão forte
    VETO = "veto"  # palavra proibida / obrigatória
    ATRIBUTO = "atributo"  # atributo-chave divergente
    SIMILARIDADE = "similaridade"  # pontuador textual


@dataclass(frozen=True)
class ResultadoMatch:
    """A decisão do matcher, com a razão junto."""

    destino: Destino
    score: float  # confiança em [0, 1]
    etapa: Etapa  # quem decidiu
    motivo: str  # em português, legível ("faltou palavra obrigatória: '512'")

    @property
    def aceita(self) -> bool:
        return self.destino is Destino.ACEITA
