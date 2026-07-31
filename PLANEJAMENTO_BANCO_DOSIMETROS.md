# Planejamento — banco de dosímetros, leitoras e modos de teste

## 1. Objetivo

Adicionar à Interface Leitora OSL um banco local em **Python + SQLite** para:

- cadastrar, pesquisar, editar e desativar dosímetros;
- cadastrar, pesquisar, editar e desativar leitoras;
- executar testes no modo **Manual** ou no modo **Dosímetro ID**;
- calcular a dose com os coeficientes corretos de cada modo;
- salvar o histórico das leituras sem alterar os valores recebidos;
- manter o arquivo SQLite dentro de `assets`;
- exportar uma cópia completa do banco para backup;
- permitir exportação do histórico para CSV.

Este documento descreve somente o planejamento. A implementação de
`database.py`, das telas e dos testes será realizada em uma etapa posterior.

## 2. Decisões da primeira versão

Para seguir o formato definido em `GUIA_BANCO_SQLITE_PYTHON.md`, a primeira
versão adotará as seguintes regras:

- haverá somente um campo `ECC` no cadastro do dosímetro;
- haverá somente um campo `RCF` no cadastro da leitora;
- não serão criados campos `Hp(10)` ou `Hp(0,07)`;
- o ID do dosímetro será texto com exatamente 10 dígitos;
- os identificadores serão armazenados como texto para preservar zeros à
  esquerda;
- dosímetros e leitoras com histórico não serão apagados: serão desativados;
- datas serão armazenadas em ISO 8601 e horários em UTC;
- as quatro grandezas da leitura serão armazenadas sem conversão automática:
  `Count (0.1s)`, `Current (mA)`, `Light (mV)` e `Dose (mSv)`;
- o banco será local e não dependerá de Java, MySQL ou servidor externo;
- `database.py` concentrará a persistência e as validações do banco, enquanto a
  tela Kivy apenas chamará seus métodos.

O modelo com várias versões históricas de ECC e RCF fica fora da primeira
versão. Para preservar a rastreabilidade, cada leitura guardará uma cópia dos
coeficientes efetivamente aplicados. Assim, editar um cadastro futuramente não
modificará uma dose antiga.

## 3. Arquivos e pastas planejados

```text
Interface_Leitora/
├── database.py
├── interface_OSL.py
├── interface_OSL.kv
└── assets/
    ├── database/
    │   └── measurements.sqlite3
    ├── backups/
    └── testes/
```

### 3.1 Banco principal

O caminho padrão será:

```text
assets/database/measurements.sqlite3
```

O diretório e o arquivo serão criados automaticamente somente quando a
implementação for inicializada pela aplicação.

### 3.2 Arquivos que não devem ser versionados

Planejar a inclusão das seguintes regras no `.gitignore`:

```gitignore
assets/database/*.sqlite3
assets/database/*.sqlite3-shm
assets/database/*.sqlite3-wal
assets/backups/*.sqlite3
```

## 4. Tela de banco de dados

A nova tela de banco de dados será organizada em três áreas.

### 4.1 Dosímetros

Campos do cadastro:

| Campo da tela | Nome interno | Regra |
|---|---|---|
| `Dosímetro ID` | `dosimeter_id` | obrigatório, único, exatamente 10 dígitos |
| `ECC` | `ecc` | número real maior que zero, padrão `1.0` |
| `Data inicial` | `begin_date` | obrigatória |
| `Data final` | `end_date` | obrigatória e não anterior à inicial |
| `Ativo` | `active` | ativo ou inativo |

Ações planejadas:

- **Novo**;
- **Salvar**;
- **Editar**;
- **Ativar/Desativar**;
- **Pesquisar por ID**;
- **Limpar formulário**.

Mensagens mínimas:

- `Dosímetro cadastrado com sucesso`;
- `Dosímetro já cadastrado`;
- `O ID deve conter exatamente 10 dígitos`;
- `ECC deve ser maior que zero`;
- `Dosímetro fora do período de validade`;
- `Dosímetro inativo`.

### 4.2 Leitoras

Campos do cadastro:

| Campo da tela | Nome interno | Regra |
|---|---|---|
| `Reader` | `reader_id` | obrigatório e único |
| `RCF` | `rcf` | número real maior que zero |
| `Begin Date` | `begin_date` | obrigatória |
| `End Date` | `end_date` | opcional e não anterior à inicial |
| `Active` | `active` | ativa ou inativa |

Ações planejadas:

- **Nova**;
- **Salvar**;
- **Editar**;
- **Ativar/Desativar**;
- **Pesquisar por Reader**;
- **Limpar formulário**.

Mensagens mínimas:

- `Leitora cadastrada com sucesso`;
- `Leitora já cadastrada`;
- `RCF deve ser maior que zero`;
- `Leitora fora do período de validade`;
- `Leitora inativa`.

### 4.3 Histórico e manutenção

A tela também deverá permitir:

- filtrar leituras por dosímetro;
- filtrar por leitora;
- filtrar por modo de teste;
- filtrar por intervalo de datas;
- consultar os parâmetros aplicados em uma leitura;
- exportar o resultado filtrado para CSV;
- exportar o banco completo como backup SQLite.

## 5. Modos de execução do teste

A troca de modo será apresentada como duas abas/botões no mesmo padrão visual
das opções `Acquisition`, `Graphics` e `Serial Monitor`:

```text
┌──────────────┬──────────────────┐
│    Manual    │   Dosímetro ID   │
└──────────────┴──────────────────┘
```

Somente o conteúdo do modo selecionado ficará visível. A opção ativa deverá ter
o mesmo destaque visual já usado pela interface, incluindo a linha inferior
colorida.

Os dois modos usarão a mesma aquisição serial, mas terão validações e origem dos
coeficientes diferentes.

### 5.1 Modo Manual

O modo Manual manterá o funcionamento configurável mostrado na referência.

Campos editáveis:

| Campo | Exemplo |
|---|---:|
| `ECC` | `1` |
| `RCF` | `0.000033` |
| `Fang` | `1` |
| `Fenerg` | `1` |
| `Base Line` | `0` |
| `File Name` | definido pelo operador |

Fluxo:

1. O operador abre a aba **Manual**.
2. A área abaixo das abas mostra e habilita:
   - `ECC`;
   - `RCF`;
   - `Fang`;
   - `Fenerg`;
   - `Base Line`;
   - `File Name`.
3. Antes do Start, todos os valores são convertidos para números e validados.
4. A dose é calculada com os valores digitados.
5. A leitura é salva com `test_mode = MANUAL`.
6. O banco grava uma cópia de todos os parâmetros aplicados.
7. O arquivo `.txt` continua sendo salvo em `assets/testes`.

No modo Manual, o dosímetro não é obrigatório. Se um ID cadastrado for
informado opcionalmente, ele poderá ser associado ao histórico, mas seus
coeficientes não substituirão os valores digitados.

### 5.2 Modo Dosímetro ID

Este modo será usado para uma leitura vinculada a um dosímetro já cadastrado.

Fluxo:

1. O operador abre a aba **Dosímetro ID**.
2. Os campos manuais são ocultados e a área abaixo das abas mostra o campo
   `Dosímetro ID`.
3. Assim que a aba é aberta, o campo `Dosímetro ID` recebe foco
   automaticamente e o cursor permanece pronto para a leitura do código de
   barras.
4. O leitor de código de barras funciona como teclado, preenchendo o campo com
   os 10 dígitos.
5. O caractere `Enter` enviado pelo leitor confirma o código e executa a
   pesquisa no banco.
6. A aplicação remove espaços e caracteres de controle antes da validação, mas
   não remove ou altera nenhum dos 10 dígitos.
7. A aplicação pesquisa o dosímetro no banco.
8. O Start somente é liberado se o dosímetro:
   - existir;
   - estiver ativo;
   - estiver dentro do período de validade;
   - possuir `ECC` válido.
9. A aplicação identifica a leitora selecionada/conectada.
10. O Start somente é liberado se a leitora:
   - existir;
   - estiver ativa;
   - estiver dentro do período de validade;
   - possuir `RCF` válido.
11. A interface carrega o `ECC` do dosímetro e o `RCF` da leitora.
12. `ECC` e `RCF` ficam bloqueados para edição manual nesse modo.
13. A dose é calculada com os valores carregados do banco.
14. A leitura é salva com `test_mode = DOSIMETER_ID`, `dosimeter_id` e
    `reader_id`.
15. O histórico grava uma cópia de todos os parâmetros efetivamente usados.

Após uma leitura válida, inválida ou cancelada, a interface deverá:

- limpar o campo quando for necessário receber o próximo dosímetro;
- devolver o foco automaticamente ao campo `Dosímetro ID`;
- manter o cursor ativo sem exigir clique do operador;
- selecionar todo o conteúdo anterior quando a intenção for substituí-lo por
  uma nova leitura;
- não iniciar o teste automaticamente apenas por receber o código;
- exigir o botão **Start** depois que o cadastro e a leitora forem validados.

Se o operador clicar em outro controle da tela, o foco poderá mudar
normalmente. Ao retornar à aba **Dosímetro ID**, o foco será recuperado
automaticamente no próximo ciclo da interface Kivy, garantindo que o widget já
esteja visível antes de solicitar o foco.

Mensagens mínimas:

- `Dosímetro não cadastrado`;
- `Dosímetro inativo`;
- `Dosímetro fora do período de validade`;
- `Leitora não cadastrada`;
- `Leitora inativa`;
- `Leitora fora do período de validade`;
- `ECC ou RCF inválido`;
- `Selecione uma leitora antes de iniciar`.

### 5.3 Fang, Fenerg e Base Line no modo Dosímetro ID

O cadastro definido no guia fornece:

- `ECC` pelo dosímetro;
- `RCF` pela leitora.

`Fang`, `Fenerg` e `Base Line` não pertencem aos cadastros descritos no guia.
Para a primeira versão planejada, eles continuarão vindo da configuração atual
da tela, mas serão gravados como cópia na leitura.

Se for exigido que **todos** os parâmetros do modo Dosímetro ID venham
exclusivamente do banco, será necessário acrescentar uma área de
`Perfil de cálculo` antes da implementação. Essa decisão não deve ser tomada
implicitamente dentro de `database.py`.

## 6. Cálculo da dose

A fórmula atual será preservada:

```text
Dose = (Soma - Base Line) × RCF × ECC × Fang × Fenerg
```

Origem dos valores:

| Parâmetro | Modo Manual | Modo Dosímetro ID |
|---|---|---|
| `ECC` | campo da tela | cadastro do dosímetro |
| `RCF` | campo da tela | cadastro da leitora |
| `Fang` | campo da tela | configuração atual da tela |
| `Fenerg` | campo da tela | configuração atual da tela |
| `Base Line` | campo da tela | configuração atual da tela |
| `File Name` | definido pelo operador | automático ou editável conforme regra da interface |

O banco não recalculará a dose ao consultar o histórico. Ele armazenará o
resultado calculado e os parâmetros aplicados.

## 7. Modelo de dados planejado

### 7.1 Tabela `dosimeters`

| Coluna | Tipo | Regra |
|---|---|---|
| `dosimeter_id` | `TEXT` | chave primária, exatamente 10 dígitos |
| `ecc` | `REAL` | obrigatório e maior que zero |
| `begin_date` | `TEXT` | data ISO |
| `end_date` | `TEXT` | data ISO |
| `active` | `INTEGER` | `0` ou `1` |
| `created_at` | `TEXT` | data/hora UTC |
| `updated_at` | `TEXT` | data/hora UTC |

### 7.2 Tabela `readers`

| Coluna | Tipo | Regra |
|---|---|---|
| `reader_id` | `TEXT` | chave primária |
| `rcf` | `REAL` | obrigatório e maior que zero |
| `begin_date` | `TEXT` | data ISO |
| `end_date` | `TEXT` | data ISO ou `NULL` |
| `active` | `INTEGER` | `0` ou `1` |
| `created_at` | `TEXT` | data/hora UTC |
| `updated_at` | `TEXT` | data/hora UTC |

### 7.3 Tabela `measurements`

Cada registro representa uma leitura completa.

| Coluna | Tipo | Regra |
|---|---|---|
| `id` | `INTEGER` | chave primária automática |
| `measured_at` | `TEXT` | data/hora UTC |
| `test_mode` | `TEXT` | `MANUAL` ou `DOSIMETER_ID` |
| `reader_id` | `TEXT` | obrigatório no modo Dosímetro ID |
| `dosimeter_id` | `TEXT` | obrigatório no modo Dosímetro ID |
| `file_name` | `TEXT` | nome lógico do arquivo de teste |
| `file_path` | `TEXT` | caminho do `.txt`, quando existir |
| `count_01s` | `INTEGER` | `Count (0.1s)` |
| `current_ma` | `REAL` | `Current (mA)` |
| `light_mv` | `REAL` | `Light (mV)` |
| `dose_msv` | `REAL` | `Dose (mSv)` |
| `ecc_applied` | `REAL` | cópia do ECC usado |
| `rcf_applied` | `REAL` | cópia do RCF usado |
| `fang_applied` | `REAL` | cópia do Fang usado |
| `fenerg_applied` | `REAL` | cópia do Fenerg usado |
| `baseline_applied` | `REAL` | cópia da Base Line usada |
| `status` | `TEXT` | `EM_ANDAMENTO`, `CONCLUIDO`, `INTERROMPIDO` ou `ERRO` |
| `notes` | `TEXT` | observação opcional |
| `created_at` | `TEXT` | data/hora UTC |
| `updated_at` | `TEXT` | data/hora UTC |

Regras condicionais:

- `DOSIMETER_ID` exige `dosimeter_id` e `reader_id`;
- `MANUAL` permite `dosimeter_id` nulo;
- os quatro valores recebidos da leitura não podem ser negativos;
- os parâmetros aplicados não serão atualizados quando um cadastro mudar;
- `dosimeter_id` e `reader_id` usarão chaves estrangeiras;
- exclusões que quebrariam o histórico serão bloqueadas.

### 7.4 Índices

Planejar pelo menos:

```text
INDEX measurements(measured_at)
INDEX measurements(dosimeter_id, measured_at)
INDEX measurements(reader_id, measured_at)
INDEX measurements(test_mode, measured_at)
```

## 8. Responsabilidades planejadas para `database.py`

`database.py` será responsável por:

- resolver o caminho do banco dentro de `assets/database`;
- criar as pastas necessárias;
- abrir conexões SQLite;
- habilitar `foreign_keys`, `WAL` e `busy_timeout`;
- criar e versionar o esquema;
- controlar `commit` e `rollback`;
- validar e normalizar IDs, números e datas;
- cadastrar, consultar, editar e desativar dosímetros;
- cadastrar, consultar, editar e desativar leitoras;
- obter um dosímetro ativo e válido para o teste;
- obter uma leitora ativa e válida para o teste;
- iniciar, concluir ou interromper uma leitura;
- pesquisar o histórico;
- exportar resultados para CSV;
- criar backup consistente com a API de backup do SQLite.

Interface prevista da classe:

```python
Database()

register_dosimeter(...)
get_dosimeter(...)
search_dosimeters(...)
update_dosimeter(...)
set_dosimeter_active(...)

register_reader(...)
get_reader(...)
search_readers(...)
update_reader(...)
set_reader_active(...)

get_valid_dosimeter_for_test(...)
get_valid_reader_for_test(...)
add_measurement(...)
search_measurements(...)
get_measurement(...)

export_csv(...)
backup(...)
```

Não será responsabilidade de `database.py`:

- desenhar widgets Kivy;
- acessar diretamente campos da tela;
- ler a porta serial;
- escolher sozinho o nome do arquivo;
- alterar unidades;
- inventar parâmetros ausentes;
- recalcular resultados históricos.

## 9. Integração planejada com a interface

### 9.1 Ao trocar o modo

**Manual**

- destacar visualmente a aba Manual;
- mostrar e habilitar `ECC`, `RCF`, `Fang`, `Fenerg`, `Base Line` e
  `File Name`;
- ocultar a área de captura por código de barras;
- tornar o Dosímetro ID opcional;
- indicar visualmente que os valores são manuais.

**Dosímetro ID**

- destacar visualmente a aba Dosímetro ID;
- ocultar os campos manuais e o campo `File Name` manual;
- mostrar o campo de captura do código de barras;
- posicionar o cursor automaticamente nesse campo;
- aceitar os 10 dígitos e o `Enter` enviados pelo leitor;
- exigir o ID com 10 dígitos;
- carregar e exibir os dados do cadastro;
- bloquear edição de `ECC` e `RCF`;
- exibir o Reader utilizado;
- bloquear Start enquanto houver erro de cadastro ou validade.

Estado visual sugerido para o modo Dosímetro ID:

```text
┌──────────────┬──────────────────┐
│    Manual    │   Dosímetro ID   │  ← aba ativa destacada
└──────────────┴──────────────────┘

Dosímetro ID
┌─────────────────────────────────┐
│ |                               │  ← foco e cursor automáticos
└─────────────────────────────────┘

Status: Aguardando leitura do código de barras
```

### 9.2 Ao iniciar

1. Validar campos conforme o modo.
2. Criar o registro com status `EM_ANDAMENTO`.
3. Gerar/iniciar o arquivo `.txt`.
4. Enviar o comando à leitora.
5. Receber os valores sem conversão de unidade.

### 9.3 Ao finalizar

1. Calcular a dose uma única vez com os parâmetros aplicados.
2. Gravar `Count`, `Current`, `Light` e `Dose`.
3. Gravar o caminho do arquivo.
4. Alterar o status para `CONCLUIDO`.
5. Em Stop ou falha, usar `INTERROMPIDO` ou `ERRO`.

## 10. Nome do arquivo

No modo Manual, `File Name` será configurável e obrigatório.

Validações planejadas:

- remover espaços apenas no início e no fim;
- rejeitar caracteres inválidos para nomes de arquivo no Windows;
- impedir caminho absoluto digitado no campo;
- impedir `..` para evitar saída da pasta de testes;
- informar antes de sobrescrever um arquivo existente;
- preferencialmente gerar um sufixo de data/hora para evitar colisões.

Sugestão automática para o modo Dosímetro ID:

```text
<dosimeter_id>_<AAAA-MM-DD_HH-mm-ss>.txt
```

## 11. Backup e exportação

### 11.1 Backup completo

A tela terá o botão **Exportar backup do banco**.

Fluxo:

1. O operador escolhe a pasta de destino.
2. A aplicação sugere:

```text
measurements_backup_<AAAA-MM-DD_HH-mm-ss>.sqlite3
```

3. `database.py` usa `sqlite3.Connection.backup()`.
4. O arquivo gerado é validado como um banco SQLite legível.
5. A interface mostra o caminho final.

Não se deve copiar manualmente apenas o arquivo principal enquanto o banco
estiver aberto em modo WAL.

### 11.2 Exportação CSV

O CSV é uma exportação de consulta, não substitui o backup.

Colunas mínimas:

```text
id
measured_at
test_mode
reader_id
dosimeter_id
file_name
count_01s
current_ma
light_mv
dose_msv
ecc_applied
rcf_applied
fang_applied
fenerg_applied
baseline_applied
status
notes
```

## 12. Segurança e integridade

- usar somente SQL parametrizado;
- habilitar chaves estrangeiras em toda conexão;
- usar transações nas gravações;
- fazer rollback em falhas;
- usar uma conexão por thread;
- não bloquear a thread visual do Kivy com consultas longas;
- validar o nome do arquivo antes de escrever;
- nunca alterar o valor original das quatro grandezas recebidas;
- preservar zeros à esquerda nos identificadores;
- impedir leitura vinculada a cadastro inexistente, inativo ou vencido;
- não apagar cadastros que possuam histórico.

## 13. Etapas futuras de implementação

### Etapa 1 — banco e `database.py`

- criar o caminho em `assets/database`;
- criar tabelas, índices e restrições;
- implementar CRUD de dosímetros e leitoras;
- implementar histórico, CSV e backup;
- criar testes unitários do banco.

**Saída:** camada de persistência validada sem depender da interface.

### Etapa 2 — tela de banco de dados

- criar navegação para Dosímetros, Leitoras e Histórico;
- conectar formulários aos métodos de `database.py`;
- tratar mensagens de sucesso e erro;
- adicionar exportação CSV e backup.

**Saída:** cadastros e manutenção disponíveis pela interface.

### Etapa 3 — modos de teste

- adicionar seletor Manual/Dosímetro ID;
- manter os campos manuais configuráveis;
- carregar ECC e RCF no modo Dosímetro ID;
- controlar campos bloqueados e validação do Start;
- implementar nome automático do arquivo.

**Saída:** os dois modos operam sem misturar a origem dos coeficientes.

### Etapa 4 — histórico e estabilização

- gravar as quatro grandezas e os parâmetros aplicados;
- testar interrupção e perda da serial;
- validar reinício da aplicação;
- validar backup e restauração;
- validar empacotamento.

**Saída:** histórico persistente, auditável e recuperável.

## 14. Testes planejados

- criar automaticamente o banco na primeira inicialização;
- cadastrar dosímetro com 10 dígitos;
- rejeitar ID curto, longo, alfanumérico ou repetido;
- preservar zero à esquerda;
- rejeitar ECC e RCF menores ou iguais a zero;
- rejeitar intervalo de datas inválido;
- cadastrar, editar e desativar uma leitora;
- bloquear Dosímetro ID inexistente, inativo ou vencido;
- bloquear leitora inexistente, inativa ou vencida;
- manter os campos manuais editáveis somente no modo Manual;
- mostrar somente os controles pertencentes à aba selecionada;
- posicionar automaticamente o foco no ID ao abrir Dosímetro ID;
- receber corretamente um código de barras terminado por `Enter`;
- consultar o cadastro após o `Enter` sem iniciar o teste automaticamente;
- recuperar o foco para a leitura do próximo dosímetro;
- carregar ECC e RCF corretos no modo Dosímetro ID;
- comprovar que uma alteração posterior no cadastro não altera a leitura antiga;
- salvar `1733`, `45`, `471` e `474246` sem mudança;
- criar uma leitura diferente a cada Start;
- impedir sobrescrita acidental do arquivo;
- filtrar histórico por ID, leitora, modo e período;
- exportar CSV com as colunas previstas;
- criar e abrir um backup;
- confirmar rollback após erro de gravação;
- confirmar persistência após reiniciar a aplicação.

## 15. Critérios de aceite

A primeira versão será aceita quando:

1. Dosímetros e leitoras puderem ser cadastrados e consultados na nova tela.
2. O banco estiver em `assets/database/measurements.sqlite3`.
3. O modo Manual mantiver todos os parâmetros e o nome de arquivo
   configuráveis.
4. A troca de modo usar abas/botões coerentes com o padrão visual existente.
5. O modo Dosímetro ID abrir com o cursor pronto para o leitor de código de
   barras.
6. O modo Dosímetro ID exigir um dosímetro já cadastrado, ativo e válido.
7. O modo Dosímetro ID carregar `ECC` do dosímetro e `RCF` da leitora.
8. O recebimento do código não iniciar o teste sem confirmação pelo Start.
9. A dose usar os valores correspondentes ao modo selecionado.
10. Cada leitura guardar os coeficientes aplicados e as quatro grandezas.
11. Leituras antigas não mudarem após a edição de um cadastro.
12. O histórico puder ser filtrado e exportado para CSV.
13. O banco completo puder ser exportado para um arquivo de backup.
14. Reiniciar a aplicação não apagar cadastros nem leituras.
15. Nenhum campo novo de `Hp(10)` ou `Hp(0,07)` existir no esquema.

## 16. Pontos a confirmar antes de implementar

1. No modo Dosímetro ID, `Fang`, `Fenerg` e `Base Line` continuarão sendo os
   valores atuais da tela ou deverão vir de um novo perfil salvo no banco?
2. Qual identificação da leitora conectada deve ser usada para localizar o RCF?
3. No modo Manual, a associação opcional a um dosímetro deve ser permitida ou o
   campo ficará totalmente oculto?
4. O nome automático sugerido para o modo Dosímetro ID poderá ser editado?
5. Uma leitura concluída poderá ser excluída ou apenas marcada como cancelada?
6. O backup será salvo por padrão em `assets/backups` ou sempre em uma pasta
   escolhida pelo operador?
