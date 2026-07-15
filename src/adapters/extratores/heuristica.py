"""Extrator heurístico (PLANO §4): título → {marca, modelo/part-number, categoria}.

Determinístico (regex + dicionários), sem I/O e sem LLM (V1). A ideia é tirar a
**âncora** do título que o Rodrigo cola — marca + modelo — pra o matching ficar
cirúrgico (é o que separa "Moto G67" de "Moto G85") e pra a busca consultar pela
âncora, não pela string verbosa inteira.

Conservador de propósito: na dúvida devolve `None` num campo, nunca um palpite
errado (dado de entrada é responsabilidade do usuário; aqui a gente só reconhece
o que dá pra reconhecer com segurança). Marcas/categorias são CONFIG (dicionário),
fáceis de estender sem mexer na lógica (§14).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Marcas conhecidas (chave normalizada → nome de exibição). Lista viva: estender
# é 1 linha. Só marcas de uma palavra (multi-palavra fica pra depois).
_MARCAS: dict[str, str] = {
    "motorola": "Motorola", "samsung": "Samsung", "apple": "Apple", "xiaomi": "Xiaomi",
    "redmi": "Redmi", "poco": "Poco", "realme": "Realme", "nokia": "Nokia",
    "lg": "LG", "acer": "Acer", "dell": "Dell", "lenovo": "Lenovo", "asus": "Asus",
    "hp": "HP", "positivo": "Positivo", "multilaser": "Multilaser", "gigabyte": "Gigabyte",
    "philco": "Philco", "britania": "Britânia", "mondial": "Mondial", "arno": "Arno",
    "electrolux": "Electrolux", "brastemp": "Brastemp", "consul": "Consul", "midea": "Midea",
    "panasonic": "Panasonic", "philips": "Philips", "sony": "Sony", "jbl": "JBL",
    "amazon": "Amazon", "tcl": "TCL", "aoc": "AOC", "gopro": "GoPro", "oster": "Oster",
    "madesa": "Madesa", "politorno": "Politorno", "kappesberg": "Kappesberg",
    "itatiaia": "Itatiaia", "bertolini": "Bertolini",
    "caloi": "Caloi", "gts": "GTS", "houston": "Houston", "oggi": "Oggi", "sense": "Sense",
}

# Palavras que costumam nomear a LINHA logo antes do número do modelo ("Moto G67",
# "Galaxy S24", "Aspire A515..."). Se aparecerem coladas ao token, entram no modelo.
_LINHAS: frozenset[str] = frozenset(
    {"moto", "galaxy", "redmi", "poco", "aspire", "ideapad", "inspiron", "vivobook",
     "zenbook", "nitro", "predator", "edge", "note", "book",
     # linhas de notebook/gamer (o número sozinho — "a15", "g15" — não identifica).
     "tuf", "gaming", "dash", "rog", "strix", "victus", "omen", "pavilion",
     "legion", "thinkpad", "katana", "cyborg", "modern", "swift"}
)

# Categoria → nome que o matcher já configura (só essas têm portão de capacidade).
# Primeira palavra-chave achada no título vence.
_CATEGORIAS: dict[str, str] = {
    "smartphone": "celular", "celular": "celular", "iphone": "celular",
    "notebook": "notebook", "laptop": "notebook", "ultrabook": "notebook",
    "tv": "eletronicos", "televisor": "eletronicos", "monitor": "eletronicos",
    "tablet": "eletronicos", "fone": "eletronicos", "headset": "eletronicos",
    "smartwatch": "eletronicos",
}

# Part-number com hífen (Acer "A515-45-R2A3"): grupos alfanuméricos ligados por
# hífen, com pelo menos uma letra e um dígito no todo.
_PART_NUMBER = re.compile(r"\b[a-z0-9]+(?:-[a-z0-9]+)+\b", re.IGNORECASE)
# Token de modelo curto: letra(s) + dígitos ("g67", "s24", "a515"). Letra PRIMEIRO
# de propósito — assim specs "256gb"/"5g"/"120hz" (dígito primeiro) não entram.
_MODELO_TOKEN = re.compile(r"^[a-z]{1,4}\d{2,4}[a-z]?$")
# Prefixos de letra que são UNIDADE, não modelo (evita pegar spec como modelo).
_UNIDADES = frozenset({"gb", "tb", "mb", "hz", "mp", "kg", "ml", "cm", "mm", "mah", "w", "v", "k"})


@dataclass(frozen=True)
class Identidade:
    """A âncora reconhecida no título. Campos que não deram → None."""

    marca: str | None = None
    modelo: str | None = None
    categoria: str | None = None


def extrair_identidade(titulo: str) -> Identidade:
    """Título → âncora (marca, modelo, categoria). Puro; campos incertos = None."""
    norm = _normalizar(titulo)
    tokens = norm.split()
    return Identidade(
        marca=_extrair_marca(tokens),
        modelo=_extrair_modelo(norm, tokens),
        categoria=_extrair_categoria(tokens),
    )


def _normalizar(texto: str) -> str:
    """minúsculas, sem acento, pontuação (menos hífen) vira espaço."""
    decomposto = unicodedata.normalize("NFKD", texto.lower())
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s-]", " ", sem_acento)).strip()


def _extrair_marca(tokens: list[str]) -> str | None:
    """A marca conhecida que aparece mais cedo no título (a mais provável)."""
    for token in tokens:
        nome = _MARCAS.get(token.strip("-"))
        if nome:
            return nome
    return None


def _extrair_categoria(tokens: list[str]) -> str | None:
    """A 1ª palavra-chave de categoria que o matcher configura. Senão, None."""
    for token in tokens:
        categoria = _CATEGORIAS.get(token)
        if categoria:
            return categoria
    return None


def _extrair_modelo(norm: str, tokens: list[str]) -> str | None:
    """Part-number com hífen (forte) ou token de modelo (com a linha, se houver)."""
    # 1. Part-number com hífen tem prioridade (o mais específico).
    for achado in _PART_NUMBER.finditer(norm):
        pn = achado.group()
        if "-" in pn and re.search(r"[a-z]", pn) and re.search(r"\d", pn) and len(pn) >= 5:
            return pn.upper()

    # 2. Token de modelo curto ("g67"); junta a linha anterior ("moto g67").
    for i, token in enumerate(tokens):
        letras = re.match(r"[a-z]+", token)
        if _MODELO_TOKEN.match(token) and (not letras or letras.group() not in _UNIDADES):
            anterior = tokens[i - 1] if i > 0 else ""
            if anterior in _LINHAS:
                return f"{anterior.capitalize()} {token.upper()}"
            return token.upper()
    return None
