# Diferença entre dose pessoal e background

Este documento explica como o OSLMeter3001A interpreta os valores de dose e de
background armazenados no banco de dados Java/MySQL.

> Observação: o nome correto é **personal dose** (dose pessoal), e não
> “pernosal dose”.

## Resumo

| Conceito | Significado | Tabela no banco | Status típico |
|---|---|---|---|
| **Personal dose** | Sinal associado à exposição do dosímetro durante o período de uso | `historico_dose` | `Need to Erase` |
| **Background dose** | Sinal residual ou de referência do dosímetro depois do apagamento | `historico_branco` | `Ready to Use` |

## 1. Personal dose — dose pessoal

A dose pessoal representa a leitura do dosímetro depois de ele ter sido usado.
Ela é o valor que pode conter a contribuição da exposição à radiação recebida
pelo usuário durante o período de monitoramento.

No banco de dados, essa leitura é registrada na tabela `historico_dose`:

```sql
historico_dose
├── time_dos       -- data e hora da leitura
├── dosimeter_id   -- identificação do dosímetro
├── hp10_dos       -- leitura Hp(10)
├── hp007_dos      -- leitura Hp(0.07)
└── status_dos     -- normalmente "Need to Erase"
```

O status `Need to Erase` indica que o dosímetro apresentou sinal acima da
linha de base e deve ser apagado antes de voltar ao uso.

## 2. Background dose — dose de fundo ou branco

O background, chamado de **branco** no código, é a leitura de referência do
dosímetro após o apagamento. Ele representa o sinal residual do material OSL,
o sinal eletrônico/óptico do sistema e outras contribuições que não devem ser
interpretadas diretamente como dose pessoal do usuário.

No banco, o background é registrado na tabela `historico_branco`:

```sql
historico_branco
├── time_bg        -- data e hora da leitura do branco
├── dosimeter_id   -- identificação do dosímetro
├── hp10_bg        -- background de Hp(10)
├── hp007_bg       -- background de Hp(0.07)
└── status_bg      -- normalmente "Ready to Use"
```

O sistema procura o background mais recente para o mesmo dosímetro:

```sql
SELECT hp10_bg, hp007_bg
FROM historico_branco
WHERE dosimeter_id = ?
ORDER BY time_bg DESC
LIMIT 1;
```

O status `Ready to Use` indica que o dosímetro foi apagado, medido como branco
e está pronto para ser utilizado novamente.

## 3. Como o Java calcula a dose líquida

Para cada canal, o programa aplica o fator de correção do dosímetro (`ECC`) e
o fator de correção da leitora (`RCF`). Depois, subtrai o background:

```text
dose líquida = (leitura OSL × ECC × RCF)
                - (background × ECC × RCF)
```

No código `TelaLeitura.java`, para Hp(10), a lógica é equivalente a:

```java
brancoHp10 = area_linhaBaseHp10 * ecc_Hp10AUX * rcf_ReaderAUX;
doseHp10 = (integralOSL_HP10 * ecc_Hp10AUX * rcf_ReaderAUX)
           - brancoHp10;
```

O mesmo cálculo é feito para Hp(0.07). Se o resultado for negativo, o sistema
define a dose como `0.000`, pois uma dose líquida negativa não é válida.

Se não houver background cadastrado, o código utiliza `2000` como branco
padrão para Hp(10) e Hp(0.07).

## 4. Diferença entre Hp(10) e Hp(0.07)

- **Hp(10)**: dose equivalente pessoal em uma profundidade de 10 mm; é usada
  principalmente como referência para exposição de corpo inteiro.
- **Hp(0.07)**: dose equivalente pessoal em uma profundidade de 0,07 mm; é
  mais relacionada à exposição superficial da pele.

Os dois canais podem possuir valores diferentes de personal dose e de
background, por isso o sistema mantém campos separados:

```text
Personal dose:   hp10_dos  e hp007_dos
Background:      hp10_bg   e hp007_bg
```

## 5. Interpretação da tela apresentada

Na tela do sistema:

- A tabela superior, com status **`Need to Erase`**, corresponde às leituras
  armazenadas em `historico_dose`. São dosímetros que precisam ser apagados.
- A tabela inferior, com status **`Ready to Use`**, corresponde às leituras
  armazenadas em `historico_branco`. São os valores de background obtidos após
  o apagamento.
- O mesmo `dosimeter_id` pode aparecer nas duas tabelas porque representa duas
  etapas do mesmo ciclo: leitura após o uso e releitura após o apagamento.

Os campos `hp10_dos`, `hp007_dos`, `hp10_bg` e `hp007_bg` são valores brutos de
leitura armazenados no banco. Os valores exibidos como `Hp(10) mSv` e
`Hp(0.07) mSv` são valores processados pela aplicação, após a aplicação dos
fatores ECC/RCF e da subtração do background.

## 6. Consulta para comparar os dois valores

Para consultar a última dose pessoal e o último background de um dosímetro:

```sql
SELECT
    d.dosimeter_id,
    d.time_dos,
    d.hp10_dos,
    d.hp007_dos,
    b.time_bg,
    b.hp10_bg,
    b.hp007_bg
FROM historico_dose d
LEFT JOIN historico_branco b
       ON b.dosimeter_id = d.dosimeter_id
WHERE d.dosimeter_id = ?
ORDER BY d.time_dos DESC, b.time_bg DESC;
```

Para uma avaliação correta, deve-se comparar registros do mesmo dosímetro e
considerar a data/hora de cada leitura. O background não deve ser somado à
dose pessoal; ele é usado como referência para remover o sinal de fundo.
