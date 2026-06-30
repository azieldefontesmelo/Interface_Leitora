"""Leitura dos logs .txt gravados pela Interface OSL.

Os logs tem 4 linhas de cabecalho (data, nome, "Soma:", "Dose:") seguidas
pelas linhas de dados. Existem dois formatos historicos:

    Antigo (separado por TAB, cada celula e um par "tempo valor"):
        0.0 1074 \t 0.0 507 \t 0.1 0
    Atual (separado por ';', um numero por celula):
        13014;1791;2361

Para suportar os dois, cada linha de dados e tratada extraindo todos os
numeros que ela contem (regex), independente do separador. Cada numero vira
uma coluna; o grafico usa o indice da amostra como eixo X.
"""

from pathlib import Path
import csv
import re

# Quantidade de linhas de cabecalho gravadas por iniciar_log (interface_OSL.py).
LINHAS_CABECALHO = 4

# Captura inteiros e decimais, com sinal opcional.
_NUMERO = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _extrair_numeros(linha):
    """Devolve a lista de numeros (float) presentes na linha, ou [] se nenhum."""
    return [float(n) for n in _NUMERO.findall(linha)]


def parse_log(caminho):
    """Le um log .txt e devolve (metadados, nomes_colunas, dados).

    metadados: dict com 'data', 'nome', 'soma', 'dose' (strings cruas do
        cabecalho; podem estar vazias se o log foi interrompido).
    nomes_colunas: lista ['coluna_1', ...] com tamanho da linha de dados mais
        comum encontrada.
    dados: lista de linhas, cada uma uma lista de floats. Linhas com numero
        de colunas diferente do padrao sao descartadas (linhas parciais).
    """
    caminho = Path(caminho)
    linhas = caminho.read_text(encoding="utf-8", errors="ignore").splitlines()

    cabecalho = linhas[:LINHAS_CABECALHO]
    metadados = {
        "data": cabecalho[0].strip() if len(cabecalho) > 0 else "",
        "nome": cabecalho[1].strip() if len(cabecalho) > 1 else "",
        "soma": cabecalho[2].strip() if len(cabecalho) > 2 else "",
        "dose": cabecalho[3].strip() if len(cabecalho) > 3 else "",
    }

    # Apos as 4 linhas de metadados pode existir uma linha de nomes de coluna
    # (ex.: "Tempo;Leitura;Luz;Corrente") — linha sem numeros. Se houver, ela
    # vira os nomes das colunas; o resto sao os dados.
    nomes_cabecalho = []
    inicio_dados = LINHAS_CABECALHO
    for indice in range(LINHAS_CABECALHO, len(linhas)):
        if not linhas[indice].strip():
            inicio_dados = indice + 1
            continue
        if _extrair_numeros(linhas[indice]):
            inicio_dados = indice
            break
        nomes_cabecalho = re.split(r"[;\t,]", linhas[indice].strip())
        nomes_cabecalho = [n.strip() for n in nomes_cabecalho if n.strip()]
        inicio_dados = indice + 1
        break

    linhas_numeros = [
        numeros
        for linha in linhas[inicio_dados:]
        if (numeros := _extrair_numeros(linha))
    ]

    if not linhas_numeros:
        return metadados, nomes_cabecalho, []

    # Numero de colunas = contagem mais frequente (ignora linhas parciais).
    contagens = [len(n) for n in linhas_numeros]
    n_colunas = max(set(contagens), key=contagens.count)

    dados = [n for n in linhas_numeros if len(n) == n_colunas]

    if len(nomes_cabecalho) == n_colunas:
        nomes_colunas = nomes_cabecalho
    else:
        nomes_colunas = [f"coluna_{i + 1}" for i in range(n_colunas)]

    return metadados, nomes_colunas, dados


def escrever_csv(caminho_txt, caminho_csv=None):
    """Converte um log .txt em .csv e devolve o caminho do CSV gerado.

    Se caminho_csv for None, salva ao lado do .txt com a mesma base.
    """
    caminho_txt = Path(caminho_txt)
    if caminho_csv is None:
        caminho_csv = caminho_txt.with_suffix(".csv")
    caminho_csv = Path(caminho_csv)

    _, nomes_colunas, dados = parse_log(caminho_txt)

    with open(caminho_csv, "w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        if nomes_colunas:
            escritor.writerow(nomes_colunas)
        escritor.writerows(dados)

    return caminho_csv
