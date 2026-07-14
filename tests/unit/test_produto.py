"""Testes da entidade Produto: os invariantes do §11."""

import pytest

from domain import Produto


def test_cria_produto_com_o_minimo_obrigatorio():
    produto = Produto(nome="Echo Dot 5", categoria="eletronicos")
    assert produto.nome == "Echo Dot 5"
    assert produto.categoria == "eletronicos"
    # Padrões seguros: sem palavras de matching e status ativo.
    assert produto.palavras_proibidas == ()
    assert produto.status == "ativo"


def test_nome_vazio_e_recusado():
    with pytest.raises(ValueError):
        Produto(nome="   ", categoria="eletronicos")


def test_categoria_vazia_e_recusada():
    with pytest.raises(ValueError):
        Produto(nome="Echo Dot 5", categoria="")


def test_produto_e_imutavel():
    produto = Produto(nome="Echo Dot 5", categoria="eletronicos")
    with pytest.raises(Exception):  # frozen=True não deixa alterar
        produto.nome = "outro"  # type: ignore[misc]
