import serial
from pathlib import Path
from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.uix.screenmanager import ScreenManager, Screen
from datetime import datetime
import serial.tools.list_ports
from kivy.properties import BooleanProperty
from kivy.core.window import Window
from kivy.uix.button import Button
import time

agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

BAUD_RATE = 115200
BASE_DIR = Path(__file__).resolve().parent
TESTES_DIR = BASE_DIR / "assets" / "testes"

COMANDOS_SUDO = {
    "leitura": "#S1%SC1001&",
    "stop": "#S1%SC1010&",
    "zerar": "#S1%SC1011&",
    "liga_led": "#S1%SC1100&",
}

class HoverButton(Button):

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

        if dentro:
            self.background_color = (0.25, 0.25, 0.25, 1)
        else:
            self.background_color = (0.18, 0.18, 0.18, 1)

class MainScreen(Screen):

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

        Clock.schedule_once(self.conectar_serial, 0)

    def func_botao_log(self):
        if self.log_arquivo:
            self.fechar_log()
        else:
            self.iniciar_log()

    def iniciar_log(self):

        data_atual = datetime.now()
        testes_dia_dir = (
            TESTES_DIR
            / data_atual.strftime("%Y")
            / data_atual.strftime("%m")
            / data_atual.strftime("%d")
        )

        testes_dia_dir.mkdir(parents=True, exist_ok=True)

        nome_arquivo = self.ids.nome_arquivo_input.text.strip()

        if not nome_arquivo:
            self.atualizar_status("Digite um nome para o arquivo.")
            return

        if not nome_arquivo.endswith(".txt"):
            nome_arquivo += ".txt"

        caminho_arquivo = testes_dia_dir / nome_arquivo

        try:
            self.log_arquivo = open(caminho_arquivo, "a", encoding="utf-8")

            self.atualizar_status(f"Log iniciado em {caminho_arquivo}")

            self.salvar_log(agora)
            self.salvar_log(nome_arquivo)
            self.salvar_log("Soma:")
            self.salvar_log("Dose:")

            self.ids.botao_log.text = "Fechar Log"

        except OSError as erro:
            self.atualizar_status(f"Erro ao criar arquivo: {erro}")

    def atualizar_soma_no_log(self):

        if not self.log_arquivo:
            return

        nome_arquivo = self.log_arquivo.name

        self.log_arquivo.flush()

        with open(nome_arquivo, "r", encoding="utf-8") as arquivo:
            linhas = arquivo.readlines()

        while len(linhas) < 4:
            linhas.append("\n")

        dose = (
            (self.soma - float(self.ids.branco_textInput.text)) # self branco de 0 a 1000000
            * float(self.ids.ecc_textInput.text)  # 0 a 10
            * float(self.ids.fcal_textInput.text) # 0 a 10
            * float(self.ids.fenerg_textInput.text) # 0 a 10
        )

        linhas[2] = f"Soma: {self.soma}\n"
        linhas[3] = f"Dose: {dose}\n"

        with open(nome_arquivo, "w", encoding="utf-8") as arquivo:
            arquivo.writelines(linhas)

    def fechar_log(self):

        if not self.log_arquivo:
            return

        nome = self.log_arquivo.name

        self.atualizar_soma_no_log()

        self.log_arquivo.close()

        self.log_arquivo = None

        self.atualizar_status(f"Log encerrado: {nome}")

        self.ids.botao_log.text = "Iniciar Log"

    def salvar_log(self, mensagem):

        if not self.log_arquivo:
            return

        self.log_arquivo.write(str(mensagem) + "\n")
        self.log_arquivo.flush()

    def conectar_serial(self, *args):

        try:
            portas = serial.tools.list_ports.comports()

            self.serial_connection = serial.Serial(
                portas[0].name,
                BAUD_RATE,
                timeout=0.05
            )

            self.atualizar_status(
                f"Conectado em {portas[0].name} @ {BAUD_RATE}"
            )

            Clock.schedule_interval(self.ler_serial, 0.1)

        except serial.SerialException as erro:

            self.atualizar_status(f"Erro ao conectar: {erro}")

    def botao_leitura(self):

        self.contador = 0
        self.soma = 0

        self.enviar_comando_sudo("leitura")

    def enviar_comando_sudo(self, nome_comando):

        comando = COMANDOS_SUDO[nome_comando]

        self.enviar_serial(comando)

    def enviar_parametros(self):

        tela_parametros = self.manager.get_screen("parametros")

        modo = tela_parametros.ids.modo_input.text.strip()
        ganho = tela_parametros.ids.ganho_input.text.strip()
        tempo_leitura = tela_parametros.ids.tempo_leitura_input.text.strip()
        potencia = tela_parametros.ids.potencia_input.text.strip()
        tempo_zeramento = tela_parametros.ids.tempo_zeramento_input.text.strip()
        potencia_zeramento = tela_parametros.ids.potencia_zeramento_input.text.strip()

        if not self._validar_campo_1_digito(modo, "M"):
            return

        if not self._validar_campo_1_digito(ganho, "G"):
            return

        if not self._validar_tempo(tempo_leitura, "L"):
            return

        if not self._validar_campo_1_digito(potencia, "P"):
            return

        if not self._validar_tempo(tempo_zeramento, "Z"):
            return

        if not self._validar_campo_1_digito(potencia_zeramento, "Q"):
            return

        comando = (
            f"#S1%M{modo}G{ganho}"
            f"L{tempo_leitura.zfill(5)}"
            f"P{potencia}"
            f"Z{tempo_zeramento.zfill(5)}"
            f"Q{potencia_zeramento}&"
        )

        self.enviar_serial(comando)

    def enviar_serial(self, comando):

        if not self.serial_connection or not self.serial_connection.is_open:

            self.atualizar_status(
                "Serial desconectada. Verifique a porta."
            )

            return

        try:

            self.serial_connection.write(comando.encode("ascii"))

            self.atualizar_status(f"Enviado: {comando}")

        except serial.SerialException as erro:

            self.atualizar_status(f"Erro ao enviar: {erro}")

    def ler_serial(self, dt):

        if not self.serial_connection:
            return

        if not self.serial_connection.is_open:
            return

        try:

            if self.serial_connection.in_waiting <= 0:
                return

            texto = self.serial_connection.read(
                self.serial_connection.in_waiting
            ).decode("ascii", errors="ignore")

            self.buffer_serial += texto

            while "&" in self.buffer_serial:

                frame, self.buffer_serial = (
                    self.buffer_serial.split("&", 1)
                )

                if frame:

                    self.ids.recebido_label.text = (
                        f"Recebido: {frame}&"
                    )

                    print(f"RECEBIDO: {frame}&")

                    if frame.startswith("#L1%A"):

                        valor = int(frame[5:])

                        self.soma += valor
                        self.contador += 0.1

                        self.salvar_log(
                            f"{self.contador:.1f} {valor}"
                        )

                    elif frame.startswith("#L1%B"):

                        valor = int(frame[5:])

                        self.soma += valor
                        self.contador += 0.001

                        self.salvar_log(
                            f"{self.contador:.1f} {valor}"
                        )

                    if frame == "#L1%I0000000":
                        comando = (
                            f"#S1%M1G3"
                            f"L03000"
                            f"P4"
                            f"Z05000"
                            f"Q4&"
                        )

                        self.enviar_serial(comando)

        except serial.SerialException as erro:

            self.atualizar_status(
                f"Erro na leitura serial: {erro}"
            )

    def atualizar_status(self, mensagem):

        print(mensagem)

        self.ids.status_label.text = mensagem

    def _validar_campo_1_digito(self, valor, nome):

        if len(valor) == 1 and valor.isdigit():
            return True

        self.atualizar_status(
            f"Campo {nome} deve ter 1 digito."
        )

        return False

    def _validar_tempo(self, valor, nome):

        if valor.isdigit() and 1 <= len(valor) <= 5:
            return True

        self.atualizar_status(
            f"Campo {nome} deve ser numerico com ate 5 digitos."
        )

        return False


class InterfaceOSLApp(App):

    def build(self):

        return Builder.load_file("interface_OSL.kv")

    def on_stop(self):

        main = self.root.get_screen("main")

        if main.log_arquivo:
            main.log_arquivo.close()

        if main.serial_connection:

            if main.serial_connection.is_open:
                main.serial_connection.close()


InterfaceOSLApp().run()