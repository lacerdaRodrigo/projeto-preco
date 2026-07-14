"""Normalização de títulos (§14, etapa 3) — deixa dois títulos comparáveis.

"Galaxy S25 Ultra Black 512 GB" e "Samsung Galaxy S25 Ultra 512GB Preto" viram
textos parecidos: minúsculas, sem acento, cor traduzida, unidade colada
(`512 gb`→`512gb`), ruído removido. Puro (só texto entra e sai), fácil de testar.
"""

from __future__ import annotations

import re
import unicodedata

from domain.matching.config import ConfigMatching

# Número seguido de unidade, com espaço opcional: "512 gb", "15,6 pol", '55"'.
_UNIDADE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(tb|gb|mb|kb|ml|l|kg|g|pol|polegadas|\")",
    re.IGNORECASE,
)
# Capacidade de armazenamento/memória: "512gb", "1tb" (já normalizados).
_CAPACIDADE = re.compile(r"\b(\d+)(gb|tb)\b")


def _sem_acento(texto: str) -> str:
    # Decompõe os acentos (á → a + ´) e joga fora as marcas.
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def normalizar(texto: str, config: ConfigMatching) -> str:
    """Canoniza um título para comparação (etapa 3 do §14)."""
    resultado = _sem_acento(texto.lower())

    # Cola número + unidade e padroniza polegadas: `512 gb`→`512gb`, `55"`→`55pol`.
    def _junta_unidade(m: re.Match[str]) -> str:
        numero = m.group(1).replace(",", ".")
        unidade = m.group(2).lower()
        if unidade in ('"', "polegadas"):
            unidade = "pol"
        return f"{numero}{unidade}"

    resultado = _UNIDADE.sub(_junta_unidade, resultado)

    # Traduz cores (black → preto) por palavra inteira.
    for ingles, portugues in config.cores.items():
        resultado = re.sub(rf"\b{re.escape(ingles)}\b", portugues, resultado)

    # Remove frases-ruído.
    for frase in config.ruido:
        resultado = resultado.replace(_sem_acento(frase), " ")

    # Tira pontuação restante e colapsa espaços.
    resultado = re.sub(r"[^\w\s]", " ", resultado)
    resultado = re.sub(r"\s+", " ", resultado).strip()
    return resultado


def tokenizar(texto_normalizado: str) -> set[str]:
    """Quebra o texto já normalizado em um conjunto de tokens (sem repetição)."""
    return set(texto_normalizado.split())


def extrair_capacidades(texto_normalizado: str) -> set[str]:
    """Extrai capacidades de armazenamento/memória: {"512gb", "1tb"}.

    Usado no portão de atributo-chave: se a oferta anuncia capacidades e nenhuma
    bate com a do produto, é sinal forte de "produto diferente" (§14).
    """
    return {f"{num}{unidade}" for num, unidade in _CAPACIDADE.findall(texto_normalizado)}
