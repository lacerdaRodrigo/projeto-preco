"""A fórmula do PREÇO FINAL à vista — o coração da comparação (PRD §16).

    preço_final = base_à_vista − cupom + frete − cashback

O ranking usa ISTO, nunca o preço de vitrine (RN02, RN10). A **ordem** importa
e está congelada aqui. No V1 ainda não coletamos cupom nem cashback, então eles
entram como zero — mas a ordem já os prevê para a Fase 2 não mexer no núcleo.

Função pura: recebe números, devolve número. Sem rede/banco/objeto de banco —
por isso é fácil e barata de testar (e é o que mais testamos).
"""

from __future__ import annotations

from decimal import Decimal

from domain.dinheiro import ZERO, dinheiro


def calcular_preco_final(
    *,
    preco: Decimal,
    preco_avista: Decimal | None = None,
    frete: Decimal | None = None,
    frete_cotado: bool = False,
    desconto_cupom: Decimal | None = None,
    cashback: Decimal | None = None,
) -> Decimal:
    """Calcula o preço final à vista de UMA oferta, na ordem do §16.

    Argumentos só por nome (``*``) para a chamada ficar legível e não trocar
    frete com cupom sem querer.

    Passos (PRD §16):
      1. **Base** = preço à vista, se houver; senão o preço normal.
      2. **Cupom** desconta da base (não deixa virar negativo).
      3. **Cashback** incide sobre o pós-cupom (não sobre o frete).
      4. **Frete** só soma se foi cotado (RN09) — sem CEP, compara sem frete.
      5. ``preço_final = pós_cupom + frete − cashback``.
    """
    # 1. Base: o à vista (PIX/boleto) vence a vitrine quando existe.
    base = preco_avista if preco_avista is not None else preco

    # 2. Cupom sobre a base. Cupom maior que o produto não vira preço negativo.
    pos_cupom = base - (desconto_cupom or ZERO)
    if pos_cupom < ZERO:
        pos_cupom = ZERO

    # 3. Cashback: dinheiro recebido depois, abatido do custo líquido (§16).
    valor_cashback = cashback or ZERO

    # 4. Frete só conta se cotado para um CEP (RN09).
    valor_frete = (frete or ZERO) if frete_cotado else ZERO

    # 5. Junta tudo e devolve já arredondado em centavos.
    return dinheiro(pos_cupom + valor_frete - valor_cashback)
