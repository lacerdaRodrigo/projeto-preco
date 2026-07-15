"""Extrator de identidade por LLM (NVIDIA, endpoint OpenAI-compatível).

A "porta da frente" robusta: um título colado de QUALQUER categoria vira a
identidade canônica (marca, linha, modelo, specs) sem dicionário na mão. É a
alternativa à heurística determinística (`texto.py`/`heuristica.py`), atrás do
MESMO contrato — quem chama tenta o LLM e cai na heurística se ele falhar.

Fronteiras (CLAUDE.md): rede isolada aqui; o núcleo não importa isto. O dado que
volta do modelo é **não-confiável** — parse defensivo, valida tudo, nunca crava
palpite. Qualquer falha (sem chave, HTTP≠200, JSON inválido, timeout) → `None`,
e o chamador usa a heurística (degradação limpa, RN12). Segredo (a chave) nunca
é logado.

Roda 1× no cadastro; o resultado é persistido no Produto, então busca e matching
seguem determinísticos.
"""

from __future__ import annotations

import json
import re

import httpx

from domain.referencia import ReferenciaProduto

# Pedimos um objeto JSON enxuto. O título inteiro continua sendo a identidade
# textual (o matching compara sobre ele); o LLM só destaca a âncora e as specs.
_SISTEMA = (
    "Você extrai a identidade de um produto a partir do título que o usuário "
    "cola de uma loja brasileira. Responda APENAS com um objeto JSON válido, sem "
    "texto em volta, sem markdown. Campos (use string vazia quando não souber, "
    "nunca invente): "
    '{"marca": "", "linha": "", "modelo": "", "part_number": "", '
    '"categoria": "", "gpu": "", "cpu": "", "ram": "", "armazenamento": "", '
    '"cor": ""}. '
    "Regras: categoria em minúsculo e simples (celular, notebook, tv, monitor, "
    "fone, tablet, geladeira...). 'linha' é a família comercial (ex.: 'TUF "
    "Gaming', 'Galaxy S', 'Moto G'). 'modelo' é o identificador curto (ex.: "
    "'A15', 'S24', 'G67'). 'part_number' é o código do fabricante quando houver "
    "(ex.: 'FA507NV'). ram e armazenamento com unidade (ex.: '16GB', '512GB', "
    "'1TB'). gpu e cpu como aparecem (ex.: 'RTX 3050', 'Ryzen 7')."
)


class ExtratorLLM:
    """Extrai `ReferenciaProduto` de um título via LLM. Falhou → `None`."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://integrate.api.nvidia.com/v1",
        model: str = "meta/llama-3.1-8b-instruct",
        timeout_s: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("ExtratorLLM exige uma chave de API")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_s = timeout_s

    def extrair(self, titulo: str) -> ReferenciaProduto | None:
        """Título → identidade rica. Qualquer falha vira `None` (cai na heurística)."""
        limpo = titulo.strip()
        if not limpo:
            return None
        dados = self._chamar(limpo)
        if dados is None:
            return None
        return _para_referencia(limpo, dados)

    def _chamar(self, titulo: str) -> dict[str, object] | None:
        """POST no chat/completions. Isola rede e nunca vaza a chave em erro."""
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
                    "max_tokens": 400,
                    "messages": [
                        {"role": "system", "content": _SISTEMA},
                        {"role": "user", "content": titulo},
                    ],
                },
                timeout=self._timeout_s,
            )
        except httpx.HTTPError:
            return None  # rede/timeout → degrada pra heurística
        if resposta.status_code != 200:
            return None
        try:
            corpo = resposta.json()
            conteudo = corpo["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            return None
        return _extrair_json(str(conteudo))


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


def _str(dados: dict[str, object], chave: str) -> str | None:
    """Campo string não-vazio do JSON; qualquer outra coisa → None (não confia)."""
    valor = dados.get(chave)
    if not isinstance(valor, str):
        return None
    limpo = valor.strip()
    return limpo or None


# EAN-13 escrito no título é o portão forte do matching — aproveita se houver.
_EAN = re.compile(r"\b(\d{13})\b")


def _para_referencia(titulo: str, dados: dict[str, object]) -> ReferenciaProduto | None:
    """JSON validado → ReferenciaProduto. Sem marca E sem modelo úteis → None
    (deixa a heurística tentar, em vez de gravar identidade vazia)."""
    marca = _str(dados, "marca")
    linha = _str(dados, "linha")
    modelo_curto = _str(dados, "modelo")
    part_number = _str(dados, "part_number")

    # Âncora de busca: a linha + o modelo curto ("TUF Gaming A15"); o part-number
    # entra como atributo (específico demais pra query, mas útil no matching).
    modelo = " ".join(p for p in (linha, modelo_curto) if p) or part_number

    if not marca and not modelo:
        return None  # identidade fraca demais — melhor a heurística tentar

    atributos: dict[str, str] = {}
    for chave in ("gpu", "cpu", "ram", "armazenamento"):
        valor = _str(dados, chave)
        if valor:
            atributos[chave] = valor
    if part_number:
        atributos["part_number"] = part_number

    achado = _EAN.search(titulo)
    return ReferenciaProduto(
        titulo=titulo,
        url="",
        ean=achado.group(1) if achado else None,
        marca=marca,
        modelo=modelo,
        cor=_str(dados, "cor"),
        categoria=_str(dados, "categoria"),
        atributos=atributos,
    )
