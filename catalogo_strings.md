# Catálogo de strings — Firmware Mega 2560 Controlador V44

Documento gerado a partir das fontes do repositório `Firmware_Mega_2560_Controlador_V44`.

## Escopo

| Arquivo analisado | Conteúdo |
|---|---|
| `Firmware_Mega_2560_Controlador_V44.ino` | Protocolo serial, comandos, estados e telemetria |
| `exibir_lcd.h` | Mensagens exibidas no LCD |
| `serial_event.h` | Leitura e montagem das palavras seriais |

Critérios usados:

- Strings repetidas foram agrupadas em uma única linha, com todas as ocorrências relevantes.
- Os valores abaixo preservam maiúsculas, minúsculas, espaços, zeros e terminadores exatamente como aparecem no código.
- Padrões montados por concatenação foram documentados com o marcador `<valor>`.
- Exemplos existentes somente em comentários estão separados ao final e não são tratados como comandos executados.
- Literais de caractere, como `'&'`, não são strings e foram excluídos das tabelas principais.

## Resumo

| Grupo | Finalidade |
|---|---|
| Comandos do supervisório | Instruções recebidas pelo Mega |
| Comandos SUDO | Operações diretas, ignorando a mecânica |
| Estados do Mega | Informações enviadas ao supervisório |
| Comandos do motor | Posições e ações enviadas ao controlador dos motores |
| Respostas do motor | Confirmações e falhas recebidas do controlador |
| Contador | Controle de início/parada da aquisição |
| Telemetria | Dados de HP10, HP07, tensão, corrente e luz de referência |
| LCD | Textos apresentados ao operador |
| Internas/parsers | Valores temporários, comparações e limpeza de buffers |

## 1. Protocolo serial

### 1.1 Comandos recebidos do supervisório

| Variável | String | Significado | Origem |
|---|---|---|---|
| `Stand_By` | `#S1%C0000&` | Stand-by | `.ino:90` |
| `iniciar` | `#S1%C0001&` | Inicia o processo automático | `.ino:91` |
| `parar` | `#S1%C0010&` | Para o processo | `.ino:92` |
| `autoteste` | `#S1%C0011&` | Executa o autoteste | `.ino:93` |
| `dosimetro_ok` | `#S1%C0100&` | Descarte aprovado | `.ino:94` |
| `dosimetro_n_ok` | `#S1%C0101&` | Descarte não aprovado | `.ino:95` |
| `codigo_lido` | `#S1%C0110&` | Confirma leitura do código de barras | `.ino:96` |
| `ler` | `#S1%C0111&` | Solicita leitura do dosímetro | `.ino:97` |
| `zerar` | `#S1%C1000&` | Solicita zeramento do dosímetro | `.ino:98` |
| `habilitar_botao` | `#S1%C1001&` | Habilita o equipamento/botão | `.ino:99` |
| `desabilitar_botao` | `#S1%C1010&` | Desabilita o equipamento/botão | `.ino:100` |
| `iniciar_modo_zerar` | `#S1%C1011&` | Inicia o modo de zeramento | `.ino:101` |

### 1.2 Comandos SUDO

| Variável | String | Significado | Origem |
|---|---|---|---|
| `SUDO_leitura` | `#S1%SC1001&` | Faz leitura sem passar pela mecânica | `.ino:103` |
| `SUDO_stop` | `#S1%SC1010&` | Para a leitura e desliga o LED sem usar a mecânica | `.ino:104` |
| `SUDO_zerar` | `#S1%SC1011&` | Liga o LED de zeramento sem usar a mecânica | `.ino:105` |
| `SUDO_ligaLed` | `#S1%SC1100&` | Liga o LED de leitura sem usar a mecânica | `.ino:106` |

### 1.3 Estados enviados pelo Mega ao supervisório

| Variável | String | Significado | Origem |
|---|---|---|---|
| `torre_vazia` | `#L1%T0000000&` | Torre vazia | `.ino:108` |
| `standby` | `#L1%I0000000&` | Equipamento em espera | `.ino:109`; também enviado diretamente em `.ino:310` |
| `buscando_origem` | `#L1%I0000001&` | Buscando a posição de origem | `.ino:110` |
| `remo_dos_torre` | `#L1%I0000010&` | Removendo o dosímetro da torre | `.ino:111` |
| `lendo_dos` | `#L1%I0000011&` | Lendo o dosímetro | `.ino:112` |
| `lendo_dose` | `#L1%I0000100&` | Lendo dose | `.ino:113` |
| `fim_leit` | `#L1%I0000101&` | Fim da leitura | `.ino:114` |
| `zerando` | `#L1%I0000110&` | Zerando | `.ino:115` |
| `relendo` | `#L1%I0000111&` | Realizando releitura | `.ino:116` |
| `fim_releit` | `#L1%I0001000&` | Fim da releitura | `.ino:117` |
| `ejetando` | `#L1%I0001001&` | Ejetando | `.ino:118` |
| `dos_descartado` | `#L1%I0001010&` | Dosímetro descartado | `.ino:119` |
| `fim_torre` | `#L1%I0001011&` | Fim da operação da torre | `.ino:120` |
| `travamento` | `#L1%I0001100&` | Travamento/falha mecânica | `.ino:121` |
| `parado` | `#L1%I0001101&` | Processo parado | `.ino:122` |
| `botao_start` | `#L1%I0001110&` | Botão de início acionado | `.ino:123` |
| `botao_stop` | `#L1%I0001111&` | Botão de parada acionado | `.ino:124` |
| `fim_hp10` | `#L1%I0010000&` | Fim da leitura HP10 | `.ino:125` |
| `fim_hp007` | `#L1%I0010001&` | Fim da leitura HP07 | `.ino:126` |
| `time_out_super_p` | `#L1%I0010010&` | Timeout do supervisório | `.ino:127` |
| `id_maquina` | `#L1%R3001A01&` | Identificação da máquina | `.ino:128` |

> `id_maquina` contém o modelo `3001A` e o número de série `01` no valor atualmente gravado no firmware.

### 1.4 Estados relacionados aos motores

| Variável | String | Significado | Origem |
|---|---|---|---|
| `motores_bem` | `#L1%M0000000&` | Motores em condição normal | `.ino:130` |
| `mtr_torre_travado` | `#L1%M0000001&` | Motor da torre travado | `.ino:131` |
| `mtr_pista_travado` | `#L1%M0000010&` | Motor da pista travado | `.ino:132` |
| `mtr_leit_travado` | `#L1%M0000100&` | Motor de leitura travado | `.ino:133` |

### 1.5 Comandos enviados ao controlador dos motores

| Variável | String | Significado | Origem |
|---|---|---|---|
| `origem` | `#C1%C000&` | Move para a origem | `.ino:135` |
| `dos_fora_torre` | `#C1%C001&` | Posiciona fora da torre/HP10 | `.ino:136` |
| `HP10` | `#C1%C010&` | Posiciona em HP10 | `.ino:137` |
| `HP07` | `#C1%C011&` | Posiciona em HP07 | `.ino:138` |
| `zeramento` | `#C1%C100&` | Posiciona para zeramento | `.ino:139` |
| `descarte_ok` | `#C1%C101&` | Posiciona para descarte aprovado | `.ino:140` |
| `descarte_n_ok` | `#C1%C110&` | Posiciona para descarte não aprovado | `.ino:141` |
| `max_corrente` | `#C1%C111&` | Solicita a corrente máxima do autoteste | `.ino:142` |
| `descrt_n_ok_desacoplado` | `#C1%C112&` | Solicita corrente máxima no descarte desacoplado | `.ino:143` |

### 1.6 Respostas recebidas do controlador dos motores

| Variável | String | Significado | Origem |
|---|---|---|---|
| `sucesso_pos` | `#PM%00&` | Posicionamento realizado com sucesso | `.ino:145` |
| `falha_pos` | `#PM%01&` | Falha no posicionamento | `.ino:146` |
| `sem_dosimetro` | `#PM%10&` | Sem dosímetro | `.ino:147` |
| `com_dosimetro` | `#PM%11&` | Com dosímetro | `.ino:148` |
| `falha_motor_torre` | `#PM%MT&` | Falha no motor da torre | `.ino:149` |
| `falha_motor_pista` | `#PM%MP&` | Falha no motor da pista | `.ino:150` |
| `falha_motor_leit` | `#PM%ML&` | Falha no motor de leitura | `.ino:151` |

### 1.7 Controle do contador

| String | Uso | Ocorrências |
|---|---|---|
| `start&` | Inicia aquisição no contador | `.ino:719-721`, `840-841`, `760-761`, `1219-1220`, `1233-1234`, `1288-1289`, `1302-1303` |
| `stop&` | Para aquisição no contador | `.ino:741-742`, `752-753`, `768-769`, `861-862`, `884-885`, `1210-1211`, `1224-1225`, `1279-1280`, `1293-1294` |

### 1.8 Telemetria montada dinamicamente

O firmware preenche zeros à esquerda, concatena o valor medido e termina o pacote com `&`. Os trechos abaixo são os literais presentes no código.

| Função | Prefixos literais encontrados | Resultado lógico | Origem |
|---|---|---|---|
| `exibirDadosHP10` | `#L1%A00000000`, `#L1%A0000000`, `#L1%A000000`, `#L1%A00000`, `#L1%A0000`, `#L1%A000`, `#L1%A00`, `#L1%A0`, `#L1%A` | `#L1%A` + valor HP10 com 9 posições + `&` | `.ino:1241-1257` |
| `exibirDadosHP07` | `#L1%B00000000`, `#L1%B0000000`, `#L1%B000000`, `#L1%B00000`, `#L1%B0000`, `#L1%B000`, `#L1%B00`, `#L1%B0`, `#L1%B` | `#L1%B` + valor HP07 com 9 posições + `&` | `.ino:1310-1326` |
| `exibir_VPMT` | `#L1%V000000`, `#L1%V00000`, `#L1%V0000`, `#L1%V000`, `#L1%V00`, `#L1%V0`, `#L1%V` | `#L1%V` + tensão PMT com 7 posições + `&` | `.ino:1339-1351` |
| `exibir_VPMT` — saturação | `#L1%VsatLeit&` | Indica saturação da leitura de tensão PMT | `.ino:1353` |
| `exibir_corrente_LED_leit` | `#L1%E000000`, `#L1%E00000`, `#L1%E0000`, `#L1%E000`, `#L1%E00`, `#L1%E0`, `#L1%E` | `#L1%E` + corrente do LED de leitura com 7 posições + `&` | `.ino:1362-1374` |
| `exibir_corrente_LED_leit` — saturação | `#L1%EsatLeit&` | Indica saturação da corrente do LED de leitura | `.ino:1376` |
| `exibir_corrente_LED_zeramento` | `#L1%F000000`, `#L1%F00000`, `#L1%F0000`, `#L1%F000`, `#L1%F00`, `#L1%F0`, `#L1%F` | `#L1%F` + corrente do LED de zeramento com 7 posições + `&` | `.ino:1385-1397` |
| `exibir_corrente_LED_zeramento` — saturação | `#L1%FsatLeit&` | Indica saturação da corrente do LED de zeramento | `.ino:1399` |
| `exibir_luz_referencia` | `#L1%L000000`, `#L1%L00000`, `#L1%L0000`, `#L1%L000`, `#L1%L00`, `#L1%L0`, `#L1%L` | `#L1%L` + luz de referência com 7 posições + `&` | `.ino:1407-1419` |
| `exibir_luz_referencia` — saturação | `#L1%LsatLeit&` | Indica saturação da luz de referência | `.ino:1421` |

## 2. Strings exibidas no LCD

| String | Uso/expressão | Ocorrências |
|---|---|---|
| `Time out contador` | Timeout do contador | `exibir_lcd.h:143` |
| `Reinitiate!` | Solicitação de reinicialização | `exibir_lcd.h:145`, `153`, `205` |
| `Time out, PC` | Timeout de comunicação com o PC | `exibir_lcd.h:151` |
| `Vpmt:` | Rótulo da tensão PMT | `exibir_lcd.h:161` |
| `Initializing...` | Inicialização do equipamento | `exibir_lcd.h:170` |
| `RADinstruments` | Identificação da empresa | `exibir_lcd.h:177` |
| `Press Start/Stop` | Aguarda o botão iniciar/parar | `exibir_lcd.h:187` |
| `Connect Software` | Aguarda conexão com o software | `exibir_lcd.h:196` |
| `Dosimeter ` | Prefixo do número do dosímetro | `exibir_lcd.h:220`, `230`, `241`, `334`, `382`, `429`, `467` |
| ` %` | Sufixo da porcentagem do processo | `exibir_lcd.h:222`, `232`, `243` |
| `OK` | Dosímetro aprovado | `exibir_lcd.h:234` |
| `Er` | Dosímetro reprovado | `exibir_lcd.h:245` |
| `Process` | Primeira linha de processo concluído | `exibir_lcd.h:252`, `452` |
| `Finished` | Segunda linha de processo concluído | `exibir_lcd.h:254`, `454` |
| `Lumideteck 3001A` | Identificação do equipamento | `exibir_lcd.h:264` |
| `Autotest` | Tela de autoteste | `exibir_lcd.h:271` |
| `Reference Light` | Primeira linha de falha de luz de referência | `exibir_lcd.h:277` |
| `Failure` | Segunda linha de falha | `exibir_lcd.h:279`, `288` |
| `Mechanical` | Primeira linha de falha mecânica | `exibir_lcd.h:286` |
| `Autotest OK` | Autoteste aprovado | `exibir_lcd.h:295` |
| `%` | Símbolo impresso após a porcentagem | `exibir_lcd.h:323`, `401` |
| `0` | Zero à esquerda do número do dosímetro | `exibir_lcd.h:336`, `384`, `431`, `469` |
| `HP07: ` | Rótulo da leitura HP07 | `exibir_lcd.h:340` |
| `0.00` | Valor inicial/modelo de leitura HP07 e HP10 | `exibir_lcd.h:341`, `345` |
| ` uSv` | Unidade de dose | `exibir_lcd.h:342`, `346` |
| `HP10: ` | Rótulo da leitura HP10 | `exibir_lcd.h:344` |
| `Erasing...` | Zeramento em andamento | `exibir_lcd.h:360` |
| `Erasing` | Zeramento em andamento/concluído | `exibir_lcd.h:366`, `388` |
| `Completed` | Zeramento concluído | `exibir_lcd.h:368` |
| `Checking...` | Verificação em andamento | `exibir_lcd.h:374` |
| `Reading` | Leitura em andamento | `exibir_lcd.h:443`, `473` |

As expressões abaixo combinam strings fixas com valores calculados:

| Expressão | Resultado |
|---|---|
| `"Dosimeter " + String(contador_dosimetro)` | Número do dosímetro atual |
| `String((contador_dosimetro - 1) * 3.448276, 0) + " %"` | Percentual do processo de leitura |
| `String((contador_dosimetro - 1) * 3.33, 0) + " %"` | Percentual no resultado OK/NOK |

## 3. Strings internas e de parsing

### 3.1 String vazia

O literal `""` é usado para inicializar ou limpar buffers e variáveis temporárias.

| Uso | Ocorrências |
|---|---|
| Inicialização de `tempoLeituraAux`, `tipoLEDAux`, `potenciaLEDLAux`, `potenciaLEDZAux`, `modoLEDAux` e `zeramentoAux` | `.ino:162`, `164-165`, `167`, `169`, `173` |
| Limpeza de `palavra_3` | `.ino:283`, `288`, `292`, `1635` |
| Limpeza de `dado` | `.ino:749`, `875` |
| Limpeza de `palavra` | `.ino:1594` |
| Impressão vazia em código comentado | `.ino:1611` |

### 3.2 Comparações e controles

| String | Uso | Ocorrências |
|---|---|---|
| `4` | Verifica potência máxima do LED antes de tratar saturação | `.ino:1207`, `1276` |
| `M` | Identifica uma palavra de configuração de parâmetros | `.ino:1543` |

## 4. Literais presentes somente em comentários

Os itens desta seção aparecem no código como documentação, exemplos ou trechos desativados. Eles não são enviados enquanto permanecerem comentados.

| String/exemplo | Finalidade | Origem |
|---|---|---|
| `#S1%M1G3L03000P4Z05000Q2&` | Exemplo de configuração automática | `.ino:37` |
| `#S1%M1G3L03000P4Z01000Q4&` | Configuração da sequência automática | `.ino:40` |
| `#S1%M1G3L30000P4Z30000Q2&` | Configuração automática com botão | `.ino:49` |
| `#S1%C1001&` | Habilitação do início/botão nos exemplos | `.ino:41`, `50` |
| `#S1%C0001&` | Início do processo no exemplo | `.ino:42` |
| `#S1%C0110&` | Confirmação da leitura do código de barras | `.ino:43`, `52` |
| `#S1%C1000&` | Zeramento nos exemplos | `.ino:44`, `53`, `387`, `397`, `406` |
| `#S1%C0100&` | Descarte aprovado nos exemplos | `.ino:45`, `54` |
| `#S1%C0101&` | Descarte não aprovado nos exemplos | `.ino:46`, `55` |
| `#S1%M3G3L03000P2Z03000Q4&` | Configuração de autoteste | `.ino:59` |
| `#S1%C0011&` | Acionamento do autoteste no exemplo | `.ino:59` |
| `#S1%M1G3L60000P4Z01000Q4&` | Configuração de leitura do LED | `.ino:60` |
| `#S1%SC1001&` | Leitura SUDO no exemplo | `.ino:60` |
| `#S1%M3G3L60000P2Z03000Q4&` | Configuração de zeramento | `.ino:61` |
| `#S1%SC1011&` | Zeramento SUDO no exemplo | `.ino:61` |
| `#S1%C1010&` | Parada da leitura no exemplo | `.ino:62` |
| `#S1%Dxxxxxxx&` | Formato documentado para dados de leitura | `.ino:1191`, `1264` |
| `#S1%IsatLeit&` | Exemplo documentado de saturação | `.ino:1192`, `1265` |
| `#S1%IstandBy&` | Exemplo documentado de estado em espera | `.ino:1192`, `1265` |
| `#L1%Vxxxxxx&` | Formato documentado de tensão PMT | `.ino:1333` |
| `#L1%Exxxxxx&` | Formato documentado de corrente do LED | `.ino:1358`, `1381` |
| `#L1%Ixxxxxx&` | Formato documentado de luz de referência | `.ino:1404` |
| `# S 1 % M X G X L X  X   X   X   X   X   P   X   Z   X   X   X   X   X   Q   X   &` | Modelo espaçado de pacote de parâmetros | `.ino:1437` |
| `#S1%MXGXLXXXXXPXZXXXXXQX&` | Modelo compacto de pacote de parâmetros | `.ino:1438` |
| `#S1%M3G3L03000P4Z05000Q2&` | Exemplo de pacote de parâmetros | `.ino:1439` |
| `Ganho: ` | Mensagem de depuração desativada | `.ino:1473` |
| `enviou o comando para o potdig` | Mensagem de depuração desativada | `.ino:1537` |
| `Comando sudo leitura recebido` | Mensagem de depuração desativada | `.ino:417` |
| `--` | Marcadores de depuração no LCD | `.ino:1202`, `1204`, `1271`, `1273` |

## 5. Literais de diretivas, não exibidos nem transmitidos

| Literal | Finalidade | Origem |
|---|---|---|
| `exibir_lcd.h` | Inclui as funções e strings do LCD | `.ino:76` |
| `serial_event.h` | Inclui as funções de leitura serial | `.ino:77` |

## Observações

- O protocolo usa `&` como terminador dos pacotes seriais.
- Os pacotes de telemetria usam preenchimento com zeros à esquerda antes do valor numérico.
- `#L1%I0000000&` aparece como variável `standby` em `.ino:109` e também como literal direto em `.ino:310`.
- Há exemplos comentados com pequenas diferenças em relação aos comandos ativos, como `#S1%C001&` no comentário de `.ino:369`; o comando ativo de autoteste declarado no firmware é `#S1%C0011&`.
- Este catálogo não modifica o firmware; ele apenas documenta os literais encontrados nas fontes.
