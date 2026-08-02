# Prompt de execução — banco de dosímetros e modos de teste

Implemente integralmente o planejamento descrito em:

```text
D:\Interface_Leitora\PLANEJAMENTO_BANCO_DOSIMETROS.md
```

Use também como referência técnica:

```text
D:\Interface_Leitora\Interface_Leitora\GUIA_BANCO_SQLITE_PYTHON.md
```

O planejamento atualizado é a fonte principal de requisitos. Quando houver
diferença entre os documentos, siga o planejamento e use o guia apenas como
referência para SQLite, validações e operações CRUD.

## Objetivo

Evolua a Interface Leitora OSL para:

1. cadastrar e gerenciar dosímetros;
2. cadastrar e gerenciar leitoras;
3. manter o banco SQLite em `assets/database`;
4. disponibilizar os modos de teste **Manual** e **Dosímetro ID**;
5. carregar `ECC` e `RCF` do banco no modo Dosímetro ID;
6. manter os parâmetros configuráveis no modo Manual;
7. salvar o histórico completo das leituras;
8. exportar consultas para CSV;
9. exportar o banco completo para backup.

Não entregue somente exemplos, pseudocódigo ou uma nova proposta. Inspecione o
projeto existente, implemente as alterações nos arquivos reais e valide o
funcionamento.

## Regras de trabalho

- Antes de editar, inspecione a estrutura do projeto, `interface_OSL.py`,
  `interface_OSL.kv`, arquivos auxiliares e testes existentes.
- Preserve funcionalidades existentes que não façam parte desta mudança.
- Preserve o padrão visual atual da interface.
- Não substitua arquivos inteiros quando uma alteração localizada for
  suficiente.
- Não apague alterações preexistentes do usuário.
- Não introduza Java, MySQL, Electron ou servidor de banco.
- Para o banco, use `sqlite3` e módulos da biblioteca padrão do Python.
- Use SQL parametrizado em todas as operações.
- Não execute migração destrutiva de dados existentes.
- Não crie campos `Hp(10)` ou `Hp(0,07)`.
- Não altere unidades nem transforme automaticamente os valores recebidos.
- Registre decisões técnicas relevantes no resumo final.

## Etapa 1 — diagnóstico do projeto

Antes da implementação:

1. Localize a raiz real da aplicação.
2. Identifique como as telas Kivy são declaradas e navegadas.
3. Localize o fluxo atual do botão Start e do botão Stop.
4. Localize os campos atuais:
   - `ECC`;
   - `RCF`;
   - `Fang`;
   - `Fenerg`;
   - `Base Line`;
   - `File Name`.
5. Localize a fórmula atual da dose.
6. Identifique como a leitora conectada é reconhecida.
7. Identifique como e onde os arquivos `.txt` são criados.
8. Verifique os testes automatizados e o comando correto para executá-los.
9. Confirme o caminho correto de `assets` tanto no código-fonte quanto no
   empacotamento atual.

Depois desse diagnóstico, implemente o planejamento. Só interrompa para pedir
informação se existir uma decisão impossível de inferir com segurança a partir
do código.

## Etapa 2 — implementar `database.py`

Crie:

```text
D:\Interface_Leitora\Interface_Leitora\database.py
```

Se a inspeção mostrar que a raiz importável da aplicação é outra, coloque o
arquivo nessa raiz e explique a decisão.

Implemente uma classe `Database` responsável por:

- resolver o caminho do banco;
- criar `assets/database` quando necessário;
- criar `assets/database/measurements.sqlite3`;
- criar e versionar o esquema;
- abrir conexões com:
  - `PRAGMA foreign_keys = ON`;
  - `PRAGMA journal_mode = WAL`;
  - `PRAGMA busy_timeout`;
- controlar transações, commit e rollback;
- normalizar datas e horários;
- validar IDs e valores numéricos;
- realizar CRUD de dosímetros e leitoras;
- impedir exclusões que prejudiquem o histórico;
- salvar e consultar medições;
- exportar consultas para CSV;
- criar backup consistente com `sqlite3.Connection.backup()`.

Implemente pelo menos os métodos previstos no planejamento:

```python
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
get_measurement(...)
search_measurements(...)

export_csv(...)
backup(...)
```

Use os nomes internos, tipos, restrições, chaves estrangeiras e índices
definidos em `PLANEJAMENTO_BANCO_DOSIMETROS.md`.

### Dosímetros

- `dosimeter_id` é texto com exatamente 10 dígitos.
- Preserve zeros à esquerda.
- `ecc` é único por cadastro e maior que zero.
- Valide data inicial, data final, estado ativo e período de validade.
- Um dosímetro com histórico deve ser desativado, não apagado.

### Leitoras

- `reader_id` é texto obrigatório e único.
- `rcf` deve ser maior que zero.
- Valide estado e período de validade.
- A data final pode ser nula.
- Uma leitora com histórico deve ser desativada, não apagada.

### Medições

Salve pelo menos:

- modo do teste;
- data/hora UTC;
- leitora;
- dosímetro, quando aplicável;
- nome e caminho do arquivo;
- `Count (0.1s)`;
- `Current (mA)`;
- `Light (mV)`;
- `Dose (mSv)`;
- cópias de ECC, RCF, Fang, Fenerg e Base Line aplicados;
- status;
- observação;
- datas de criação e atualização.

Alterações futuras nos cadastros não podem modificar os coeficientes de uma
medição antiga.

## Etapa 3 — tela de banco de dados

Crie ou adapte a tela Kivy para oferecer:

### Dosímetros

- novo cadastro;
- pesquisa;
- edição;
- ativação e desativação;
- validação do ID com exatamente 10 dígitos;
- mensagens claras de sucesso e erro.

Campos:

```text
Dosímetro ID
ECC
Data inicial
Data final
Ativo
```

### Leitoras

- novo cadastro;
- pesquisa;
- edição;
- ativação e desativação;
- mensagens claras de sucesso e erro.

Campos:

```text
Reader
RCF
Begin Date
End Date
Active
```

### Histórico e manutenção

- filtros por dosímetro, leitora, modo e período;
- visualização dos parâmetros aplicados;
- exportação CSV;
- botão para exportar backup completo do banco;
- mensagens com o caminho dos arquivos exportados.

Não coloque comandos SQL diretamente nos callbacks dos widgets. A tela deve
usar os métodos de `Database`.

## Etapa 4 — abas Manual e Dosímetro ID

Na área de aquisição, crie duas abas/botões:

```text
┌──────────────┬──────────────────┐
│    Manual    │   Dosímetro ID   │
└──────────────┴──────────────────┘
```

Use o mesmo padrão visual das opções atuais `Acquisition`, `Graphics` e
`Serial Monitor`, inclusive o destaque inferior da opção ativa.

Somente o painel correspondente à aba selecionada deve ficar visível.

### Modo Manual

Mostre e habilite:

```text
ECC
RCF
Fang
Fenerg
Base Line
File Name
```

Requisitos:

- manter os valores configuráveis;
- validar todos antes do Start;
- manter o nome do arquivo configurável;
- calcular a dose com os valores digitados;
- salvar `test_mode = MANUAL`;
- salvar uma cópia dos parâmetros aplicados;
- não exigir Dosímetro ID.

### Modo Dosímetro ID

Mostre o campo:

```text
Dosímetro ID
```

Requisitos de interação:

- ao abrir a aba, o campo deve receber foco automaticamente;
- o cursor deve ficar pronto para o leitor de código de barras;
- considere que o leitor funciona como teclado;
- aceite os 10 dígitos e o `Enter` final enviado pelo leitor;
- ao receber `Enter`, normalize caracteres de controle e consulte o banco;
- não remova, complete ou modifique os 10 dígitos;
- exiba os dados localizados e o estado da validação;
- recupere o foco para o próximo código após leitura, erro ou cancelamento;
- quando apropriado, selecione o conteúdo anterior para permitir substituição;
- se o operador retornar à aba, reagende o foco no próximo ciclo do Kivy;
- receber o código não deve iniciar automaticamente a aquisição;
- o botão Start continua sendo a confirmação para iniciar o teste.

Valide antes de habilitar Start:

- ID com exatamente 10 dígitos;
- dosímetro cadastrado;
- dosímetro ativo;
- dosímetro dentro da validade;
- ECC válido;
- leitora cadastrada;
- leitora ativa;
- leitora dentro da validade;
- RCF válido.

Nesse modo:

- carregue `ECC` do cadastro do dosímetro;
- carregue `RCF` do cadastro da leitora;
- bloqueie a edição manual de ECC e RCF;
- use `Fang`, `Fenerg` e `Base Line` da configuração atual da aplicação;
- salve cópias de todos os valores aplicados;
- use `test_mode = DOSIMETER_ID`;
- vincule `dosimeter_id` e `reader_id`;
- sugira o nome:

```text
<dosimeter_id>_<AAAA-MM-DD_HH-mm-ss>.txt
```

## Etapa 5 — integrar o cálculo e o arquivo

Preserve a fórmula atual:

```text
Dose = (Soma - Base Line) × RCF × ECC × Fang × Fenerg
```

No modo Manual, use os valores digitados.

No modo Dosímetro ID:

- ECC vem do dosímetro;
- RCF vem da leitora;
- Fang, Fenerg e Base Line vêm da configuração atual da tela.

Não recalcule resultados antigos ao abrir o histórico.

Preserve o salvamento dos arquivos `.txt` existentes. Faça apenas as adaptações
necessárias para:

- garantir um nome válido;
- impedir caminhos absolutos e `..`;
- impedir sobrescrita silenciosa;
- associar o caminho à medição;
- manter compatibilidade com `assets/testes`.

## Etapa 6 — backup e exportação

Implemente:

### CSV

- exporte o resultado dos filtros do histórico;
- use codificação compatível com Excel;
- inclua as colunas previstas no planejamento.

### Backup SQLite

- use a API de backup do SQLite;
- sugira o nome:

```text
measurements_backup_<AAAA-MM-DD_HH-mm-ss>.sqlite3
```

- permita escolher o destino;
- use `assets/backups` como destino inicial sugerido;
- valide que o arquivo gerado pode ser aberto como SQLite;
- não faça cópia simples do arquivo principal enquanto estiver aberto em WAL.

## Decisões padrão para esta implementação

Se o código existente não determinar outra regra claramente, adote:

1. `Fang`, `Fenerg` e `Base Line` continuam vindo da configuração atual da tela
   no modo Dosímetro ID.
2. Se a leitora conectada não tiver uma identidade persistente no código,
   apresente um seletor com as leitoras ativas cadastradas.
3. No modo Manual, não exija nem mostre Dosímetro ID.
4. No modo Dosímetro ID, gere o nome do arquivo automaticamente e mostre-o como
   informação não editável.
5. Não permita excluir uma medição concluída pela interface; preserve o
   histórico.
6. O diálogo de backup começa em `assets/backups`, mas permite outro destino.

## Testes obrigatórios

Crie ou atualize testes para cobrir:

- criação automática do banco;
- criação idempotente do esquema;
- dosímetro válido;
- ID inválido ou repetido;
- preservação de zero à esquerda;
- ECC e RCF inválidos;
- datas inválidas;
- ativação e desativação;
- validade do dosímetro e da leitora;
- transação e rollback;
- persistência após reabrir o banco;
- cópia imutável dos parâmetros aplicados;
- gravação exata de `1733`, `45`, `471` e `474246`;
- filtros do histórico;
- exportação CSV;
- criação e abertura do backup;
- alternância visual dos modos;
- visibilidade dos campos de cada modo;
- foco automático no Dosímetro ID;
- captura de 10 dígitos terminada por `Enter`;
- consulta sem Start automático;
- recuperação de foco para o próximo código;
- carregamento de ECC e RCF corretos;
- bloqueio do Start para cadastro inválido;
- nome de arquivo seguro;
- preservação do fluxo serial existente.

Use testes temporários ou bancos em diretórios temporários. Não grave dados de
teste no banco real de `assets`.

## Verificação final

Antes de concluir:

1. Execute a análise sintática dos arquivos Python alterados.
2. Execute os testes existentes e os novos.
3. Inspecione os erros e corrija a causa, não apenas o sintoma.
4. Verifique a interface no ambiente disponível, se for possível executá-la sem
   hardware.
5. Confirme que a inicialização sem leitora conectada não quebra a aplicação.
6. Confirme que nenhum banco ou backup de teste ficou nos dados reais.
7. Revise o diff para garantir que não houve alterações alheias ao escopo.

## Entrega esperada

Ao finalizar, informe:

- arquivos criados e alterados;
- estrutura do banco implementada;
- funcionamento das abas Manual e Dosímetro ID;
- comportamento do leitor de código de barras;
- funcionamento do histórico, CSV e backup;
- testes executados e seus resultados;
- limitações que dependam de hardware;
- decisões ou diferenças necessárias em relação ao planejamento.

Não declare a tarefa concluída se os testes relevantes estiverem falhando ou
se o fluxo principal ainda estiver apenas parcialmente implementado.
