"""Config do matching: dicionários e limiares.

Regra do §14: **traduções, sinônimos, palavras-ruído, thresholds e pesos são
configuração, não código** — você afina o matcher sem mexer na lógica. Tudo
que é "ajuste fino" mora aqui; o `matcher.py` só aplica.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConfigMatching:
    """Parâmetros que afinam o matcher (todos com padrão sensato)."""

    # Limiares de decisão (RN04). Score ≥ aceita → ACEITA; ≥ revisar → REVISAR;
    # abaixo → DESCARTA.
    limiar_aceita: float = 0.85
    limiar_revisar: float = 0.6

    # Categorias onde o modelo-linha É o SKU definitivo (G67 ≠ G17): se o token do
    # modelo não aparece na oferta, é OUTRO produto → DESCARTA duro. Nas demais
    # (notebook: "A15" é série, não config), a ausência não decide — cai na
    # similaridade, que pode mandar pra REVISAR em vez de sumir em silêncio.
    categorias_modelo_forte: frozenset[str] = frozenset({"celular"})

    # Traduções de cor (inglês → português) para "black" e "preto" casarem.
    cores: dict[str, str] = field(
        default_factory=lambda: {
            "black": "preto",
            "white": "branco",
            "blue": "azul",
            "red": "vermelho",
            "green": "verde",
            "gray": "cinza",
            "grey": "cinza",
            "silver": "prata",
            "gold": "dourado",
            "pink": "rosa",
            "purple": "roxo",
        }
    )

    # Palavras que denunciam ACESSÓRIO/PEÇA (não o produto em si). Vetadas só
    # quando aparecem na oferta e NÃO no nome do meu produto — se eu rastreio um
    # refil, meu nome tem "refil" e não veta. Pega o clássico "Refil para
    # Purificador PE12G" / "Mouse para Notebook A15" (§14).
    vetos_acessorio: tuple[str, ...] = (
        "refil", "refis", "kit", "compativel", "capa", "case", "pelicula",
        "suporte", "cabo", "carregador", "adaptador", "mouse", "teclado",
        "cooler", "bomba", "pingadeira", "gabinete", "protetor", "adesivo",
        "brinde", "skin", "membrana", "valvula",
    )

    # Palavras/frases-ruído removidas antes de comparar (não ajudam a identificar
    # o produto). Só afetam a similaridade — vetos ("seminovo") são outra etapa.
    ruido: tuple[str, ...] = (
        "frete gratis",
        "sem juros",
        "a vista",
        "pronta entrega",
        "envio imediato",
        "original",
        "lacrado",
        "promocao",
        "oferta",
        "nota fiscal",
    )

    # Atributos-chave por categoria (§11/§14): quais atributos, se divergirem,
    # já dizem "produto diferente". No V1 focamos em capacidade (GB/TB), que é a
    # divergência mais comum (o próprio exemplo do PRD: Vivobook 8GB ≠ 16GB).
    atributos_chave_por_categoria: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: {
            "notebook": ("capacidade",),
            "celular": ("capacidade",),
            "eletronicos": ("capacidade",),
        }
    )


def config_padrao() -> ConfigMatching:
    """Config pronta para uso com os padrões brasileiros."""
    return ConfigMatching()
