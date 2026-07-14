"""Matcher determinístico e explicável (§14) — puro, vive no núcleo.

A IA (embeddings/LLM) entra depois como plug-in em `adapters/matching/`, atrás
deste mesmo contrato (par produto+oferta → ResultadoMatch), sem reescrever isto.
"""

from domain.matching.config import ConfigMatching, config_padrao
from domain.matching.matcher import casar
from domain.matching.normalizacao import normalizar
from domain.matching.resultado import Destino, Etapa, ResultadoMatch

__all__ = [
    "ConfigMatching",
    "Destino",
    "Etapa",
    "ResultadoMatch",
    "casar",
    "config_padrao",
    "normalizar",
]
