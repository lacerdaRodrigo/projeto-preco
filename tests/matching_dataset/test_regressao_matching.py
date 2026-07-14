"""Regressão do matcher a partir do dataset rotulado (§14, §23).

Cada par "é / não é o mesmo produto" vira um caso. Regra de ouro (PRD §14): o
**falso positivo é o pior erro** — casar produtos diferentes envenena preço,
ranking e alerta. Por isso:
  - "é o mesmo" (mesmo=true)  → tem de ACEITAR.
  - "não é"     (mesmo=false) → NÃO pode aceitar (fica em DESCARTA/REVISAR).

Cada erro real que você corrigir na vida real vira uma linha nova em `pares.json`
— o matcher melhora sem regredir. Este é o teste que protege o coração.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from domain import OfertaBruta, Produto
from domain.matching import Destino, casar

_PARES = json.loads((Path(__file__).parent / "pares.json").read_text(encoding="utf-8"))


def _monta_produto(dados: dict) -> Produto:
    return Produto(
        nome=dados["nome"],
        categoria=dados["categoria"],
        marca=dados.get("marca"),
        modelo=dados.get("modelo"),
        ean=dados.get("ean"),
        atributos=dados.get("atributos", {}),
        palavras_proibidas=tuple(dados.get("palavras_proibidas", [])),
        palavras_obrigatorias=tuple(dados.get("palavras_obrigatorias", [])),
    )


@pytest.mark.parametrize("par", _PARES, ids=[p["caso"] for p in _PARES])
def test_dataset_de_matching(par: dict):
    produto = _monta_produto(par["produto"])
    oferta = OfertaBruta(
        titulo=par["oferta_titulo"],
        preco=Decimal("100.00"),
        url="http://exemplo",
        ean=par.get("oferta_ean"),
    )

    resultado = casar(produto, oferta)

    if par["mesmo"]:
        assert resultado.destino is Destino.ACEITA, (
            f"deveria casar, mas deu {resultado.destino.value} "
            f"({resultado.motivo})"
        )
    else:
        # O que não pode acontecer NUNCA é o falso positivo.
        assert resultado.destino is not Destino.ACEITA, (
            f"falso positivo: casou indevidamente ({resultado.motivo})"
        )
