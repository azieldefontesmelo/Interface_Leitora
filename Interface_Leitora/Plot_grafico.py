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
        for linha in leitor:
            for indice, valor in enumerate(linha):
                vetores[indice].append(float(valor))
    return nomes, vetores


def plotar_csv(caminho_csv, caminho_png):
    """Le os vetores do CSV e salva o grafico em caminho_png.

    Eixo X = primeira coluna (tempo); demais colunas = curvas.
    """
    nomes, vetores = ler_csv(caminho_csv)

    figura, eixo = plt.subplots(figsize=(8, 5))

    if vetores and vetores[0]:
        tempo = vetores[0]
        for nome, valores in zip(nomes[1:], vetores[1:]):
            eixo.plot(tempo, valores, label=nome)
        eixo.set_xlabel(nomes[0])
        eixo.legend()
    else:
        eixo.text(
            0.5, 0.5, "Sem dados para plotar",
            ha="center", va="center", transform=eixo.transAxes,
        )

    eixo.set_title(Path(caminho_csv).stem)
    eixo.set_ylabel("Valor")
    eixo.grid(True)
    figura.tight_layout()

    figura.savefig(caminho_png, dpi=100)
    plt.close(figura)

    return Path(caminho_png)


def gerar_grafico(caminho_txt, caminho_png, caminho_csv=None):
    """Fluxo completo: txt -> csv -> le csv -> vetores -> grafico.

    Devolve (caminho_csv, caminho_png).
    """
    caminho_csv = escrever_csv(caminho_txt, caminho_csv)
    plotar_csv(caminho_csv, caminho_png)
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
