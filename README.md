# OSLMeter V4.0

Interface gráfica em **Python + Kivy** para controlar uma **leitora OSL**
(*Optically Stimulated Luminescence*) via porta **serial**. O programa envia
comandos para o equipamento, recebe dados em tempo real, salva em arquivos de
log `.txt` e permite **visualizar gráficos** com filtros por curva.

## Funcionalidades

- Conexão serial com a leitora (115200 baud) e seleção de porta.
- Envio de comandos: leitura, stop, zerar e ligar LED.
- **Reference Light**: modo que mede o integral da luz em vez da dose.
- Configuração de parâmetros de leitura (modo, ganho, tempo, potência…).
- Cálculo de dose: `(soma - branco) × rcf × ecc × fcal × fenerg`.
- Parada automática após o tempo de leitura configurado.
- Gravação em buffer em memória, com descarte em lote ao fechar o log.
- Dados salvos em `assets/testes/AAAA/MM/DD/<nome>.txt`, com **3 colunas**:
  `Time`, `Count`, `Light` (e `Current` exibido na tela, fora do arquivo).
- Tela de **Gráficos**: busca arquivo de log, plota curvas selecionáveis
  (Count, Current, Light) via checkboxes e exporta para `.csv`.
- **PyInstaller**: função `resource_path()` para localizar assets relativas ao
  executável empacotado.

## Requisitos

- **Python 3.11+**
- Dependências (em `Interface_Leitora/requirements.txt`):
  - `kivy==2.3.1`
  - `pyserial==3.5`
  - `matplotlib==3.9.2`

## Instalação

```bash
git clone https://github.com/azieldefontesmelo/Interface_Leitora.git
cd Interface_Leitora/Interface_Leitora

python -m venv .venv
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# Linux/Mac:
# source .venv/bin/activate

pip install -r requirements.txt
```

## Como rodar

```bash
cd Interface_Leitora        # pasta que contém interface_OSL.py
python interface_OSL.py
```

> O arquivo `.kv` é carregado por caminho relativo, então execute o programa
> **de dentro da pasta `Interface_Leitora`**.

### Usando a interface

1. Selecione a **porta serial** e clique em **Connect**.
2. Digite um nome de arquivo e clique em **Iniciar Log** para gravar.
3. Use **SUDO leitura** para iniciar a aquisição (e **SUDO stop** para parar).
4. Os dados são salvos em `assets/testes/AAAA/MM/DD/<nome>.txt`.
5. **Ref Light** mede o integral da luz (exibe no label da dose).
6. **Parameters**: configura modo, ganho, tempo de leitura, potência,
   zeramento e parâmetros de dose (ECC, RCF, Branco, Fcal, Fenerg).

### Tela de Gráficos

1. Clique no botão **Graficos**.
2. Escolha um arquivo `.txt` no navegador de arquivos.
3. Marque/desmarque **Count**, **Current** e **Light** para filtrar curvas.
4. **Gerar gráfico** plota as curvas selecionadas.
5. **Exportar CSV** salva os dados em `.csv` ao lado do `.txt`.

## Estrutura do projeto

```
Interface_Leitora/
└── Interface_Leitora/
    ├── interface_OSL.py        # aplicação principal (telas: main, parametros, graficos)
    ├── interface_OSL.kv        # layout da interface (Kivy)
    ├── Plot_grafico.py         # fluxo do gráfico: txt → csv → vetores → PNG
    ├── conversor/
    │   ├── __init__.py         # exporta parse_log e escrever_csv
    │   └── log_parser.py       # leitura do log e conversão para CSV
    ├── requirements.txt
    ├── test.py                 # protótipo/sandbox (não faz parte do app principal)
    └── assets/
        ├── UI/                 # ícones
        └── testes/AAAA/MM/DD/  # logs .txt gravados por dia
```

## Formato do arquivo de log

Cada `.txt` tem 5 linhas de cabeçalho seguidas pelos dados:

```
30/06/2026 15:30:00
exemplo.txt
Integral:
Dose mSv:
Time;Count;Current;Light
16632;1690;1750;2220
16633;1579;1677;2239
```

Ao fechar o log, as linhas `Integral:` e `Dose mSv:` são atualizadas para
`Soma: {soma}` e `Dose: {dose}` com o valor calculado.

As **3 colunas de dados** no arquivo são:
- `Time` — contador da amostra (incrementa a cada 0,1 s)
- `Count` — contagens do detector (frame `#L1%A`)
- `Light` — densidade de potência luminosa (frame `#L1%D`)

A **Current** (frame `#L1%E`) é exibida na tela em tempo real mas não é
persistida no arquivo de log.
