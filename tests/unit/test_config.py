"""Testes da configuração. Não dependem de .env real: passamos um dict."""

from config import carregar_config


def test_usa_sqlite_como_padrao_quando_nao_ha_database_url():
    config = carregar_config(ambiente={})
    assert config.database_url == "sqlite:///./precos.db"


def test_le_os_valores_do_ambiente():
    config = carregar_config(
        ambiente={
            "DATABASE_URL": "sqlite:///./teste.db",
            "CEP_DESTINO": "01001000",
        }
    )
    assert config.database_url == "sqlite:///./teste.db"
    assert config.cep_destino == "01001000"


def test_cashback_elegivel_vira_lista_normalizada():
    config = carregar_config(ambiente={"CASHBACK_ELEGIVEL": "Inter, Meliuz ,, AME"})
    assert config.cashback_elegivel == ("inter", "meliuz", "ame")


def test_cashback_vazio_vira_tupla_vazia():
    config = carregar_config(ambiente={})
    assert config.cashback_elegivel == ()


def test_repr_mascara_o_token_para_nao_vazar_em_log():
    config = carregar_config(ambiente={"ML_ACCESS_TOKEN": "segredo-super-secreto"})
    texto = repr(config)
    assert "segredo-super-secreto" not in texto  # o segredo NÃO aparece
    assert "***" in texto                          # aparece mascarado
