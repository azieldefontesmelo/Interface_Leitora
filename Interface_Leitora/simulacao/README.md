# Simulador OSL

O simulador fala o mesmo protocolo usado pela leitora. Selecione a porta serial
na lista da janela e clique em **Conectar**. Use na interface principal a outra
ponta do par virtual; por exemplo, se o simulador estiver na `COM6`, a interface
deve abrir a `COM5`.

## Uso

1. Execute `simulador_osl.py` com a venv do projeto.
2. Abra a interface principal.
3. Selecione `COM5`.
4. Clique em `Connect` e depois em `Start`.

O simulador envia leitura, corrente, tempo e luz a cada 100 ms. O tempo da
leitura é obtido do parâmetro `L` recebido na string de configuração, como
`L03000` (3 segundos). Ao terminar, o simulador apaga o LED, para a geração
de amostras e envia `#L1%I0000101&` (fim da leitura).

Use **Atualizar** para reler as portas disponíveis depois de criar ou conectar
um par virtual.
