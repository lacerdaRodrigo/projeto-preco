"""Entidade Produto — o que EU quero acompanhar (não a oferta de uma loja).

Puro: só dados e regras, sem rede/banco/UI (regra do CLAUDE.md). Ver PRD §11.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class Produto:
    """Um produto cadastrado por mim para vigiar o preço.

    ``frozen=True``: depois de criado não muda (evita alteração acidental).

    Obrigatórios: ``nome`` e ``categoria`` (PRD §11). Os demais são
    recomendados/opcionais e ajudam o matching a acertar a oferta certa.
    """

    # Obrigatórios (PRD §11)
    nome: str
    categoria: str

    # Recomendados — EAN/GTIN é a melhor chave de matching quando existe
    marca: str | None = None
    modelo: str | None = None
    ean: str | None = None
    cor: str | None = None

    # Preço que eu considero justo (referência para "vale a pena?")
    preco_referencia: Decimal | None = None

    # Controle de matching por produto (PRD §11/§14). Ex.: proibir "capa",
    # exigir "128gb", aceitar modelos equivalentes.
    palavras_obrigatorias: tuple[str, ...] = ()
    palavras_proibidas: tuple[str, ...] = ()
    modelos_equivalentes: tuple[str, ...] = ()

    # Atributos livres por categoria (voltagem, memória, tamanho...). PRD §11.
    atributos: dict[str, str] = field(default_factory=dict)

    # Estado do acompanhamento e destaque.
    status: str = "ativo"
    hot: bool = False

    id: int | None = None  # None enquanto não foi salvo (o repositório preenche)

    def __post_init__(self) -> None:
        # Invariante do §11: sem nome e categoria não é um produto válido.
        if not self.nome.strip():
            raise ValueError("Produto precisa de um nome.")
        if not self.categoria.strip():
            raise ValueError("Produto precisa de uma categoria.")
