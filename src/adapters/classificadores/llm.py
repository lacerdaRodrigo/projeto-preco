"""Classificador de identidade por LLM (NVIDIA, endpoint OpenAI-compatível).

O juiz do matching: dado o produto-alvo e a lista de ofertas de uma busca, decide
em UMA chamada quais são o MESMO produto (mesma marca, linha, modelo e geração) e
quais não são — 'Buds' ≠ 'Buds 2', 'Wave 200' ≠ 'Wave Buds', capa/refil ≠ o
produto. Sem regra por categoria no backend: a IA entende a diferença sozinha.

Fronteiras (CLAUDE.md): rede isolada aqui; o núcleo não importa isto. O dado que
volta do modelo é **não-confiável** — parse defensivo, valida índice e tipo,
nunca crava palpite. Qualquer falha (sem chave, HTTP≠200, JSON inválido, timeout)
→ vereditos `None` (o chamador mantém a decisão determinística; degradação limpa,
RN12). Segredo (a chave) nunca é logado. Só recebe título de loja (dado público),
nunca PII.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import httpx

from application.classificadores import VereditoIdentidade
from domain.oferta import OfertaBruta
from domain.produto import Produto

_SISTEMA = (
    "Você é um juiz de correspondência de produtos de e-commerce brasileiro. "
    "Recebe um produto ALVO e uma lista de OFERTAS numeradas. Para cada oferta, "
    "decida se é o MESMO produto que o alvo. "
    "Compare SOMENTE três coisas: MARCA + LINHA + MODELO/número. "
    "IGNORE COMPLETAMENTE todo o resto — cor, capacidade de bateria, horas de "
    "reprodução, microfone, 'sem fio', 'bluetooth', 'true wireless', estojo, "
    "quantidade, voltagem: NADA disso decide, são só specs/descrição. "
    "Variações de ESCRITA do mesmo modelo são IGUAIS (true): 'Wave 200 Tws' = "
    "'Wave 200TWS' = 'Wave 200'; 'Moto G67' = 'Moto G 67'. "
    "É false SOMENTE quando a marca, a linha ou o número/modelo são realmente "
    "OUTROS: marca diferente (alvo 'JBL' vs 'KaBuM' vs 'Beatsound' = false); "
    "linha diferente ('Wave' ≠ 'Vibe' ≠ 'Beam' ≠ 'Endurance'); número/geração "
    "diferente ('Wave 200' ≠ 'Wave Buds' ≠ 'Wave Buds 2' ≠ 'Wave Flex'; 'G67' ≠ "
    "'G17'); ou é acessório/capa/película/refil/peça. "
    "Exemplos — ALVO 'JBL Wave 200TWS': 'JBL Wave 200 Tws Preto'=true; 'JBL Wave "
    "200tws 5h Bateria Branco'=true; 'Fone Jbl Wave 200 até 20h'=true; 'JBL Wave "
    "Buds'=false; 'JBL Vibe 200tws'=false; 'JBL Wave Beam 2'=false; 'KaBuM TECH "
    "500'=false. ALVO 'JBL Wave Buds': 'JBL Wave Buds Preto'=true; 'JBL Wave Buds "
    "2'=false; 'JBL Wave 200'=false. "
    "Responda APENAS com um objeto JSON válido, sem texto em volta, sem markdown: "
    '{"resultados": [{"i": 0, "mesmo": true, "motivo": "..."}, ...]}. '
    "'i' é o número da oferta; 'mesmo' é booleano; 'motivo' é curto (em português)."
)


class ClassificadorLLM:
    """Decide, em lote e via LLM, quais ofertas são o produto-alvo. Falhou → None."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://integrate.api.nvidia.com/v1",
        # Classificar identidade é tarefa SIMPLES: um instruct leve e rápido
        # (llama-3.1-8b: ~1.5s, veredito certo) bate um modelo de raciocínio (o
        # nemotron 49B levava 24–120s e estourava timeout). Não use reasoning aqui.
        model: str = "meta/llama-3.1-8b-instruct",
        timeout_s: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError("ClassificadorLLM exige uma chave de API")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_s = timeout_s

    def classificar(
        self, produto: Produto, ofertas: Sequence[OfertaBruta]
    ) -> list[VereditoIdentidade | None]:
        """Alvo + ofertas → vereditos alinhados. Qualquer falha → tudo `None`."""
        if not ofertas:
            return []
        dados = self._chamar(_alvo_de(produto), [o.titulo for o in ofertas])
        if dados is None:
            return [None] * len(ofertas)
        return _mapear_vereditos(dados, len(ofertas))

    def _chamar(self, alvo: str, titulos: list[str]) -> dict[str, object] | None:
        """POST no chat/completions. Isola rede e nunca vaza a chave em erro."""
        ofertas_txt = "\n".join(f"{i}. {t}" for i, t in enumerate(titulos))
        pergunta = f"ALVO: {alvo}\n\nOFERTAS:\n{ofertas_txt}"
        try:
            resposta = httpx.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "temperature": 0,
                    "max_tokens": 2000,  # ~1 linha JSON/oferta; folga p/ lote grande
                    "messages": [
                        {"role": "system", "content": _SISTEMA},
                        {"role": "user", "content": pergunta},
                    ],
                },
                timeout=self._timeout_s,
            )
        except httpx.HTTPError:
            return None  # rede/timeout → degrada pro determinístico
        if resposta.status_code != 200:
            return None
        try:
            corpo = resposta.json()
            conteudo = corpo["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            return None
        return _extrair_json(str(conteudo))


def _alvo_de(produto: Produto) -> str:
    """Texto compacto que identifica o produto-alvo pro juiz."""
    partes = [produto.marca or "", produto.modelo or "", produto.nome]
    for chave in ("gpu", "cpu", "ram", "armazenamento", "part_number"):
        valor = produto.atributos.get(chave)
        if valor:
            partes.append(valor)
    return " ".join(p for p in partes if p).strip()


def _extrair_json(texto: str) -> dict[str, object] | None:
    """Pega o objeto JSON da resposta, tolerando cercas markdown/texto em volta."""
    inicio = texto.find("{")
    fim = texto.rfind("}")
    if inicio == -1 or fim <= inicio:
        return None
    try:
        dados = json.loads(texto[inicio : fim + 1])
    except (ValueError, TypeError):
        return None
    return dados if isinstance(dados, dict) else None


def _mapear_vereditos(
    dados: dict[str, object], quantidade: int
) -> list[VereditoIdentidade | None]:
    """JSON validado → lista alinhada às ofertas. Índice fora/ausente → None."""
    vereditos: list[VereditoIdentidade | None] = [None] * quantidade
    resultados = dados.get("resultados")
    if not isinstance(resultados, list):
        return vereditos
    for item in resultados:
        if not isinstance(item, dict):
            continue
        i = item.get("i")
        mesmo = item.get("mesmo")
        if not isinstance(i, int) or not 0 <= i < quantidade:
            continue
        if not isinstance(mesmo, bool):
            continue  # não confia em "true"/1/None — só booleano de verdade
        motivo = item.get("motivo")
        vereditos[i] = VereditoIdentidade(
            mesmo=mesmo,
            motivo=str(motivo).strip() if isinstance(motivo, str) else (
                "IA: é o mesmo produto" if mesmo else "IA: produto diferente"
            ),
        )
    return vereditos
