# Simulador OSL

O simulador usa exclusivamente a porta serial virtual `COM6` e fala o mesmo
protocolo usado pela leitora. Com o par `COM5 <-> COM6`, a interface principal
deve abrir a `COM5`.

## Uso

1. Execute `simulador_osl.py` com a venv do projeto.
2. Abra a interface principal.
3. Selecione `COM5`.
4. Clique em `Connect` e depois em `Start`.

O simulador envia leitura, corrente, tempo e luz a cada 100 ms. O LED do
Canvas acende durante a leitura.

Se as portas tiverem outros números, altere `PORTA_SERIAL` no início do
`simulador_osl.py` para a segunda porta do par.
