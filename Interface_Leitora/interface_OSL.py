from datetime import datetime
from pathlib import Path

import serial
import serial.tools.list_ports
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.properties import BooleanProperty
from kivy.uix.button import Button
from kivy.uix.screenmanager import Screen


BAUD_RATE = 115200
PORTAS_SERIAL = []

TESTES_DIR = Path(__file__).resolve().parent / "assets" / "testes"

COMANDOS_SUDO = {
    "leitura": "#S1%SC1001&",
    "stop": "#S1%SC1010&",
    "zerar": "#S1%SC1011&",
    "liga_led": "#S1%SC1100&",
}
COMANDO_PARAMETROS_PADRAO = "#S1%M1G3L03000P4Z05000Q4&"
COMANDO_INICIAL = COMANDO_PARAMETROS_PADRAO


class BotaoNavegacaoParametros(Button):
    hovered = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        Window.bind(mouse_pos=self.on_mouse_pos)

    def on_mouse_pos(self, window, pos):
        if not self.get_root_window():
            return

        dentro = self.collide_point(*self.to_widget(*pos))
        if self.hovered == dentro:
            return

        self.hovered = dentro
        self.background_color = (
            (0.25, 0.25, 0.25, 1)
            if dentro else (0.18, 0.18, 0.18, 1)
        )


class TelaPrincipalLeitora(Screen):
    soma = 0
    contador = 0
    ecc = 1
    fcal = 0.0001
    fenerg = 1
    branco = 1

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.serial_connection = None
        self.buffer_serial = ""
        self.log_arquivo = None
        self.leitura_evento = None
        Clock.schedule_once(self.atualizar_portas_serial, 0)

    # Log
    def func_botao_log(self):
        self.fechar_log() if self.log_arquivo else self.iniciar_log()

    def iniciar_log(self):
        nome_arquivo = self.ids.nome_arquivo_input.text.strip()
        if not nome_arquivo:
            self.atualizar_status("Digite um nome para o arquivo.")
            return

        if not nome_arquivo.endswith(".txt"):
            nome_arquivo += ".txt"

        data_atual = datetime.now()
        testes_dia_dir = TESTES_DIR / data_atual.strftime("%Y/%m/%d")
        testes_dia_dir.mkdir(parents=True, exist_ok=True)

        try:
            caminho_arquivo = testes_dia_dir / nome_arquivo
            self.log_arquivo = open(caminho_arquivo, "a", encoding="utf-8")
            self.atualizar_status(f"Log iniciado em {caminho_arquivo}")
            self.ids.botao_log.text = "Fechar Log"

            for linha in (
                data_atual.strftime("%d/%m/%Y %H:%M:%S"),
                nome_arquivo,
                "Soma:",
                "Dose:",
            ):
                self.salvar_log(f"{linha} \n")

        except OSError as erro:
            self.atualizar_status(f"Erro ao criar arquivo: {erro}")

    def fechar_log(self):
        if not self.log_arquivo:
            return

        nome = self.log_arquivo.name
        self.atualizar_soma_no_log()
        self.log_arquivo.close()
        self.log_arquivo = None
        self.ids.botao_log.text = "Iniciar Log"
        self.atualizar_status(f"Log encerrado: {nome}")

    def salvar_log(self, mensagem):
        if self.log_arquivo:
            self.log_arquivo.write(f"{mensagem}")
            self.log_arquivo.flush()

    def atualizar_soma_no_log(self):
        if not self.log_arquivo:
            return

        nome_arquivo = self.log_arquivo.name
        self.log_arquivo.flush()

        with open(nome_arquivo, "r", encoding="utf-8") as arquivo:
            linhas = arquivo.readlines()

        while len(linhas) < 4:
            linhas.append("\n")

        linhas[2] = f"Soma: {self.soma}\n"
        linhas[3] = f"Dose: {self.calcular_dose()}\n"

        with open(nome_arquivo, "w", encoding="utf-8") as arquivo:
            arquivo.writelines(linhas)

    def calcular_dose(self):
        return (
            (self.soma - float(self.ids.branco_textInput.text))
            * float(self.ids.ecc_textInput.text)
            * float(self.ids.fcal_textInput.text)
            * float(self.ids.fenerg_textInput.text)
        )

    # Serial
    def atualizar_portas_serial(self, *args):
        portas_detectadas = [
            porta.device for porta in serial.tools.list_ports.comports()
        ]
        portas = list(dict.fromkeys(PORTAS_SERIAL + portas_detectadas))

        self.ids.porta_spinner.values = portas
        self.ids.porta_spinner.text = portas[0] if portas else "Porta"
        self.atualizar_status(
            "Escolha a porta e clique em Conectar."
            if portas else "Nenhuma porta serial encontrada."
        )

    def func_botao_conexao_serial(self):
        if self.serial_aberta():
            self.desconectar_serial()
            return

        self.conectar_serial()

    def conectar_serial(self, *args):
        porta = self.ids.porta_spinner.text
        if porta == "Porta":
            self.atualizar_status("Selecione uma porta serial.")
            return

        try:
            self.desconectar_serial(atualizar_botao=False)
            self.serial_connection = serial.Serial(
                porta, BAUD_RATE, timeout=0.05
            )
            self.leitura_evento = Clock.schedule_interval(self.ler_serial, 0.1)
            Clock.schedule_once(
                lambda dt: self.enviar_serial(COMANDO_INICIAL), 0.2
            )

            self.ids.botao_conexao_serial.text = "Desconectar"
            self.atualizar_status(f"Conectado em {porta} @ {BAUD_RATE}")

        except (OSError, serial.SerialException) as erro:
            self.atualizar_status(f"Erro ao conectar: {erro}")

    def desconectar_serial(self, atualizar_botao=True):
        if self.leitura_evento:
            self.leitura_evento.cancel()
            self.leitura_evento = None

        if self.serial_aberta():
            self.serial_connection.close()

        self.serial_connection = None

        if atualizar_botao:
            self.ids.botao_conexao_serial.text = "Conectar"
            self.atualizar_status("Serial desconectada.")

    def serial_aberta(self):
        return self.serial_connection and self.serial_connection.is_open

    def enviar_serial(self, comando):
        if not self.serial_aberta():
            self.atualizar_status("Serial desconectada. Verifique a porta.")
            return

        try:
            self.serial_connection.write(comando.encode("ascii"))
            self.atualizar_status(f"Enviado: {comando}")
        except serial.SerialException as erro:
            self.atualizar_status(f"Erro ao enviar: {erro}")

    def ler_serial(self, dt):
        if not self.serial_aberta():
            return

        try:
            if self.serial_connection.in_waiting <= 0:
                return

            texto = self.serial_connection.read(
                self.serial_connection.in_waiting
            ).decode("ascii", errors="ignore")
            self.buffer_serial += texto

            while "&" in self.buffer_serial:
                frame, self.buffer_serial = self.buffer_serial.split("&", 1)
                if frame:
                    self.processar_frame(frame)

        except serial.SerialException as erro:
            self.atualizar_status(f"Erro na leitura serial: {erro}")

    def processar_frame(self, frame):
        self.ids.recebido_label.text = f"Recebido: {frame}&"
        print(f"RECEBIDO: {frame}&")

        if frame.startswith("#L1%A"):
            self.registrar_valor(frame, 0.1)
        elif frame.startswith("#L1%B"):
            self.registrar_valor(frame, 0.1)
        elif frame.startswith("#L1%D"):
            self.registrar_valor(frame, -1)
        elif frame.startswith("#L1%E"):
            self.registrar_valor(frame, 0)
        elif frame.startswith("#L1%T"):
            self.registrar_valor(frame, -2)
        elif frame == "#L1%I0000000":
            self.enviar_serial(COMANDO_PARAMETROS_PADRAO)

    def registrar_valor(self, frame, incremento):
        valor = int(frame[5:])
        self.soma += valor
        if incremento > 0:
            self.salvar_log(f"{self.contador:.1f};{valor};")
            self.contador += incremento
        if incremento == 0:
            self.salvar_log(f"{valor};")
        if incremento == -1:
            self.salvar_log(f"{valor} \n")
        if incremento == -2:
            self.salvar_log(f"{valor};")

    # Comandos
    def botao_leitura(self):
        self.contador = 0
        self.soma = 0
        self.enviar_comando_sudo("leitura")

    def enviar_comando_sudo(self, nome_comando):
        self.enviar_serial(COMANDOS_SUDO[nome_comando])

    def enviar_parametros(self):
        tela = self.manager.get_screen("parametros")
        modo = tela.ids.modo_input.text.strip()
        ganho = tela.ids.ganho_input.text.strip()
        tempo_leitura = tela.ids.tempo_leitura_input.text.strip()
        potencia = tela.ids.potencia_input.text.strip()
        tempo_zeramento = tela.ids.tempo_zeramento_input.text.strip()
        potencia_zeramento = tela.ids.potencia_zeramento_input.text.strip()

        campos_validos = (
            self._validar_campo_1_digito(modo, "M")
            and self._validar_campo_1_digito(ganho, "G")
            and self._validar_tempo(tempo_leitura, "L")
            and self._validar_campo_1_digito(potencia, "P")
            and self._validar_tempo(tempo_zeramento, "Z")
            and self._validar_campo_1_digito(potencia_zeramento, "Q")
        )
        if not campos_validos:
            return

        comando = (
            f"#S1%M{modo}G{ganho}"
            f"L{tempo_leitura.zfill(5)}"
            f"P{potencia}"
            f"Z{tempo_zeramento.zfill(5)}"
            f"Q{potencia_zeramento}&"
        )
        self.enviar_serial(comando)

    # Utilitarios
    def atualizar_status(self, mensagem):
        print(mensagem)
        self.ids.status_label.text = mensagem

    def _validar_campo_1_digito(self, valor, nome):
        if len(valor) == 1 and valor.isdigit():
            return True

        self.atualizar_status(f"Campo {nome} deve ter 1 digito.")
        return False

    def _validar_tempo(self, valor, nome):
        if valor.isdigit() and 1 <= len(valor) <= 5:
            return True

        self.atualizar_status(
            f"Campo {nome} deve ser numerico com ate 5 digitos."
        )
        return False


class TelaParametrosLeitura(Screen):
    pass


class AplicativoInterfaceOSL(App):
    def build(self):
        return Builder.load_file("interface_OSL.kv")

    def on_stop(self):
        main = self.root.get_screen("main")
        if main.log_arquivo:
            main.log_arquivo.close()

        main.desconectar_serial(atualizar_botao=False)


AplicativoInterfaceOSL().run()
