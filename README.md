# OSLMeter V4.0

Aplicação desktop em **Python + Kivy** para controlar uma leitora OSL
(*Optically Stimulated Luminescence*) pela porta serial, acompanhar os valores
em tempo real, calcular a dose, salvar o arquivo técnico da aquisição e manter
um histórico auditável em **SQLite**.

O programa trabalha em dois modos:

- **Manual**: o operador informa ECC, RCF, Fang, Fenerg, Base Line e o nome do
  arquivo.
- **Dosímetro ID**: o código de barras identifica um dosímetro cadastrado; ECC
  e RCF são carregados do banco e o nome do arquivo é gerado automaticamente.

## Funcionalidades

- Conexão serial a `115200 baud`, seleção e atualização das portas disponíveis.
- Comandos de leitura, Stop, Erase, Ref Light e configuração da leitora.
- Modos de teste **Manual** e **Dosímetro ID**.
- Captura de código de barras com 10 dígitos e Enter final.
- Cadastro e manutenção de dosímetros e leitoras.
- Validação de estado ativo e período de validade antes da aquisição.
- Cálculo de dose com os parâmetros efetivamente aplicados.
- Histórico SQLite com snapshots de ECC, RCF, Fang, Fenerg e Base Line.
- Arquivos `.txt` separados por ano, mês e dia.
- Gráfico em tempo real e tela para abrir logs antigos.
- Exportação do histórico filtrado para CSV.
- Backup consistente do banco pela API de backup do SQLite.
- Simulador de leitora para desenvolvimento sem o equipamento físico.
- Empacotamento para Windows com PyInstaller.

## Requisitos

- Python 3.11 ou superior.
- Kivy 2.3.1.
- pyserial 3.5.
- matplotlib 3.9.2.
- pandas 3.0.5, usado para organizar tabelas, filtros, formatação de dados e exportações.

O módulo `sqlite3` já faz parte da biblioteca padrão do Python.

## Instalação

No PowerShell:

```powershell
git clone https://github.com/azieldefontesmelo/Interface_Leitora.git
cd Interface_Leitora\Interface_Leitora

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

No Linux ou macOS, ative o ambiente com:

```bash
source .venv/bin/activate
```

## Como executar

A partir da pasta que contém `interface_OSL.py`:

```powershell
python interface_OSL.py
```

Os caminhos de `interface_OSL.kv` e `assets` são resolvidos com base na pasta
do código ou do executável empacotado. A janela abre maximizada e possui tamanho
mínimo de `900 × 650` para evitar sobreposição dos formulários.

## Visão geral da interface

A barra lateral esquerda contém as áreas principais:

1. **Leitura OSL**: conexão, modos de teste, aquisição e monitoramento.
2. **Banco de dados**: dosímetros, leitoras, histórico, CSV e backup.
3. **Gráficos**: abertura e plotagem de arquivos `.txt`.
4. **Setup**: parâmetros enviados ao firmware da leitora.

### Conexão serial

Na parte superior da tela de leitura:

1. Clique em **Refresh** para atualizar as portas.
2. Selecione a porta COM.
3. Clique em **Connect**.
4. O botão muda para **Disconnect** quando a conexão é aberta.

A aplicação registra uma cópia da comunicação serial em:

```text
assets/log/serial_AAAAMMDD_HHMMSS_microssegundos.txt
```

Cada linha contém horário, direção (`TX`, `RX` ou sistema) e conteúdo do
evento. Esse log serve para diagnóstico e não substitui o arquivo da medição.

## Modo Manual

Selecione a aba **Manual**. Os seguintes campos ficam visíveis e editáveis:

| Campo | Função |
|---|---|
| `ECC` | fator individual do dosímetro usado no cálculo |
| `RCF` | fator da leitora usado no cálculo |
| `Fang` | fator angular |
| `Fenerg` | fator de energia |
| `Base Line` | valor subtraído da soma |
| `File Name` | nome do arquivo `.txt` |

Antes do Start, ECC, RCF, Fang e Fenerg devem ser números maiores que zero.
Base Line deve ser numérica e não negativa. O nome do arquivo não aceita
caminho absoluto, `..` nem caracteres inválidos do Windows.

Fluxo:

1. Preencha os parâmetros.
2. Informe o nome do arquivo.
3. Conecte a serial.
4. Clique em **Start**.
5. A aplicação cria uma medição `EM_ANDAMENTO`, cria o `.txt` sem sobrescrever
   um arquivo existente e envia o comando de leitura.
6. Ao final, grava os valores e altera o status para `CONCLUIDO`.

No modo Manual, o histórico usa `test_mode = MANUAL` e não exige dosímetro nem
leitora cadastrados.

## Modo Dosímetro ID

Selecione a aba **Dosímetro ID**. O painel manual é ocultado e são mostrados:

- campo `Dosímetro ID`;
- seletor de leitora;
- status de validação;
- ECC e RCF encontrados;
- nome automático do arquivo.

### Leitor de código de barras

O leitor funciona como teclado. Ao abrir a aba:

1. O campo recebe foco automaticamente.
2. O leitor envia os 10 dígitos.
3. O Enter final executa a consulta. Se o ID completo e a leitora já estiverem
   preenchidos, a consulta também é feita automaticamente.
4. Espaços e caracteres de controle do scanner são removidos, sem alterar os
   dígitos.
5. A consulta não inicia a aquisição; o operador ainda confirma em **Start**.

O Start só é habilitado quando:

- o ID contém exatamente 10 dígitos ASCII;
- o dosímetro existe, está ativo e dentro da validade;
- o ECC do dosímetro é maior que zero;
- uma leitora foi selecionada;
- a leitora existe, está ativa e dentro da validade;
- o RCF da leitora é maior que zero.

Nesse modo, ECC vem do dosímetro e RCF vem da leitora. Fang, Fenerg e Base Line
continuam usando a configuração atual dos campos manuais, mesmo quando esse
painel está oculto. ECC e RCF carregados não são editáveis.

O nome sugerido segue:

```text
<dosimeter_id>_<AAAA-MM-DD_HH-mm-ss>.txt
```

Depois de uma conclusão, interrupção ou erro, o campo é preparado novamente
para o próximo código.

## Aquisição, Stop, Erase e Ref Light

- **Start** valida o modo, cria o histórico e inicia a aquisição.
- **Stop** envia o comando de parada, fecha o arquivo e marca a medição como
  `INTERROMPIDO`.
- **Erase** envia o comando de zeramento.
- **Ref Light** mede o integral de luz e mostra esse resultado no cartão de
  dose, preservando o fluxo já existente da leitora.

Falhas de transmissão, recepção ou finalização marcam a medição como `ERRO`
quando já existe um registro em andamento.

## Cálculo da dose

A fórmula preservada pelo projeto é:

```text
Dose = (Soma - Base Line) × RCF × ECC × Fang × Fenerg
```

No modo Manual, todos os coeficientes vêm dos campos. No modo Dosímetro ID, ECC
e RCF vêm do banco. O resultado e uma cópia de todos os coeficientes são salvos
na medição; editar um cadastro depois não altera o histórico antigo.

## Painel de acompanhamento

A parte inferior da tela principal possui três abas:

- **Acquisition**: mostra Count, Current, Light e Dose.
- **Graphics**: gráfico em tempo real com seleção das séries Count, Current e
  Light.
- **Serial Monitor**: apresenta o estado da conexão e o último frame recebido.

Os frames principais processados são:

| Frame | Valor |
|---|---|
| `#L1%A` | Count |
| `#L1%E` | Current |
| `#L1%D` | Light e fechamento da amostra |

## Tela Setup

A tela **Setup** configura os parâmetros enviados ao firmware:

- modo;
- ganho;
- tempo de leitura;
- potência;
- tempo de zeramento;
- potência de zeramento.

Campos de um dígito e tempos de até cinco dígitos são validados antes de montar
o comando serial.

## Banco de dados

O banco é criado automaticamente em:

```text
assets/database/measurements.sqlite3
```

As conexões habilitam:

- `PRAGMA foreign_keys = ON`;
- `PRAGMA journal_mode = WAL`;
- `PRAGMA busy_timeout = 10000`.

O esquema é versionado com `PRAGMA user_version` e a tabela
`schema_versions`.

### Tabela `dosimeters`

| Coluna | Conteúdo |
|---|---|
| `dosimeter_id` | texto com exatamente 10 dígitos |
| `ecc` | fator maior que zero |
| `begin_date` | início da validade |
| `end_date` | fim opcional da validade; vazio significa sem data final |
| `active` | `1` ativo ou `0` inativo |
| `created_at`, `updated_at` | auditoria em UTC |

### Tabela `readers`

| Coluna | Conteúdo |
|---|---|
| `reader_id` | identificação textual única |
| `rcf` | fator maior que zero |
| `begin_date` | início da validade |
| `end_date` | fim opcional da validade |
| `active` | `1` ativa ou `0` inativa |
| `created_at`, `updated_at` | auditoria em UTC |

### Tabela `measurements`

Cada linha representa uma aquisição e contém:

- data/hora UTC;
- modo Manual ou Dosímetro ID;
- leitora e dosímetro quando aplicáveis;
- nome e caminho do arquivo;
- Count, Current, Light e Dose;
- snapshots de ECC, RCF, Fang, Fenerg e Base Line;
- status e observação;
- datas de criação e atualização.

Os status possíveis são `EM_ANDAMENTO`, `CONCLUIDO`, `INTERROMPIDO` e `ERRO`.
Chaves estrangeiras impedem apagar cadastros usados no histórico; a interface
usa ativação e desativação.

## Cadastros na tela Banco de dados

### Aba Dosímetros

- **Novo** limpa o formulário.
- **Salvar** cadastra ou atualiza o item selecionado.
- **Ativar/Desativar** muda a disponibilidade sem apagar o histórico.
- **Pesquisar** filtra pelo ID.
- Clicar em um resultado carrega o registro para edição.

Datas podem ser digitadas como `dd/mm/aaaa`. A data final é opcional para
dosímetros e leitoras; quando vazia, a validade permanece aberta.

### Aba Leitoras

O fluxo é equivalente ao de dosímetros. `End Date` pode ficar vazio, o que
representa validade sem data final.

### Aba Histórico

É possível filtrar por:

- Dosímetro ID;
- leitora;
- modo de teste;
- data inicial;
- data final.

Ao clicar em uma medição, a tela mostra os quatro valores, os cinco parâmetros
aplicados, caminho do arquivo e observação.

## Exportação CSV

O botão **Exportar CSV** exporta exatamente os resultados do filtro atual para:

```text
assets/exports/measurements_<data_hora>.csv
```

O arquivo usa `UTF-8 com BOM`, compatível com a abertura direta no Excel, e
inclui os dados da medição e os parâmetros aplicados.

## Backup SQLite

O botão **Exportar backup do banco** abre um seletor de destino iniciado em:

```text
assets/backups
```

O nome sugerido é:

```text
measurements_backup_<AAAA-MM-DD_HH-mm-ss>.sqlite3
```

O backup usa `sqlite3.Connection.backup()`, adequado ao modo WAL, e executa
`PRAGMA integrity_check` antes de confirmar o arquivo. Um destino existente não
é sobrescrito silenciosamente.

## Arquivos de medição

Os `.txt` são gravados em:

```text
assets/testes/AAAA/MM/DD/<nome>.txt
```

Formato:

```text
30/07/2026 15:30:00
exemplo.txt
Soma: 3469
Dose: 0.114
Time;Count;Current;Light
0.1;1733;45;471
0.2;1736;45;470
```

O arquivo é criado com modo exclusivo. Se já existir, a aquisição não o
sobrescreve e o operador recebe uma mensagem de erro.

## Tela Gráficos

1. Abra a área **Gráficos** na barra lateral.
2. Navegue pela árvore de `assets/testes`.
3. Opcionalmente filtre por data.
4. Selecione um `.txt`.
5. Marque Count, Current e/ou Light.
6. Clique em **Gerar gráfico**.
7. Use **Exportar CSV** para converter o log selecionado.

O parser suporta o formato atual separado por `;` e formatos históricos. Linhas
parciais com quantidade divergente de colunas são ignoradas.

## Simulador sem hardware

O simulador usa a porta `COM6`. Com um par virtual `COM5 ↔ COM6`:

1. Execute `simulacao\rodar_simulador.bat`.
2. Abra a interface.
3. Selecione `COM5`.
4. Clique em **Connect** e depois em **Start**.

Para outro par de portas, altere `PORTA_SERIAL` no início de
`simulacao/simulador_osl.py`.

## Estrutura do projeto

```text
Interface_Leitora/
├── interface_OSL.py
├── interface_OSL.kv
├── database.py
├── measurement_workflow.py
├── Plot_grafico.py
├── OSLMeter.spec
├── requirements.txt
├── conversor/
│   ├── __init__.py
│   └── log_parser.py
├── simulacao/
│   ├── simulador_osl.py
│   ├── rodar_simulador.bat
│   └── README.md
├── tests/
│   ├── test_database.py
│   ├── test_interface_modes.py
│   └── test_measurement_workflow.py
└── assets/
    ├── UI/
    ├── database/
    ├── backups/
    ├── exports/
    ├── log/
    └── testes/AAAA/MM/DD/
```

Responsabilidades:

- `interface_OSL.py`: telas, serial, fluxo da aquisição e integração.
- `interface_OSL.kv`: layout e estados visuais.
- `database.py`: esquema, validações, CRUD, histórico, CSV e backup.
- `measurement_workflow.py`: nome seguro, texto do scanner e fórmula da dose.
- `Plot_grafico.py`: geração do gráfico.
- `conversor/log_parser.py`: leitura do `.txt` e conversão para CSV.

## Testes

Os testes usam diretórios temporários e não escrevem no banco real:

```powershell
cd Interface_Leitora
python -m unittest discover -s tests -v
```

Eles cobrem esquema idempotente, rollback, CRUD, validade, snapshots,
persistência, filtros, CSV, backup, segurança do nome do arquivo, troca visual
dos modos, foco do código de barras, consulta por Enter, aquisição serial
simulada e interrupção por Stop.

## Empacotamento

Com PyInstaller instalado:

```powershell
pyinstaller OSLMeter.spec
```

O arquivo `.spec` inclui `interface_OSL.kv` e `assets`. Os módulos Python
importados são detectados durante a análise. No executável, os caminhos são
resolvidos a partir de `sys._MEIPASS`.

## Solução de problemas

- **Start desabilitado no modo Dosímetro ID**: confira se o ID tem 10 dígitos,
  a leitora foi selecionada e ambos os cadastros estão ativos e dentro da
  validade. O Enter pode ser usado para validar o código, mas não é obrigatório
  quando os campos já estão preenchidos.
- **Arquivo já existe**: informe outro nome no modo Manual ou aguarde um novo
  segundo para gerar outro nome automático.
- **Nenhuma porta serial encontrada**: conecte o equipamento ou crie o par de
  portas virtuais e clique em Refresh.
- **Banco ocupado**: a aplicação espera até 10 segundos; verifique se outra
  instância está escrevendo no mesmo arquivo.
- **Layout sobreposto**: reinicie a versão atual; a janela tem tamanho mínimo
  de `900 × 650` e as telas acompanham explicitamente o `ScreenManager`.
