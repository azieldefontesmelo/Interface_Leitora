# Interface Leitora OSL

Interface gráfica em **Python + Kivy** para controlar uma **leitora OSL**
(*Optically Stimulated Luminescence*) via porta **serial**. O programa envia
os comandos para o equipamento, recebe os dados de leitura em tempo real,
salva tudo em arquivos de log `.txt` e permite **visualizar os resultados em
gráficos** dentro da própria interface.

## ✨ Funcionalidades

- Conexão serial com a leitora (115200 baud) e seleção de porta.
- Envio de comandos: leitura, parar, zerar e ligar LED.
- Configuração de parâmetros de leitura (modo, ganho, tempo, potência…).
- Gravação automática dos dados em `.txt`, organizados por data, com **4
  colunas**: `Tempo`, `Leitura`, `Luz` e `Corrente`.
- Tela de **Gráficos**: busca um arquivo de log, plota o gráfico e exporta
  os dados para `.csv` (abre direto no Excel).

## 📦 Requisitos

- **Python 3.11+**
- Dependências (em `Interface_Leitora/requirements.txt`):
  - `kivy`, `pyserial`, `matplotlib`

## 🚀 Instalação

```bash
# clone o repositório
git clone https://github.com/azieldefontesmelo/Interface_Leitora.git
cd Interface_Leitora/Interface_Leitora

# (recomendado) crie um ambiente virtual
python -m venv .venv
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# Linux/Mac:
# source .venv/bin/activate

# instale as dependências
pip install -r requirements.txt
```

## ▶️ Como rodar

```bash
cd Interface_Leitora        # pasta que contém interface_OSL.py
python interface_OSL.py
```

> O arquivo `.kv` é carregado por caminho relativo, então execute o programa
> **de dentro da pasta `Interface_Leitora`**.

### Usando a interface

1. Selecione a **porta serial** e clique em **Conectar**.
2. Digite um nome de arquivo e clique em **Iniciar Log** para gravar.
3. Use **SUDO leitura** para iniciar a aquisição (e **SUDO stop** para parar).
4. Os dados são salvos em `assets/testes/AAAA/MM/DD/<nome>.txt`.

### Tela de Gráficos

1. Clique no botão **Graficos**.
2. Escolha um arquivo `.txt` no navegador de arquivos.
3. **Gerar gráfico** plota as curvas (eixo X = Tempo; curvas de Leitura, Luz e
   Corrente).
4. **Exportar CSV** salva os dados em `.csv` ao lado do `.txt`.

## 📁 Estrutura do projeto

```
Interface_Leitora/
└── Interface_Leitora/
    ├── interface_OSL.py        # aplicação principal (telas: main, parametros, graficos)
    ├── interface_OSL.kv        # layout da interface (Kivy)
    ├── Plot_grafico.py         # fluxo do gráfico: txt → csv → vetores → PNG
    ├── conversor/
    │   └── log_parser.py       # leitura do log e conversão para CSV
    ├── requirements.txt
    └── assets/
        ├── UI/                 # ícones
        └── testes/AAAA/MM/DD/  # logs .txt gravados por dia
```

## 📄 Formato do arquivo de log

Cada `.txt` tem 5 linhas de cabeçalho seguidas pelos dados:

```
30/06/2026 15:30:00
exemplo_4_vetores.txt
Soma: 167228
Dose: 16.7228
Tempo;Leitura;Luz;Corrente
0.0;2054;1750;2365
0.1;1962;1677;2302
```

Os **4 vetores**: `Tempo` (contador da amostra), `Leitura` (contagens),
`Luz` (densidade de potência) e `Corrente`.

