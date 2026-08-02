# Como rodar o OSLMeter

Este guia mostra como preparar o ambiente, iniciar a interface e testar o
projeto com uma leitora física ou com o simulador.

## 1. Pré-requisitos

- Windows 10/11, Linux ou macOS.
- Python 3.11 ou superior.
- Git, caso o projeto ainda precise ser clonado.
- Uma porta serial disponível para usar a leitora física.

Confirme o Python instalado:

```powershell
python --version
```

No Windows, se `python` não for reconhecido, tente:

```powershell
py --version
```

## 2. Obter o projeto

```powershell
git clone https://github.com/azieldefontesmelo/Interface_Leitora.git
cd Interface_Leitora
```

As branches `master` e `banco-de-dados` contêm a versão com integração SQLite.
Para selecionar explicitamente uma delas:

```powershell
git switch master
```

ou:

```powershell
git switch banco-de-dados
```

## 3. Criar o ambiente virtual

Entre na pasta que contém `interface_OSL.py`:

```powershell
cd Interface_Leitora
python -m venv .venv
```

Ative o ambiente no PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Se o PowerShell bloquear a ativação, permita scripts somente para a sessão
atual e tente novamente:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

No Prompt de Comando do Windows:

```bat
.venv\Scripts\activate.bat
```

No Linux ou macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## 4. Instalar as dependências

Com o ambiente virtual ativo:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

O `requirements.txt` instala as dependências externas usadas pela aplicação:

- Kivy;
- pyserial;
- matplotlib;
- pandas.

SQLite não exige instalação separada, pois o módulo `sqlite3` acompanha o
Python.

## 5. Iniciar a interface

Ainda na pasta interna `Interface_Leitora`, execute:

```powershell
python interface_OSL.py
```

A pasta correta deve conter estes arquivos:

```text
Interface_Leitora/
├── interface_OSL.py
├── interface_OSL.kv
├── database.py
├── measurement_workflow.py
├── requirements.txt
└── assets/
```

Na primeira execução, o programa cria ou atualiza automaticamente o banco:

```text
assets/database/measurements.sqlite3
```

O esquema SQLite é migrado para a versão atual sem precisar executar comandos
SQL manualmente.

## 6. Usar com a leitora física

1. Conecte a leitora ao computador.
2. Abra a aplicação.
3. Clique em **Refresh** para atualizar as portas.
4. Selecione a porta COM correspondente.
5. Clique em **Connect**.
6. Escolha o modo Manual ou Dosímetro ID.
7. Preencha ou confirme os parâmetros necessários.
8. Clique em **Start**.

No modo Dosímetro ID, a leitora e o dosímetro precisam estar cadastrados,
ativos e dentro do período de validade. O teste só é consolidado depois das
leituras de Hp(10) e Hp(0,07).

## 7. Testar sem o equipamento físico

O simulador requer um par de portas seriais virtuais. A configuração padrão é:

```text
Interface: COM5
Simulador: COM6
```

Com o par virtual criado, abra um segundo terminal, ative o mesmo ambiente
virtual e execute:

```powershell
simulacao\rodar_simulador.bat
```

Também é possível iniciar diretamente:

```powershell
python simulacao\simulador_osl.py
```

Depois, na interface:

1. selecione `COM5`;
2. clique em **Connect**;
3. inicie a aquisição.

Se o par usar outros números, altere `PORTA_SERIAL` no início de
`simulacao/simulador_osl.py`.

No Linux, o simulador também depende do suporte Tk do sistema. Em distribuições
baseadas em Debian/Ubuntu, ele costuma ser fornecido pelo pacote `python3-tk`.

## 8. Executar os testes

Com o ambiente virtual ativo e dentro da pasta interna `Interface_Leitora`:

```powershell
python -m unittest discover -s tests -v
```

Os testes usam bancos e diretórios temporários e não alteram o banco real da
aplicação.

## 9. Gerar o executável Windows

O PyInstaller não faz parte das dependências necessárias para executar o código
Python. Para gerar uma distribuição, instale-o separadamente:

```powershell
python -m pip install pyinstaller
pyinstaller OSLMeter.spec
```

O resultado será criado em `dist/OSLMeter`.

## 10. Problemas comuns

### `ModuleNotFoundError`

Confirme que o ambiente virtual está ativo e reinstale as dependências:

```powershell
python -m pip install -r requirements.txt
```

### `interface_OSL.kv` não encontrado

Execute `python interface_OSL.py` dentro da pasta interna `Interface_Leitora`.

### Nenhuma porta serial aparece

Verifique o cabo, o driver do equipamento e clique em **Refresh**. Para o
simulador, confirme que o par de portas virtuais foi criado.

### Start desabilitado no modo Dosímetro ID

Confira se:

- o Dosímetro ID possui 10 dígitos;
- a leitora foi selecionada;
- os dois cadastros estão ativos e dentro da validade;
- ECC e RCF são maiores que zero.

### Banco ocupado

Feche outras instâncias da aplicação que estejam usando o mesmo arquivo
SQLite. O sistema aguarda até 10 segundos antes de informar a falha.
