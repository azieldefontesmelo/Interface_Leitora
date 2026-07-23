"""Geracao do grafico :

    1. transformar o .txt em .csv (e salvar o .csv);
    2. ler o .csv;
    3. carregar os dados em vetores (uma lista por coluna);
    4. plotar o grafico e salvar em PNG.

"""

from pathlib import Path
import csv

import matplotlib
matplotlib.use("Agg")  # backend sem janela; precisa vir antes do pyplot
import matplotlib.pyplot as plt

from conversor.log_parser import escrever_csv


def ler_csv(caminho_csv):
    """Le o CSV e devolve (nomes_colunas, vetores).

    vetores: lista com uma lista (vetor) por coluna do CSV.
    """
    with open(caminho_csv, encoding="utf-8", newline="") as arquivo:
        leitor = csv.reader(arquivo)
        nomes = next(leitor, [])
        vetores = [[] for _ in nomes]
        for numero_linha, linha in enumerate(leitor, start=2):
            if not linha:
                continue
            if len(linha) != len(vetores):
                raise ValueError(
                    f"Linha {numero_linha} possui {len(linha)} colunas; "
                    f"esperadas {len(vetores)}."
                )
            try:
                valores = [float(valor) for valor in linha]
            except ValueError as erro:
                raise ValueError(
                    f"Valor inválido na linha {numero_linha}."
                ) from erro
            for indice, valor in enumerate(valores):
                vetores[indice].append(valor)
    return nomes, vetores


def _mapear_series(nomes, vetores):
    """Normaliza os formatos históricos de 3, 4 e 5 colunas.

    Formato antigo (3): Count, Current, Light; o tempo é o índice da amostra.
    Formato esperado (4): Time, Count, Current, Light.
    Formato atual (5): Time, Count, Current, Sample, Light.
    """
    quantidade = len(vetores)
    if quantidade >= 5:
        tempo = vetores[0]
        indices = (1, 2, 4)
    elif quantidade == 4:
        tempo = vetores[0]
        indices = (1, 2, 3)
    elif quantidade == 3:
        tempo = [indice * 0.1 for indice in range(len(vetores[0]))]
        indices = (0, 1, 2)
    else:
        raise ValueError(
            f"Formato não suportado: o arquivo possui {quantidade} colunas."
        )

    rotulos_padrao = ("Count (0.1s)", "Current (mA)", "Light (mV)")
    series = []
    for indice, rotulo in zip(indices, rotulos_padrao):
        if indice >= quantidade:
            continue
        if len(vetores[indice]) != len(tempo):
            raise ValueError(f"A coluna {indice + 1} possui tamanho inconsistente.")
        nome = nomes[indice] if indice < len(nomes) else rotulo
        if not nome or nome.startswith("coluna_"):
            nome = rotulo
        series.append((nome, vetores[indice]))
    return tempo, series


def plotar_csv(caminho_csv, caminho_png, gerar_grafico_leitura=1, gerar_grafico_corrente=1, gerar_grafico_luz=1):
    """Le os vetores do CSV e salva o grafico em caminho_png.

    Eixo X = primeira coluna (tempo); demais colunas = curvas.
    """
    nomes, vetores = ler_csv(caminho_csv)

    figura, eixo = plt.subplots(figsize=(8, 5))
    try:
        if vetores and vetores[0]:
            tempo, series = _mapear_series(nomes, vetores)
            habilitadas = (
                gerar_grafico_leitura,
                gerar_grafico_corrente,
                gerar_grafico_luz,
            )
            for habilitada, (nome, valores) in zip(habilitadas, series):
                if habilitada:
                    eixo.plot(tempo, valores, label=nome)

            eixo.set_xlabel("Time (s)")
            if any(habilitadas):
                eixo.legend()
        else:
            eixo.text(
                0.5, 0.5, "Sem dados para plotar",
                ha="center", va="center", transform=eixo.transAxes,
            )

        eixo.set_title(Path(caminho_csv).stem)
        eixo.set_ylabel("Value (u.a.)")
        eixo.grid(True)
        figura.tight_layout()
        figura.savefig(caminho_png, dpi=100)
    finally:
        plt.close(figura)

    return Path(caminho_png)


def gerar_grafico(caminho_txt, caminho_png, caminho_csv=None, gerar_grafico_leitura=1, gerar_grafico_corrente=1, gerar_grafico_luz=1):
    """Fluxo completo: txt -> csv -> le csv -> vetores -> grafico.

    Devolve (caminho_csv, caminho_png).
    """
    caminho_txt = Path(caminho_txt)
    if caminho_txt.suffix.lower() == ".csv":
        caminho_csv = caminho_txt
    else:
        caminho_csv = escrever_csv(caminho_txt, caminho_csv)
    plotar_csv(caminho_csv, caminho_png, gerar_grafico_leitura, gerar_grafico_corrente, gerar_grafico_luz)
    return caminho_csv, Path(caminho_png)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("uso: python Plot_grafico.py <arquivo.txt> [saida.png]")
        raise SystemExit(1)

    txt = sys.argv[1]
    png = sys.argv[2] if len(sys.argv) > 2 else str(Path(txt).with_suffix(".png"))
    csv_gerado, png_gerado = gerar_grafico(txt, png)
    print(f"CSV salvo em:  {csv_gerado}")
    print(f"Grafico salvo: {png_gerado}")
