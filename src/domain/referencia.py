"""ReferenciaProduto — a identidade canônica de um produto que EU já achei.

A "porta da frente" do rastreador (ver PLANO §1): eu pesquiso no Google, acho a
loja e o produto certo, e colo a URL. O extrator lê a página e devolve esta
identidade — o nome canônico + a melhor chave de matching que a página expõe.

Puro: só um objeto de valor, sem rede/banco/UI. Quem lê a página (I/O) é o
adaptador em `adapters/extratores/`; aqui só mora o formato e a conversão para
`Produto`, a entidade que o resto do sistema (busca, matching) já consome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from domain.produto import Produto

# Categoria usada quando a página não declara nenhuma — não quebra o Produto
# (que exige categoria) nem o matching (o check por categoria só ignora).
CATEGORIA_PADRAO = "geral"


@dataclass(frozen=True)
class ReferenciaProduto:
    """O que o extrator tira da página do produto de referência.

    A escada de identidade do PLANO, do sinal mais forte pro mais fraco: EAN/GTIN
    → marca + modelo → o título canônico (que carrega os atributos como texto:
    "4 cadeiras preto madeira"). Só o ``titulo`` é obrigatório — é o mínimo pra
    identificar o produto; o resto entra quando a página expõe.
    """

    titulo: str  # nome canônico da página (identidade + atributos como texto)
    url: str  # de onde veio — todo preço é rastreável (URL + timestamp)
    preco: Decimal | None = None  # preço na loja onde eu achei (referência)
    ean: str | None = None  # GTIN/EAN — o portão FORTE do matching quando existe
    marca: str | None = None
    modelo: str | None = None  # part number do fabricante (MPN), quando há
    cor: str | None = None
    categoria: str | None = None  # da página (breadcrumb), quando há
    # Specs-chave que ajudam busca e matching (ex.: {"gpu": "RTX 3050",
    # "armazenamento": "512GB", "ram": "16GB"}). Vazio quando o extrator não sabe.
    atributos: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Sem título não há identidade — o extrator devolve None nesse caso, então
        # aqui é só uma guarda de sanidade contra construção inválida.
        if not self.titulo.strip():
            raise ValueError("ReferenciaProduto precisa de um título.")

    def para_produto(self) -> Produto:
        """Vira um `Produto` (o que eu quero vigiar), pronto pra busca/matching."""
        return Produto(
            nome=self.titulo,
            categoria=self.categoria or CATEGORIA_PADRAO,
            marca=self.marca,
            modelo=self.modelo,
            ean=self.ean,
            cor=self.cor,
            preco_referencia=self.preco,
            atributos=dict(self.atributos),
        )
