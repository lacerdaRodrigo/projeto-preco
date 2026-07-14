"""O matcher: decide se uma OfertaBruta é o meu Produto (§14).

Pipeline de portões, do sinal mais forte/barato ao mais fraco/caro (curto-
circuito): EAN → vetos → normaliza → atributo-chave → similaridade. Determinístico
e explicável (V1); a IA entra depois como plug-in atrás deste mesmo contrato.

Puro: só recebe entidades e config, devolve um ResultadoMatch. Sem I/O.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from domain.matching.config import ConfigMatching, config_padrao
from domain.matching.normalizacao import (
    extrair_capacidades,
    normalizar,
    tokenizar,
)
from domain.matching.resultado import Destino, Etapa, ResultadoMatch
from domain.oferta import OfertaBruta
from domain.produto import Produto


def casar(
    produto: Produto,
    oferta: OfertaBruta,
    config: ConfigMatching | None = None,
) -> ResultadoMatch:
    """Roda o pipeline e devolve a decisão + o porquê (§14)."""
    cfg = config or config_padrao()
    titulo_norm = normalizar(oferta.titulo, cfg)

    # 1. EAN — portão forte. Bateu, acabou (score 1.0). É a melhor chave (§14).
    if produto.ean and oferta.ean and produto.ean == oferta.ean:
        return ResultadoMatch(Destino.ACEITA, 1.0, Etapa.EAN, "EAN bate")

    # 2. Vetos — baratos, cortam a maior parte do lixo cedo.
    veto = _checar_vetos(produto, titulo_norm, cfg)
    if veto is not None:
        return veto

    # 3. Normalização do produto (etapa 3) — texto de referência para comparar.
    referencia_norm = normalizar(_texto_de_referencia(produto), cfg)

    # 4. Atributo-chave (capacidade): divergiu → produto diferente (descarta).
    atributo = _checar_capacidade(produto, referencia_norm, titulo_norm, cfg)
    if atributo is not None:
        return atributo

    # 5. Similaridade textual — pontuador para o que restou ambíguo.
    score = _similaridade(referencia_norm, titulo_norm)
    return _classificar(score, cfg)


def _checar_vetos(
    produto: Produto, titulo_norm: str, cfg: ConfigMatching
) -> ResultadoMatch | None:
    """Palavra proibida presente ou obrigatória ausente → DESCARTA (§14)."""
    for proibida in produto.palavras_proibidas:
        alvo = normalizar(proibida, cfg)
        if alvo and alvo in titulo_norm:
            return ResultadoMatch(
                Destino.DESCARTA, 0.0, Etapa.VETO, f"palavra proibida: '{proibida}'"
            )
    for obrigatoria in produto.palavras_obrigatorias:
        alvo = normalizar(obrigatoria, cfg)
        if alvo and alvo not in titulo_norm:
            return ResultadoMatch(
                Destino.DESCARTA,
                0.0,
                Etapa.VETO,
                f"faltou palavra obrigatória: '{obrigatoria}'",
            )
    return None


def _checar_capacidade(
    produto: Produto, referencia_norm: str, titulo_norm: str, cfg: ConfigMatching
) -> ResultadoMatch | None:
    """Se a categoria usa capacidade como atributo-chave e ela diverge, descarta."""
    chaves = cfg.atributos_chave_por_categoria.get(produto.categoria, ())
    if "capacidade" not in chaves:
        return None

    # Capacidade do produto: do texto de referência + dos atributos declarados.
    caps_produto = extrair_capacidades(referencia_norm)
    for valor in produto.atributos.values():
        caps_produto |= extrair_capacidades(normalizar(valor, cfg))

    caps_oferta = extrair_capacidades(titulo_norm)

    # Só julga quando os dois lados anunciam capacidade e não têm nenhuma em comum.
    if caps_produto and caps_oferta and caps_produto.isdisjoint(caps_oferta):
        return ResultadoMatch(
            Destino.DESCARTA,
            0.0,
            Etapa.ATRIBUTO,
            f"capacidade diverge: produto {sorted(caps_produto)} "
            f"vs oferta {sorted(caps_oferta)}",
        )
    return None


def _similaridade(referencia_norm: str, titulo_norm: str) -> float:
    """Similaridade textual estilo *token-set ratio* (§14), com `difflib` (stdlib).

    A ideia: compara três textos montados dos tokens — só a interseção, a
    interseção + o que sobra de cada lado — e fica com o maior parecido. Assim,
    quando a identidade do produto está *contida* num título verboso (cheio de
    specs e ruído), o score continua alto, em vez de ser punido pelo excesso.
    1.0 = a referência cabe inteira no título; perto de 0 = nada em comum.
    """
    a = tokenizar(referencia_norm)
    b = tokenizar(titulo_norm)
    if not a or not b:
        return 0.0

    intersecao = sorted(a & b)
    so_na_referencia = sorted(a - b)
    so_no_titulo = sorted(b - a)

    t0 = " ".join(intersecao)
    t1 = " ".join(intersecao + so_na_referencia)
    t2 = " ".join(intersecao + so_no_titulo)

    return max(_ratio(t0, t1), _ratio(t0, t2), _ratio(t1, t2))


def _ratio(x: str, y: str) -> float:
    """Quão parecidas são duas strings, em [0, 1] (0 se ambas vazias)."""
    if not x and not y:
        return 0.0
    return SequenceMatcher(None, x, y).ratio()


def _classificar(score: float, cfg: ConfigMatching) -> ResultadoMatch:
    """Traduz o score nos três destinos do RN04."""
    motivo = f"similaridade textual {score:.2f}"
    if score >= cfg.limiar_aceita:
        destino = Destino.ACEITA
    elif score >= cfg.limiar_revisar:
        destino = Destino.REVISAR
    else:
        destino = Destino.DESCARTA
    return ResultadoMatch(destino, round(score, 4), Etapa.SIMILARIDADE, motivo)


def _texto_de_referencia(produto: Produto) -> str:
    """Junta os campos que identificam o produto num texto comparável ao título."""
    partes = [
        produto.nome,
        produto.marca or "",
        produto.modelo or "",
        produto.cor or "",
        *produto.modelos_equivalentes,
        *produto.atributos.values(),
    ]
    return " ".join(p for p in partes if p)
