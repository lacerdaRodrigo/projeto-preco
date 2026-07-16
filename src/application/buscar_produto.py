"""Caso de uso BuscarProduto — o maestro da fatia vertical (§13).

Pega UM produto e coordena tudo até o resultado gravado: carrega o produto →
dispara os coletores em paralelo (resiliente por loja) → casa cada oferta →
calcula o preço final → grava idempotente. **Orquestra, não contém regra**: as
regras vivem no domain; aqui só a coreografia. Depende só de portas (Coletor,
Repositório) — zero import de adaptador, então roda igual local e na nuvem.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from application.buscadores import BuscadorDeCupons
from application.classificadores import ClassificadorIdentidade, VereditoIdentidade
from application.coletores import Coletor, ErroColetor, LojaIndisponivel
from application.repositorios import (
    RepositorioProduto,
    RepositorioSKU,
    RepositorioSnapshot,
    RepositorioCupom,
    RepositorioCashback,
)
from domain import (
    SKU,
    OfertaBruta,
    Produto,
    SnapshotPreco,
    calcular_preco_final,
)
from domain.cupom import Cupom, avaliar_melhor_cupom
from domain.cashback import Cashback, avaliar_melhor_cashback
from domain.matching import ConfigMatching, Destino, Etapa, ResultadoMatch, casar


class ProdutoInexistente(Exception):
    """O produto pedido não existe (ou não é da conta)."""


@dataclass(frozen=True)
class OfertaRankeada:
    """Uma oferta aceita, já com o preço final calculado (§16)."""

    loja: str
    titulo: str
    url: str
    preco_final: Decimal
    em_estoque: bool
    score_match: float
    # Decomposição do preço final (§16), pra "escadinha" de desconto na UI.
    preco_base: Decimal | None = None
    desconto_cupom: Decimal | None = None
    desconto_cashback: Decimal | None = None
    # Qual cupom/cashback incidiu (RN13). `cupom_confirmado=False` = cupom
    # DESCOBERTO (não digitado por você) → o desconto é "provável", não garantido.
    cupom_codigo: str | None = None
    cupom_confirmado: bool = True
    cashback_fonte: str | None = None
    # False = preço de vitrine (Google Shopping), não confirmado na página da loja.
    preco_confirmado: bool = True


@dataclass(frozen=True)
class OfertaTriada:
    """Uma oferta que NÃO entrou no ranking, com o porquê — pra ver o funil."""

    loja: str
    titulo: str
    motivo: str  # legível ("modelo diferente…", "acessório/peça: 'mouse'")
    etapa: str  # qual portão decidiu (modelo, atributo, veto, similaridade)
    score: float


@dataclass(frozen=True)
class ResultadoBusca:
    """O que o maestro devolve: o ranking + o que deu errado, transparente."""

    produto: Produto
    ranking: list[OfertaRankeada]  # por preço final; em estoque primeiro
    em_revisao: int  # ofertas 0.6–0.85 (foram pra fila, não pro ranking)
    descartadas: int
    lojas_indisponiveis: list[str]  # falha transitória → dá pra tentar de novo
    lojas_degradadas: list[str]  # coletor quebrado (RN12) → não gravou nada
    # O funil visível: cada oferta que ficou de fora, com o motivo (§14).
    em_revisao_itens: list[OfertaTriada] = field(default_factory=list)
    descartadas_itens: list[OfertaTriada] = field(default_factory=list)


@dataclass(frozen=True)
class _Coleta:
    """Resultado interno de UMA loja (isola a falha dela — RN08)."""

    coletor: Coletor
    ofertas: list[OfertaBruta]
    status: str  # "ok" | "indisponivel" | "degradado"


@dataclass(frozen=True)
class _Candidata:
    """Uma oferta que casou, esperando disputar a vaga de 'melhor da loja'."""

    coletor: Coletor
    oferta: OfertaBruta
    score: float
    loja_origem: str  # a loja que dá identidade ao SKU (source, ou nome do coletor)


class BuscarProduto:
    def __init__(
        self,
        coletores: Sequence[Coletor],
        repo_produto: RepositorioProduto,
        repo_sku: RepositorioSKU,
        repo_snapshot: RepositorioSnapshot,
        repo_cupom: RepositorioCupom | None = None,
        repo_cashback: RepositorioCashback | None = None,
        config_matching: ConfigMatching | None = None,
        classificador: ClassificadorIdentidade | None = None,
        buscador_cupons: BuscadorDeCupons | None = None,
        ttl_cupons: timedelta = timedelta(hours=24),
        agora: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._coletores = coletores
        self._produtos = repo_produto
        self._skus = repo_sku
        self._snapshots = repo_snapshot
        # Cupom/cashback são opcionais: sem os repositórios, o preço final é só
        # item + frete (a "carteira" não altera nada). A API os injeta sempre.
        self._cupons = repo_cupom
        self._cashbacks = repo_cashback
        self._config = config_matching
        # O juiz de identidade (IA). Ausente → matching 100% determinístico.
        self._classificador = classificador
        # Descoberta automática de cupons (Serper+LLM). Ausente → só carteira manual.
        self._buscador_cupons = buscador_cupons
        self._ttl_cupons = ttl_cupons  # cache: não redescobre a loja dentro do TTL
        self._agora = agora  # injetável para testes deterministas

    async def executar(
        self, 
        produto_id: int, 
        conta_id: int, 
        cep: str | None = None,
        condicoes_usuario: tuple[str, ...] = ()
    ) -> ResultadoBusca:
        # 1. Carrega o produto (já escopado por conta).
        produto = self._produtos.obter(produto_id, conta_id)
        if produto is None or produto.id is None:
            raise ProdutoInexistente(f"produto {produto_id} não encontrado na conta")

        # 2. Fan-out: todas as lojas em paralelo, cada falha isolada (RN08).
        descricao = _descricao_de(produto)
        coletas = await asyncio.gather(
            *(self._coletar_seguro(c, descricao, cep) for c in self._coletores)
        )

        # 3. Junta todas as ofertas (com a loja de origem). Casa cada uma pelo
        #    determinístico — o PISO/fallback — e, em UMA chamada, deixa a IA
        #    arbitrar a identidade (mesmo produto?). A IA manda na zona ambígua;
        #    os sinais certos (EAN bate, veto do usuário/acessório) o determinístico
        #    ainda decide. Sem IA, tudo cai no determinístico de sempre.
        itens = [
            (coleta.coletor, oferta, _loja_de_origem(coleta.coletor, oferta))
            for coleta in coletas
            for oferta in coleta.ofertas
        ]
        ofertas = [oferta for _, oferta, _ in itens]
        decisoes = [casar(produto, oferta, self._config) for oferta in ofertas]
        vereditos = await self._vereditos_ia(produto, ofertas, decisoes)

        # As aceitas vão pra um balde POR LOJA DE ORIGEM — o SKU é 1 por loja
        # (RN01). Um agregador (Google Shopping) traz N lojas numa busca só, então
        # a identidade vem da loja de origem, não do coletor.
        aceitas: dict[tuple[int, str], list[_Candidata]] = {}
        em_revisao_itens: list[OfertaTriada] = []
        descartadas_itens: list[OfertaTriada] = []
        for (coletor, oferta, loja_origem), decisao, veredito in zip(
            itens, decisoes, vereditos
        ):
            destino, score, motivo, etapa = _decidir(decisao, veredito)
            if destino is Destino.REVISAR:
                em_revisao_itens.append(
                    OfertaTriada(loja_origem, oferta.titulo, motivo, etapa, round(score, 4))
                )
            elif destino is Destino.DESCARTA:
                descartadas_itens.append(
                    OfertaTriada(loja_origem, oferta.titulo, motivo, etapa, round(score, 4))
                )
            else:
                candidata = _Candidata(coletor, oferta, score, loja_origem)
                chave = (coletor.loja_id, loja_origem)
                aceitas.setdefault(chave, []).append(candidata)

        # 4–5. Por loja, escolhe a MELHOR oferta e grava (SKU + snapshot idempotente).
        data_hoje = self._agora().date()
        ranking = []
        for (loja_id, loja_origem), candidatas in aceitas.items():
            await self._garantir_cupons(loja_origem)  # descobre se o cache expirou
            cupons = self._cupons.ativos_por_loja(loja_origem) if self._cupons else []
            cashbacks = (
                self._cashbacks.ativos_por_loja(loja_origem) if self._cashbacks else []
            )
            # Códigos descobertos: o que NÃO estiver aqui é manual (confiável).
            descobertos = (
                {d.cupom.codigo for d in self._cupons.descobertos_por_loja(loja_origem)}
                if self._cupons else set()
            )
            melhor_cand = _melhor(candidatas, cupons, cashbacks, data_hoje, condicoes_usuario)
            ranking.append(self._persistir(
                produto_id, melhor_cand, conta_id, cupons, cashbacks,
                data_hoje, condicoes_usuario, descobertos,
            ))

        # Ranking: em estoque primeiro, depois pelo menor preço final (§16).
        ranking.sort(key=lambda o: (not o.em_estoque, o.preco_final))

        # Funil sem repetição: a mesma loja+título aparecia N vezes (o agregador
        # devolve o produto em várias posições) — mostra uma só.
        em_revisao_itens = _sem_repetir(em_revisao_itens)
        descartadas_itens = _sem_repetir(descartadas_itens)

        return ResultadoBusca(
            produto=produto,
            ranking=ranking,
            em_revisao=len(em_revisao_itens),
            descartadas=len(descartadas_itens),
            lojas_indisponiveis=[c.coletor.nome for c in coletas if c.status == "indisponivel"],
            lojas_degradadas=[c.coletor.nome for c in coletas if c.status == "degradado"],
            em_revisao_itens=em_revisao_itens,
            descartadas_itens=descartadas_itens,
        )

    async def _vereditos_ia(
        self,
        produto: Produto,
        ofertas: list[OfertaBruta],
        decisoes: list[ResultadoMatch],
    ) -> list[VereditoIdentidade | None]:
        """A IA classifica, em UMA chamada, só as ofertas da ZONA AMBÍGUA — as que
        o determinístico resolveu por EAN ou veto ficam de fora (a IA não muda
        isso e mandá-las só engorda o lote). Roda fora do event loop (adaptador
        síncrono). Sem classificador → sem opinião (tudo `None`)."""
        vereditos: list[VereditoIdentidade | None] = [None] * len(ofertas)
        if self._classificador is None:
            return vereditos
        alvos = [
            (i, oferta)
            for i, (oferta, decisao) in enumerate(zip(ofertas, decisoes))
            if decisao.etapa not in (Etapa.EAN, Etapa.VETO)
        ]
        if not alvos:
            return vereditos
        saida = await asyncio.to_thread(
            self._classificador.classificar, produto, [oferta for _, oferta in alvos]
        )
        if len(saida) != len(alvos):  # guarda: contrato garante alinhamento
            return vereditos
        for (i, _), veredito in zip(alvos, saida):
            vereditos[i] = veredito
        return vereditos

    async def _coletar_seguro(
        self, coletor: Coletor, descricao: str, cep: str | None
    ) -> _Coleta:
        """Busca numa loja e traduz falha em status — nunca deixa vazar (RN08)."""
        try:
            ofertas = await coletor.buscar(descricao, cep)
            return _Coleta(coletor, ofertas, "ok")
        except LojaIndisponivel:
            return _Coleta(coletor, [], "indisponivel")  # transitório: retry depois
        except ErroColetor:
            # Inclui ColetorQuebrado (RN12): não grava nada dessa loja.
            return _Coleta(coletor, [], "degradado")

    async def _garantir_cupons(self, loja: str) -> None:
        """Descobre e grava os cupons da loja, com CACHE por TTL — não redescobre
        se a última descoberta é recente (economiza Serper/LLM entre buscas). Sem
        buscador/repositório, não faz nada (só a carteira manual vale)."""
        if self._buscador_cupons is None or self._cupons is None:
            return
        ultimo = self._cupons.visto_em(loja)
        if ultimo is not None and self._agora() - ultimo < self._ttl_cupons:
            return  # cache fresco
        descobertos = await self._buscador_cupons.buscar(loja)
        quando = self._agora()
        for d in descobertos:
            self._cupons.salvar_descoberto(loja, d, quando)

    def _persistir(
        self,
        produto_id: int,
        candidata: _Candidata,
        conta_id: int,
        cupons: list[Cupom],
        cashbacks: list[Cashback],
        data_atual: date,
        condicoes_usuario: tuple[str, ...],
        descobertos: set[str],
    ) -> OfertaRankeada:
        coletor, oferta = candidata.coletor, candidata.oferta
        sku = self._skus.salvar_ou_atualizar(
            SKU(
                produto_id=produto_id,
                loja_id=coletor.loja_id,
                loja_origem=candidata.loja_origem,
                url=oferta.url,
                titulo_original=oferta.titulo,
                score_match=candidata.score,
                vendedor_oficial=oferta.vendedor_oficial,
            ),
            conta_id,
        )
        if sku.id is None:  # o repositório sempre preenche; guarda de sanidade
            raise RuntimeError("repositório não devolveu o id do SKU")
        # Grava o snapshot só se algo mudou (RN11) — rodar 2x não duplica.
        self._snapshots.salvar_snapshot_se_mudou(
            SnapshotPreco(
                sku_id=sku.id,
                preco=oferta.preco,
                preco_avista=oferta.preco_avista,
                desconto_pix=oferta.desconto_pix,
                frete=oferta.frete,
                frete_cotado=oferta.frete_cotado,
                prazo_dias=oferta.prazo_dias,
                parcelas=oferta.parcelas,
                sem_juros=oferta.sem_juros,
                em_estoque=oferta.em_estoque,
                coletado_em=self._agora(),
            ),
            conta_id,
        )
        final, base, desc_cupom, desc_cashback, cupom_ap, cashback_ap = _decompor(
            oferta, cupons, cashbacks, data_atual, condicoes_usuario
        )
        cupom_codigo = cupom_ap.codigo if cupom_ap else None
        return OfertaRankeada(
            loja=candidata.loja_origem,
            titulo=oferta.titulo,
            url=oferta.url,
            preco_final=final,
            em_estoque=oferta.em_estoque,
            score_match=candidata.score,
            preco_base=base,
            desconto_cupom=desc_cupom if desc_cupom > 0 else None,
            desconto_cashback=desc_cashback if desc_cashback > 0 else None,
            cupom_codigo=cupom_codigo,
            # Confirmado = manual (você digitou); descoberto → "provável", marcado.
            cupom_confirmado=cupom_codigo is not None and cupom_codigo not in descobertos,
            cashback_fonte=cashback_ap.fonte if cashback_ap else None,
            preco_confirmado=oferta.preco_confirmado,
        )


def _loja_de_origem(coletor: Coletor, oferta: OfertaBruta) -> str:
    """Qual loja dá identidade ao SKU desta oferta.

    Coletor de uma loja só → o nome dele (comportamento de sempre). Agregador
    (Google Shopping) → a loja de origem de cada oferta (`vendedor`/source), pra
    N lojas de uma busca virarem N SKUs, não colapsarem num só. Ver PLANO passo 5.
    """
    if getattr(coletor, "agrega_lojas", False) and oferta.vendedor:
        return oferta.vendedor
    return coletor.nome


def _decidir(
    decisao: ResultadoMatch, veredito: VereditoIdentidade | None
) -> tuple[Destino, float, str, str]:
    """Combina o determinístico com a IA → (destino, score, motivo, etapa).

    Sinais CERTOS o determinístico mantém: EAN bate (é o produto) e vetos (palavra
    proibida/obrigatória do usuário, ou acessório/peça). Na zona ambígua de
    identidade (modelo/capacidade/similaridade), a IA arbitra quando tem opinião;
    sem IA (ou sem opinião), vale a decisão determinística — o piso de sempre.
    """
    if decisao.etapa in (Etapa.EAN, Etapa.VETO):
        return decisao.destino, decisao.score, decisao.motivo, decisao.etapa.value
    if veredito is not None:
        if veredito.mesmo:
            return Destino.ACEITA, max(decisao.score, 0.9), f"IA: {veredito.motivo}", "ia"
        return Destino.DESCARTA, 0.0, f"IA: {veredito.motivo}", "ia"
    return decisao.destino, decisao.score, decisao.motivo, decisao.etapa.value


def _sem_repetir(itens: list[OfertaTriada]) -> list[OfertaTriada]:
    """Tira duplicatas do funil pela chave loja+título (o agregador repete)."""
    vistos: set[tuple[str, str]] = set()
    unicos: list[OfertaTriada] = []
    for item in itens:
        chave = (item.loja, item.titulo)
        if chave in vistos:
            continue
        vistos.add(chave)
        unicos.append(item)
    return unicos


def _melhor(
    candidatas: list[_Candidata],
    cupons: list[Cupom],
    cashbacks: list[Cashback],
    data_atual: date,
    condicoes_usuario: tuple[str, ...]
) -> _Candidata:
    """A melhor oferta de uma loja: em estoque primeiro, menor preço final,
    empate desfeito pelo maior score de matching."""
    return min(
        candidatas,
        key=lambda c: (
            not c.oferta.em_estoque, 
            _preco_final_de(c.oferta, cupons, cashbacks, data_atual, condicoes_usuario), 
            -c.score
        ),
    )


def _decompor(
    oferta: OfertaBruta,
    cupons: list[Cupom],
    cashbacks: list[Cashback],
    data_atual: date,
    condicoes_usuario: tuple[str, ...],
) -> tuple[Decimal, Decimal, Decimal, Decimal, Cupom | None, Cashback | None]:
    """Decompõe o preço final (§16): (final, base, desc_cupom, desc_cashback,
    cupom_aplicado, cashback_aplicado).

    base = preço à vista (ou o preço cheio). Aplica o MELHOR cupom válido, depois o
    MELHOR cashback elegível sobre o valor já com cupom. Devolve também QUAL cupom/
    cashback incidiu (RN13, pra escadinha nomear na UI)."""
    base = oferta.preco_avista if oferta.preco_avista is not None else oferta.preco
    cupom, desconto_cupom = avaliar_melhor_cupom(cupons, base, data_atual)

    pos_cupom = base - desconto_cupom
    if pos_cupom < Decimal("0"):
        pos_cupom = Decimal("0")

    cashback, valor_cashback = avaliar_melhor_cashback(
        cashbacks, pos_cupom, list(condicoes_usuario)
    )

    final = calcular_preco_final(
        preco=oferta.preco,
        preco_avista=oferta.preco_avista,
        frete=oferta.frete,
        frete_cotado=oferta.frete_cotado,
        desconto_cupom=desconto_cupom,
        cashback=valor_cashback,
    )
    return final, base, desconto_cupom, valor_cashback, cupom, cashback


def _preco_final_de(
    oferta: OfertaBruta,
    cupons: list[Cupom],
    cashbacks: list[Cashback],
    data_atual: date,
    condicoes_usuario: tuple[str, ...],
) -> Decimal:
    """Só o preço final (§16) — o desempate do ranking usa isto."""
    return _decompor(oferta, cupons, cashbacks, data_atual, condicoes_usuario)[0]


# Categorias onde marca+modelo NÃO basta pra desambiguar: um notebook "Asus A15"
# casa com dezenas de configs. Aí a query leva também o discriminador forte (GPU)
# — sem virar a string verbosa inteira, que over-constringe.
_CATEGORIAS_COM_SPEC_NA_BUSCA = frozenset({"notebook"})
# Ordem de specs a acrescentar na busca (a GPU separa variantes de gamer melhor
# que RAM/armazenamento; o armazenamento entra como reforço).
_SPECS_NA_BUSCA = ("gpu", "armazenamento")


def _descricao_de(produto: Produto) -> str:
    """Monta o texto de busca (§4).

    Com âncora (marca + modelo), consulta ENXUTA por ela ("Motorola Moto G67") —
    a string verbosa inteira over-constringe: nenhuma loja titula igual, então
    buscar o título todo devolve pouco ou nada. Em categorias onde o modelo é uma
    série ambígua (notebook: "Asus A15"), acrescenta o discriminador forte (GPU)
    pra achar a config certa. Sem âncora, cai no nome completo.
    """
    if produto.marca and produto.modelo:
        base = f"{produto.marca} {produto.modelo}"
        extra = _discriminadores(produto)
        return f"{base} {extra}".strip() if extra else base
    partes = [produto.nome, produto.marca or "", produto.modelo or ""]
    return " ".join(p for p in partes if p).strip()


def _discriminadores(produto: Produto) -> str:
    """Specs-chave que entram na busca pra desambiguar (só nas categorias que
    precisam; só o que o extrator gravou em `atributos`)."""
    if produto.categoria not in _CATEGORIAS_COM_SPEC_NA_BUSCA:
        return ""
    return " ".join(
        produto.atributos[chave]
        for chave in _SPECS_NA_BUSCA
        if produto.atributos.get(chave)
    )
