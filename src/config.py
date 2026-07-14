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

    def __repr__(self) -> str:
        # Mascara o segredo pra ele nunca aparecer em log/print/stack trace.
        token = "***" if self.ml_access_token else None
        serper = "***" if self.serper_api_key else None
        return (
            f"Config(database_url={self.database_url!r}, "
            f"ml_access_token={token!r}, "
            f"serper_api_key={serper!r}, "
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
    )
