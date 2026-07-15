"""Configuração da aplicação.

Regra de segurança: segredo NUNCA no código — tudo vem do ambiente (.env).
Ver regras invioláveis no CLAUDE.md e no PRD §27.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    """Configuração lida do ambiente.

    `frozen=True`: depois de criada, não muda (evita alteração acidental).
    """

    database_url: str
    ml_access_token: str | None = None
    serper_api_key: str | None = None
    cep_destino: str | None = None
    cashback_elegivel: tuple[str, ...] = field(default_factory=tuple)
    # LLM de extração de identidade (NVIDIA, endpoint OpenAI-compatível). Sem
    # chave, o cadastro cai na heurística — o LLM é opcional (degrada limpo).
    nvidia_api_key: str | None = None
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    # Modelo da EXTRAÇÃO de identidade (1 título → marca/modelo/specs no cadastro).
    # Um instruct leve e rápido (8b) é confiável e melhor que o nemotron 49B de
    # raciocínio, que era lento e falhava ~50% por timeout no cadastro.
    nvidia_model: str = "meta/llama-3.1-8b-instruct"
    # Modelo do CLASSIFICADOR (alvo × N ofertas → mesmo/diferente na busca). Tarefa
    # simples e no caminho crítico: um instruct leve e rápido (não use raciocínio,
    # que é lento e estoura timeout no lote).
    nvidia_model_classificador: str = "meta/llama-3.1-8b-instruct"

    def __repr__(self) -> str:
        # Mascara o segredo pra ele nunca aparecer em log/print/stack trace.
        token = "***" if self.ml_access_token else None
        serper = "***" if self.serper_api_key else None
        nvidia = "***" if self.nvidia_api_key else None
        return (
            f"Config(database_url={self.database_url!r}, "
            f"ml_access_token={token!r}, "
            f"serper_api_key={serper!r}, "
            f"nvidia_api_key={nvidia!r}, "
            f"nvidia_base_url={self.nvidia_base_url!r}, "
            f"nvidia_model={self.nvidia_model!r}, "
            f"nvidia_model_classificador={self.nvidia_model_classificador!r}, "
            f"cep_destino={self.cep_destino!r}, "
            f"cashback_elegivel={self.cashback_elegivel!r})"
        )


def _lista_de(valor: str | None) -> tuple[str, ...]:
    """Transforma "inter, meliuz" em ("inter", "meliuz"). Vazio → ()."""
    if not valor:
        return ()
    return tuple(item.strip().lower() for item in valor.split(",") if item.strip())


def carregar_config(ambiente: Mapping[str, str] | None = None) -> Config:
    """Monta a Config a partir das variáveis de ambiente.

    Passe `ambiente` (um dict) nos testes; em produção usa o os.environ real,
    já preenchido pelo .env via load_dotenv().
    """
    if ambiente is None:
        load_dotenv()  # popula o os.environ a partir do arquivo .env, se existir
        ambiente = os.environ

    return Config(
        database_url=ambiente.get("DATABASE_URL", "sqlite:///./precos.db"),
        ml_access_token=ambiente.get("ML_ACCESS_TOKEN") or None,
        serper_api_key=ambiente.get("SERPER_API_KEY") or None,
        cep_destino=ambiente.get("CEP_DESTINO") or None,
        cashback_elegivel=_lista_de(ambiente.get("CASHBACK_ELEGIVEL")),
        nvidia_api_key=ambiente.get("NVIDIA_API_KEY") or None,
        nvidia_base_url=(
            ambiente.get("NVIDIA_BASE_URL") or "https://integrate.api.nvidia.com/v1"
        ),
        nvidia_model=(
            ambiente.get("NVIDIA_MODEL") or "meta/llama-3.1-8b-instruct"
        ),
        nvidia_model_classificador=(
            ambiente.get("NVIDIA_MODEL_CLASSIFICADOR") or "meta/llama-3.1-8b-instruct"
        ),
    )
