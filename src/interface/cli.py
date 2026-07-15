"""CLI do Smart Price Tracker (§26) — cadastrar produtos e ver o ranking.

É o "composition root": o único lugar que amarra config + adaptadores + caso de
uso. As camadas de baixo não conhecem a CLI; a CLI é que conhece todas.

Uso:
    pesquisa-preco cadastrar -n "Echo Dot 5" -c eletronicos --proibidas "capa,suporte"
    pesquisa-preco listar
    pesquisa-preco buscar 1               # Google Shopping (várias lojas BR)
    pesquisa-preco buscar 1 --kabum       # só KaBuM! (frete/à vista/estoque real)
"""

import asyncio
import sqlite3
from dataclasses import replace
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from adapters.classificadores import ClassificadorLLM
from adapters.coletores.google_shopping import ColetorGoogleShopping
from adapters.coletores.kabum import ColetorKabum
from adapters.coletores.sandbox import ColetorSandbox
from adapters.coletores.vtex import lojas_vtex_padrao
from adapters.extratores import (
    LeitorDePagina,
    extrair_do_slug,
    extrair_identidade_do_titulo,
)
from adapters.repositorios.sqlite import (
    RepositorioProdutoSQLite,
    RepositorioSKUSQLite,
    RepositorioSnapshotSQLite,
    conectar,
)
from application.buscar_produto import (
    BuscarProduto,
    ProdutoInexistente,
    ResultadoBusca,
)
from application.coletores import Coletor
from config import Config, carregar_config
from domain import Produto, ReferenciaProduto

# V1: uma conta fixa (eu + noiva vêm no V6; o gancho conta_id já existe). RN16.
CONTA_PADRAO = 1

app = typer.Typer(
    help="Smart Price Tracker — comparador pessoal de preços (V1 local).",
    add_completion=False,
)
console = Console()


def _caminho_do_banco(database_url: str) -> str:
    """Extrai o caminho do arquivo de uma URL 'sqlite:///./precos.db'."""
    prefixo = "sqlite:///"
    if database_url.startswith(prefixo):
        return database_url[len(prefixo) :]
    return database_url


def _abrir() -> tuple[sqlite3.Connection, Config]:
    config = carregar_config()
    return conectar(_caminho_do_banco(config.database_url)), config


def _lista(texto: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in texto.split(",") if item.strip())


@app.command()
def cadastrar(
    nome: str = typer.Option(..., "--nome", "-n", help="Nome do produto."),
    categoria: str = typer.Option(..., "--categoria", "-c", help="Categoria."),
    marca: Optional[str] = typer.Option(None, help="Marca (ajuda o matching)."),
    modelo: Optional[str] = typer.Option(None, help="Modelo."),
    ean: Optional[str] = typer.Option(None, help="EAN/GTIN (a melhor chave)."),
    proibidas: str = typer.Option("", help="Palavras proibidas, separadas por vírgula."),
    obrigatorias: str = typer.Option("", help="Palavras obrigatórias, por vírgula."),
) -> None:
    """Cadastra um produto para acompanhar."""
    con, _ = _abrir()
    produto = RepositorioProdutoSQLite(con).salvar(
        Produto(
            nome=nome,
            categoria=categoria,
            marca=marca,
            modelo=modelo,
            ean=ean,
            palavras_proibidas=_lista(proibidas),
            palavras_obrigatorias=_lista(obrigatorias),
        ),
        CONTA_PADRAO,
    )
    console.print(
        f"[green]✓[/] Produto cadastrado: [bold]{produto.nome}[/] "
        f"(id [cyan]{produto.id}[/])"
    )


@app.command()
def rastrear(
    url: Optional[str] = typer.Argument(
        None, help="URL do produto que você achou no Google (caminho principal)."
    ),
    titulo: Optional[str] = typer.Option(
        None, "--titulo", "-t", help="Fallback: cole o título quando não tiver/ler a URL."
    ),
    categoria: Optional[str] = typer.Option(
        None, "--categoria", "-c", help="Sobrescreve a categoria detectada na página."
    ),
) -> None:
    """Rastreia um produto que você já achou: cola a URL (ou o título) e ele
    captura a identidade canônica e cadastra pra você comparar preço (PLANO §1).

    Você faz a descoberta no Google; a ferramenta só lê o produto que você
    escolheu (1 página que você já abriu — não é um robô vasculhando a loja).
    """
    if not url and not titulo:
        console.print(
            "[red]Informe a URL do produto[/] (ou [bold]--titulo[/] como fallback)."
        )
        raise typer.Exit(code=1)

    # Precedência: página lida (identidade rica) → título que você colou → nome
    # que está na própria URL (quando a loja bloqueia, o slug salva o dia).
    ref: Optional[ReferenciaProduto] = None
    if url:
        with console.status("[bold]Lendo a página do produto...[/]"):
            ref = asyncio.run(LeitorDePagina().ler(url))
    if ref is None and titulo:
        cfg = carregar_config()
        ref = extrair_identidade_do_titulo(
            titulo,
            nvidia_api_key=cfg.nvidia_api_key,
            nvidia_base_url=cfg.nvidia_base_url,
            nvidia_model=cfg.nvidia_model,
        )
    if ref is None and url:
        ref = extrair_do_slug(url)
        if ref is not None:
            console.print(
                "[yellow]Não li a página[/] (a loja bloqueou ou não expõe dado "
                "estruturado), [yellow]mas aproveitei o nome que está na própria URL.[/]"
            )
    if ref is None:
        console.print(
            "[red]Não deu pra identificar o produto por essa URL.[/] "
            "Cole o título com [bold]--titulo[/]."
        )
        raise typer.Exit(code=1)

    produto = ref.para_produto()
    if categoria:
        produto = replace(produto, categoria=categoria)  # Produto é frozen
    con, _ = _abrir()
    salvo = RepositorioProdutoSQLite(con).salvar(produto, CONTA_PADRAO)
    _mostrar_referencia(salvo, ref)


def _mostrar_referencia(produto: Produto, ref: ReferenciaProduto) -> None:
    """Mostra a identidade capturada e aponta o próximo passo (buscar preço)."""
    tabela = Table(title="Produto identificado")
    tabela.add_column("campo", style="dim")
    tabela.add_column("valor", style="bold")
    tabela.add_row("nome", produto.nome)
    tabela.add_row("categoria", produto.categoria)
    if produto.marca:
        tabela.add_row("marca", produto.marca)
    if produto.modelo:
        tabela.add_row("modelo", produto.modelo)
    if produto.ean:
        tabela.add_row("EAN", produto.ean)
    if produto.cor:
        tabela.add_row("cor", produto.cor)
    if ref.preco is not None:
        tabela.add_row("preço de referência", f"R$ {ref.preco}")
    console.print(tabela)
    console.print(
        f"[green]✓[/] Cadastrado (id [cyan]{produto.id}[/]). "
        f"Agora rode [bold]buscar {produto.id}[/] pra comparar o preço nas lojas."
    )


@app.command()
def listar() -> None:
    """Lista os produtos cadastrados."""
    con, _ = _abrir()
    produtos = RepositorioProdutoSQLite(con).produtos_ativos(CONTA_PADRAO)
    if not produtos:
        console.print("[yellow]Nenhum produto ainda.[/] Use [bold]cadastrar[/].")
        return
    tabela = Table(title="Produtos acompanhados")
    tabela.add_column("id", justify="right", style="cyan")
    tabela.add_column("nome", style="bold")
    tabela.add_column("categoria")
    tabela.add_column("proibidas", style="dim")
    for p in produtos:
        tabela.add_row(str(p.id), p.nome, p.categoria, ", ".join(p.palavras_proibidas))
    console.print(tabela)


@app.command()
def ofertas(
    produto_id: int = typer.Argument(..., help="id do produto (veja em 'listar')."),
) -> None:
    """Mostra as ofertas já guardadas de um produto, com o link completo (copiável)."""
    con, _ = _abrir()
    produto = RepositorioProdutoSQLite(con).obter(produto_id, CONTA_PADRAO)
    if produto is None:
        console.print(f"[red]Produto {produto_id} não encontrado.[/] Veja 'listar'.")
        raise typer.Exit(code=1)

    repo_sku = RepositorioSKUSQLite(con)
    repo_snap = RepositorioSnapshotSQLite(con)
    skus = repo_sku.de_produto(produto_id, CONTA_PADRAO)
    if not skus:
        console.print(
            f"[yellow]Nenhuma oferta guardada para '{produto.nome}'.[/] "
            "Rode [bold]buscar[/] primeiro."
        )
        return

    # Junta cada SKU ao seu último preço, ordena pelo mais barato.
    linhas = []
    for sku in skus:
        if sku.id is None:
            continue
        snap = repo_snap.ultimo_snapshot(sku.id, CONTA_PADRAO)
        preco = snap.preco if snap else None
        linhas.append((preco, sku.loja_origem, sku.url))
    linhas.sort(key=lambda t: (t[0] is None, t[0] or 0))

    console.print(f"\n[bold]{produto.nome}[/] — ofertas guardadas:\n")
    for preco, loja, url in linhas:
        valor = f"R$ {preco}" if preco is not None else "—"
        # Loja vira link clicável (Ctrl+clique); a URL sai crua embaixo, sem
        # quebra artificial (soft_wrap) pra copiar limpo mesmo sendo comprida.
        console.print(f"[green]{valor:>12}[/]  [bold][link={url}]{loja}[/link][/]")
        console.print(f"[dim]{url}[/]", soft_wrap=True)


@app.command()
def buscar(
    produto_id: int = typer.Argument(..., help="id do produto (veja em 'listar')."),
    cep: Optional[str] = typer.Option(None, help="CEP destino (para cotar frete)."),
    demo: bool = typer.Option(
        False, "--demo", help="Usa uma loja de demonstração (API aberta, sem token)."
    ),
    kabum: bool = typer.Option(
        False, "--kabum", help="Só KaBuM! (dados ricos: frete, à vista, estoque real)."
    ),
    vtex: bool = typer.Option(
        False,
        "--vtex",
        help="Inclui lojas VTEX (melhor esforço — podem bloquear por anti-bot).",
    ),
) -> None:
    """Busca o produto nas lojas e mostra o ranking por preço final à vista.

    Padrão: Google Shopping (várias lojas BR de uma vez, precisa da SERPER_API_KEY).
    """
    con, config = _abrir()
    coletores: list[Coletor]
    if demo:
        coletores = [ColetorSandbox()]
    elif kabum:
        coletores = [ColetorKabum()]
    elif vtex:
        coletores = [ColetorKabum(), *lojas_vtex_padrao()]
    else:
        # Padrão: comparação real em N lojas via Google Shopping (Serper).
        if not config.serper_api_key:
            console.print(
                "[red]Falta a SERPER_API_KEY no .env[/] (chave grátis em "
                "https://serper.dev). Ou use [bold]--kabum[/] / [bold]--demo[/]."
            )
            raise typer.Exit(code=1)
        coletores = [ColetorGoogleShopping(config.serper_api_key)]
    classificador = (
        ClassificadorLLM(
            config.nvidia_api_key,
            config.nvidia_base_url,
            config.nvidia_model_classificador,
        )
        if config.nvidia_api_key
        else None
    )
    caso_de_uso = BuscarProduto(
        coletores=coletores,
        repo_produto=RepositorioProdutoSQLite(con),
        repo_sku=RepositorioSKUSQLite(con),
        repo_snapshot=RepositorioSnapshotSQLite(con),
        classificador=classificador,
    )
    try:
        with console.status("[bold]Buscando nas lojas...[/]"):
            resultado = asyncio.run(
                caso_de_uso.executar(produto_id, CONTA_PADRAO, cep or config.cep_destino)
            )
    except ProdutoInexistente:
        console.print(f"[red]Produto {produto_id} não encontrado.[/] Veja 'listar'.")
        raise typer.Exit(code=1) from None

    _mostrar_ranking(resultado)


def _mostrar_ranking(resultado: ResultadoBusca) -> None:
    console.print(f"\n[bold]{resultado.produto.nome}[/] — melhores ofertas:\n")
    if resultado.ranking:
        tabela = Table()
        tabela.add_column("#", justify="right")
        tabela.add_column("Preço final", justify="right", style="green")
        tabela.add_column("Loja")
        tabela.add_column("Título (clique para abrir)")
        tabela.add_column("Estoque", justify="center")
        tabela.add_column("Match", justify="right", style="dim")
        for i, o in enumerate(resultado.ranking, 1):
            # Título vira link clicável pra oferta (Ctrl+clique nos terminais com
            # suporte a hyperlink, como o gnome-terminal). Mantém a tabela limpa.
            titulo = f"[link={o.url}]{o.titulo[:42]}[/link]" if o.url else o.titulo[:42]
            tabela.add_row(
                str(i),
                f"R$ {o.preco_final}",
                o.loja,
                titulo,
                "✓" if o.em_estoque else "—",
                f"{o.score_match:.2f}",
            )
        console.print(tabela)
        console.print(
            "[dim]Dica: Ctrl+clique no título abre a oferta. "
            "Veja os links completos (copiáveis) com [/][bold]ofertas <id>[/][dim].[/]"
        )
    else:
        console.print("[yellow]Nenhuma oferta casou com o produto.[/]")

    console.print(
        f"\n[dim]em revisão: {resultado.em_revisao} · "
        f"descartadas: {resultado.descartadas}[/]"
    )
    _mostrar_funil(resultado)
    if resultado.lojas_indisponiveis:
        console.print(
            f"[yellow]não responderam (instabilidade ou bloqueio de IP — tente do "
            f"seu PC): {', '.join(resultado.lojas_indisponiveis)}[/]"
        )
    if resultado.lojas_degradadas:
        console.print(
            f"[red]resposta inesperada (mudança de formato ou anti-bot): "
            f"{', '.join(resultado.lojas_degradadas)}[/]"
        )


def _mostrar_funil(resultado: ResultadoBusca) -> None:
    """Mostra POR QUE cada loja ficou de fora — o funil deixa de ser invisível."""
    if resultado.em_revisao_itens:
        tabela = Table(title="Em revisão (quase bateu — confira)")
        tabela.add_column("Loja")
        tabela.add_column("Score", justify="right", style="dim")
        tabela.add_column("Título")
        tabela.add_column("Motivo", style="yellow")
        for i in resultado.em_revisao_itens:
            tabela.add_row(i.loja, f"{i.score:.2f}", i.titulo[:40], i.motivo)
        console.print(tabela)

    if resultado.descartadas_itens:
        # Agrupa por motivo pra não despejar centenas de linhas — só o resumo.
        tally: dict[str, int] = {}
        for i in resultado.descartadas_itens:
            tally[i.motivo] = tally.get(i.motivo, 0) + 1
        linhas = sorted(tally.items(), key=lambda kv: kv[1], reverse=True)
        resumo = " · ".join(f"{motivo} ({n})" for motivo, n in linhas[:6])
        console.print(f"[dim]descartadas por motivo: {resumo}[/]")


if __name__ == "__main__":
    app()
