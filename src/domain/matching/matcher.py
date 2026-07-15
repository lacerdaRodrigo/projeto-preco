"""O matcher: decide se uma OfertaBruta é o meu Produto (§14).

Pipeline de portões, do sinal mais forte/barato ao mais fraco/caro (curto-
circuito): EAN → vetos → normaliza → atributo-chave → similaridade. Determinístico
e explicável (V1); a IA entra depois como plug-in atrás deste mesmo contrato.

Puro: só recebe entidades e config, devolve um ResultadoMatch. Sem I/O.
"""

from __future__ import annotations

import re
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

    # 4. Acessório/peça (§14): "Refil para Purificador PE12G", "Mouse p/ A15" —
    #    trazem o part-number mas NÃO são o produto. Veta antes do portão de modelo
    #    (senão o "PE12G" no refil seria confirmado como o purificador).
    acessorio = _checar_acessorio(referencia_norm, titulo_norm, cfg)
    if acessorio is not None:
        return acessorio

    # 5. Modelo (§5): o número do modelo é PORTÃO, não token fraco — senão "G17"
    #    passa por "G67" (muda 1 char, o resto igual). Part-number forte
    #    (A515-45-R2A3) presente → aceita na hora. Modelo de linha ("Moto G67")
    #    ausente → é OUTRO produto (descarta); presente → confirma, mas deixa a
    #    capacidade decidir o armazenamento antes de aceitar.
    decisao_modelo, modelo_confirmado = _checar_modelo(produto, titulo_norm, cfg)
    if decisao_modelo is not None:
        return decisao_modelo

    # 6. Atributo-chave (capacidade): divergiu → produto diferente (descarta).
    atributo = _checar_capacidade(produto, referencia_norm, titulo_norm, cfg)
    if atributo is not None:
        return atributo

    # 7. Modelo de linha confirmado e capacidade não divergiu → é o produto
    #    (modelo + specs conferem vale mais que a similaridade do título verboso).
    if modelo_confirmado:
        return ResultadoMatch(
            Destino.ACEITA, 0.9, Etapa.MODELO, f"modelo '{produto.modelo}' + specs conferem"
        )

    # 8. Similaridade textual — pontuador para o que restou ambíguo.
    score = _similaridade(referencia_norm, titulo_norm)
    return _classificar(score, cfg)


def _checar_modelo(
    produto: Produto, titulo_norm: str, cfg: ConfigMatching
) -> tuple[ResultadoMatch | None, bool]:
    """Confronta o modelo do produto com o título (§5).

    Devolve `(decisão, confirmado)`:
    - **decisão** não-nula = já resolveu (aceita part-number, ou descarta modelo
      diferente); o `casar` retorna na hora.
    - **confirmado** = o modelo de linha foi achado no título; o `casar` segue pra
      capacidade e, se ela não divergir, aceita.

    Duas naturezas de modelo:
    - **Part-number** (com hífen, ex.: A515-45-R2A3): é o SKU inteiro. Presente
      (como sequência) → aceita ~0.95. Ausente → não decide (a loja pode ter
      omitido o código comprido) — segue o pipeline.
    - **Linha** (ex.: "Moto G67"): o(s) token(s) com dígito ("g67") é a âncora e
      **quase sempre** está no título. Presente → confirma. Ausente → é OUTRO
      modelo (G17/G56...) → descarta.
    """
    modelo = produto.modelo
    if not modelo:
        return None, False
    modelo_norm = normalizar(modelo, cfg)  # "AF-32" → "af 32" (o hífen vira espaço)
    tokens_modelo = modelo_norm.split()
    if not tokens_modelo:
        return None, False

    if "-" in modelo:  # part-number forte: casa como sequência ("g67" ∉ "g675")
        padrao = r"\b" + r"\s+".join(re.escape(t) for t in tokens_modelo) + r"\b"
        if re.search(padrao, titulo_norm):
            return ResultadoMatch(
                Destino.ACEITA, 0.95, Etapa.MODELO, f"part-number '{modelo}' bate"
            ), True
        return None, False  # part-number omitido é comum → não decide

    # Linha: a âncora é o(s) token(s) com dígito. Sem número, não dá pra ancorar.
    nucleo = [t for t in tokens_modelo if any(c.isdigit() for c in t)]
    if not nucleo:
        return None, False
    if all(t in titulo_norm.split() for t in nucleo):
        return None, True  # confirmado; a capacidade decide o armazenamento
    return ResultadoMatch(
        Destino.DESCARTA, 0.0, Etapa.MODELO, f"modelo diferente (não achei '{modelo}')"
    ), False


def _checar_acessorio(
    referencia_norm: str, titulo_norm: str, cfg: ConfigMatching
) -> ResultadoMatch | None:
    """Oferta é acessório/peça do produto, não o produto → DESCARTA (§14).

    A palavra de acessório ("refil", "mouse", "kit") na oferta vetada só quando
    NÃO está no nome do meu produto — assim, se eu rastreio um refil, "refil" no
    meu nome desarma o veto e o refil certo passa. Compara por token inteiro.
    """
    tokens_oferta = set(titulo_norm.split())
    tokens_referencia = set(referencia_norm.split())
    for palavra in cfg.vetos_acessorio:
        if palavra in tokens_oferta and palavra not in tokens_referencia:
            return ResultadoMatch(
                Destino.DESCARTA, 0.0, Etapa.VETO, f"acessório/peça: '{palavra}'"
            )
    return None


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

    # 1. ARMAZENAMENTO (≥64GB): RAM e storage são ambos "GB"; um RAM igual ("4gb")
    #    mascarava storage diferente (o "Moto G67 128GB" passava por 256GB porque
    #    compartilhava a RAM). Se os dois anunciam storage e ele diverge → descarta.
    arm_produto = _armazenamento(caps_produto)
    arm_oferta = _armazenamento(caps_oferta)
    if arm_produto and arm_oferta and _em_gb(arm_produto) != _em_gb(arm_oferta):
        return ResultadoMatch(
            Destino.DESCARTA,
            0.0,
            Etapa.ATRIBUTO,
            f"capacidade (armazenamento) diverge: produto {arm_produto} "
            f"vs oferta {arm_oferta}",
        )

    # 2. Sem nenhuma capacidade em comum → produto diferente (pega divergência de
    #    RAM tipo 16GB ≠ 8GB, quando o produto declara a RAM como atributo-chave).
    if caps_produto and caps_oferta and caps_produto.isdisjoint(caps_oferta):
        return ResultadoMatch(
            Destino.DESCARTA,
            0.0,
            Etapa.ATRIBUTO,
            f"capacidade diverge: produto {sorted(caps_produto)} "
            f"vs oferta {sorted(caps_oferta)}",
        )
    return None


def _armazenamento(caps: set[str]) -> str | None:
    """A maior capacidade de ARMAZENAMENTO (≥64GB) do conjunto; None se não houver.

    Abaixo de 64GB é RAM — não serve pra separar storage 256 de 128 (e comparar
    RAM do produto com storage da oferta daria falso descarte).
    """
    storage = [c for c in caps if _em_gb(c) >= 64]
    return max(storage, key=_em_gb) if storage else None


def _em_gb(capacidade: str) -> int:
    """'512gb'→512, '1tb'→1024. Para comparar/ordenar capacidades na mesma unidade."""
    m = re.match(r"(\d+)(gb|tb)", capacidade)
    if not m:
        return 0
    return int(m.group(1)) * (1024 if m.group(2) == "tb" else 1)


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
