import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from threading import Thread

import serial
import serial.tools.list_ports
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.properties import BooleanProperty
from kivy.uix.button import Button
from kivy.uix.screenmanager import Screen
from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.uix.textinput import TextInput
from kivy.uix.treeview import TreeView, TreeViewLabel, TreeViewNode

from conversor import escrever_csv
from Plot_grafico import gerar_grafico
import os
import sys

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


NomeArquivoBL = BoxLayout(orientation="vertical")

lbl_erro = Label(text="Enter Valid File Name!")
NomeArquivoBL.add_widget(lbl_erro)

btn = Button(text="OK", size_hint_y=0.3)
NomeArquivoBL.add_widget(btn)

popupNomeArquivo = Popup(
    title="Warning",
    content=NomeArquivoBL,
    size_hint=(None, None),
    size=(400, 200)
)

btn.bind(on_release=popupNomeArquivo.dismiss)

BAUD_RATE = 115200
PORTAS_SERIAL = []

TESTES_DIR = Path(__file__).resolve().parent / "assets" / "testes"

COMANDOS_SUDO = {
    "leitura": "#S1%SC1001&",
    "stop": "#S1%SC1010&",
    "zerar": "#S1%SC1011&",
    "liga_led": "#S1%SC1100&",
}
COMANDO_PARAMETROS_PADRAO = "#S1%M1G4L03000P4Z05000Q4&"
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


class EntradaData(TextInput):
    """TextInput com máscara automática dd/mm/aaaa."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._formatacao_agendada = False
        self.bind(text=self._agendar_formatacao)

    def _agendar_formatacao(self, *args):
        if self._formatacao_agendada:
            return
        self._formatacao_agendada = True
        Clock.schedule_once(self._aplicar_mascara, 0)

    def _aplicar_mascara(self, dt):
        self._formatacao_agendada = False
        digitos = "".join(
            caractere for caractere in self.text if caractere.isdigit()
        )[:8]
        partes = [digitos[:2]]
        if len(digitos) > 2:
            partes.append(digitos[2:4])
        if len(digitos) > 4:
            partes.append(digitos[4:8])
        formatado = "/".join(partes)
        if len(digitos) in (2, 4):
            formatado += "/"

        if self.text != formatado:
            self.text = formatado
        self.cursor = (len(self.text), 0)


class NoArvoreArquivos(BoxLayout, TreeViewNode):
    """Item visual da árvore de pastas e arquivos."""

    def __init__(self, caminho=None, pasta=False, **kwargs):
        self.caminho = caminho
        self.pasta = pasta
        super().__init__(**kwargs)
        self.is_leaf = not pasta
        self.size_hint_y = None
        self.height = "30dp"
        self.orientation = "horizontal"
        self.spacing = 6
        self.padding = (4, 0)

        self.add_widget(Image(
            source=(
                "atlas://data/images/defaulttheme/filechooser_folder"
                if pasta else
                resource_path("assets/UI/arquivo_csv.png")
                if caminho and caminho.suffix.lower() == ".csv" else
                "atlas://data/images/defaulttheme/filechooser_file"
            ),
            size_hint=(None, None),
            size=(24, 24),
        ))
        nome = Label(
            text=caminho.name if caminho else "",
            size_hint_x=1,
            color=(1, 1, 1, 1),
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="right",
        )
        nome.bind(size=lambda widget, tamanho: setattr(widget, "text_size", tamanho))
        self.add_widget(nome)


class ArvoreArquivos(TreeView):
    """Árvore Ano/Mês/Dia dos arquivos de leitura."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.hide_root = True
        self.indent_level = 22
        self.caminho_base = None
        self.selecao_callback = None

    def recarregar(self, caminho_base, data_filtro=None):
        self.caminho_base = Path(caminho_base)
        for no in reversed(list(self.iterate_all_nodes())):
            if no is not self.root:
                self.remove_node(no)
        self.root.is_open = True

        arquivos = []
        if data_filtro:
            pasta_data = self.caminho_base / data_filtro.strftime("%Y/%m/%d")
            if pasta_data.is_dir():
                arquivos = sorted(
                    arquivo for arquivo in pasta_data.iterdir()
                    if arquivo.is_file()
                    and arquivo.suffix.lower() in (".txt", ".csv")
                )
        elif self.caminho_base.is_dir():
            arquivos = sorted(
                arquivo for arquivo in self.caminho_base.rglob("*")
                if arquivo.is_file() and arquivo.suffix.lower() in (".txt", ".csv")
            )

        if not arquivos:
            vazio = self.add_node(NoArvoreArquivos(self.caminho_base / "Nenhum arquivo encontrado"), self.root)
            vazio.is_leaf = True
            return 0

        nos_pasta = {}
        for arquivo in arquivos:
            relativo = arquivo.parent.relative_to(self.caminho_base)
            pai = self.root
            acumulado = self.caminho_base
            for parte in relativo.parts:
                acumulado = acumulado / parte
                if acumulado not in nos_pasta:
                    no_pasta = self.add_node(NoArvoreArquivos(acumulado, pasta=True), pai)
                    no_pasta.is_open = True
                    nos_pasta[acumulado] = no_pasta
                pai = nos_pasta[acumulado]
            no_arquivo = self.add_node(NoArvoreArquivos(arquivo), pai)
            no_arquivo.bind(is_selected=self._quando_selecionado)
        return len(arquivos)

    def _quando_selecionado(self, no, selecionado):
        if selecionado and self.selecao_callback:
            self.selecao_callback(self, no)


class TelaPrincipalLeitora(Screen):
    soma = 0
    contador = 0.1
    ecc = 1
    fcal = 0.0001
    fenerg = 1
    branco = 1
    f_fechar_log = False
    tempo_leitura = 3000
    string_log = ""
    soma_luz = 0
    f_luz_ref = False
    #caminho_arquivo = ""

    def bloquear_tela(self):
        self.disabled = True
        Clock.schedule_once(popupNomeArquivo.dismiss, 13)
        Clock.schedule_once(self.desbloquear_tela, 14)

    def desbloquear_tela(self, dt):
        self.disabled = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.caminho_arquivo = None
        self.serial_connection = None
        self.buffer_serial = ""
        self.log_arquivo = None
        self.leitura_evento = None
        self.nova_linha = True
        Clock.schedule_once(self.atualizar_portas_serial, 0)

    # Log
    def func_botao_log(self):
        if not self.log_arquivo:
            self.iniciar_log()

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
            self.caminho_arquivo = testes_dia_dir / nome_arquivo
            try:
                self.log_arquivo = open(self.caminho_arquivo, "x", encoding="utf-8")
            except FileExistsError:
                lbl_erro.text = "File Already Exists."
                popupNomeArquivo.open()
                print("Arquivo já existe")
                return

            self.log_arquivo.close()
            self.atualizar_status(f"Log iniciado em {self.caminho_arquivo}")

            self.nova_linha = True
            for linha in (
                data_atual.strftime("%d/%m/%Y %H:%M:%S"),
                nome_arquivo,
                "Integral:",
                "Dose mSv:",
                "Time;Count;Current;Light",
            ):
                self.salvar_log(f"{linha} \n")

            self.contador = 0.1
            self.soma = 0
            self.soma_luz = 0
            self.nova_linha = True
            self.enviar_comando_sudo("leitura")

        except OSError as erro:
            self.atualizar_status(f"Erro ao criar arquivo: {erro}")

    def fechar_log(self):
        self.ids.nome_arquivo_input.text = ""
        if not self.log_arquivo:
            return
        nome = self.log_arquivo.name
        self.atualizar_soma_no_log()
        self.log_arquivo = open(self.caminho_arquivo, "a", encoding="utf-8")
        self.log_arquivo.write(self.string_log)
        self.log_arquivo.close()
        self.log_arquivo = None
        self.atualizar_status(f"Log encerrado: {nome}")

    def salvar_log(self, mensagem):
        if self.log_arquivo:
            self.string_log += f"{mensagem}"
            #self.log_arquivo.write(f"{mensagem}")
            #self.log_arquivo.flush()

    def atualizar_soma_no_log(self):
        if not self.log_arquivo:

            return

        nome_arquivo = self.log_arquivo.name
        #self.log_arquivo.flush()

        with open(nome_arquivo, "r", encoding="utf-8") as arquivo:
            linhas = arquivo.readlines()

        linhas_string = self.string_log.splitlines()

        while len(linhas) < 4:
            linhas.append("\n")

        while len(linhas_string) < 4:
            linhas_string.append("\n")


        linhas[2] = f"Soma: {self.soma}\n"
        linhas[3] = f"Dose: {self.calcular_dose()}\n"

        linhas_string[2] = f"Soma: {self.soma}"
        linhas_string[3] = f"Dose: {self.calcular_dose()}"

        self.ids.label_dose.text = f"{self.calcular_dose():.2f}"

        self.string_log = "\n".join(linhas_string)

        #with open(nome_arquivo, "w", encoding="utf-8") as arquivo:
        #    arquivo.writelines(linhas)

    def calcular_dose(self):
        return (
            (self.soma - float(self.ids.branco_textInput.text.replace(',', '.')))
            * float(self.ids.rcf_textInput.text.replace(',', '.'))
            * float(self.ids.ecc_textInput.text.replace(',', '.'))
            * float(self.ids.fcal_textInput.text.replace(',', '.'))
            * float(self.ids.fenerg_textInput.text.replace(',', '.'))
        )

    # Serial
    def atualizar_portas_serial(self, *args):
        portas_detectadas = [
            porta.device for porta in serial.tools.list_ports.comports()
        ]
        portas = list(dict.fromkeys(portas_detectadas + PORTAS_SERIAL))

        self.ids.porta_spinner.values = portas
        self.ids.porta_spinner.text = portas[0] if portas else "COM Port"
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
        lbl_erro.text = "Wait a Moment."
        popupNomeArquivo.open()
        self.bloquear_tela()
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

            self.ids.botao_conexao_serial.text = "Disconnect"
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
            self.ids.botao_conexao_serial.text = "Connect"
            self.atualizar_status("Serial desconectada.")

    def serial_aberta(self):
        return self.serial_connection and self.serial_connection.is_open

    def enviar_serial(self, comando):
        if not self.serial_aberta():
            self.atualizar_status("Serial desconectada. Verifique a porta.")
            lbl_erro.text = "Connect to OSL System!"
            popupNomeArquivo.open()
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
        print(f"f_luz_ref: {self.f_luz_ref}")
        # O frame D fecha a amostra (ultima coluna); os demais sao colunas
        # intermediarias. Cada linha comeca pelo Tempo (ver registrar_valor).
        if frame.startswith("#L1%D"):
            self.registrar_valor(frame, fim_linha=True)
            valor = int(frame[5:])
            self.ids.label_light.text = f"{valor}"
            self.soma_luz += valor
            if self.f_luz_ref:
                print("luz_ref")
                self.ids.label_dose.text = f"{self.soma_luz}"

        elif frame[:5] in ("#L1%A", "#L1%B", "#L1%E", "#L1%T"):
            if frame[:5] == "#L1%A":
                valor = int(frame[5:])
                self.ids.label_count.text = f"{valor}"
                self.soma += valor

            if frame[:5] == "#L1%E":
                valor = int(frame[5:])
                self.ids.label_current.text = f"{valor}"

            self.registrar_valor(frame, fim_linha=False)
        elif frame == "#L1%I0000000":
            self.enviar_serial(COMANDO_PARAMETROS_PADRAO)

    def registrar_valor(self, frame, fim_linha):
        valor = int(frame[5:])

        # Primeira coluna de cada linha: o Tempo (contador da amostra).
        if self.nova_linha:
            self.salvar_log(f"{self.contador:.1f};")

            if self.contador > int(self.tempo_leitura)/1000:
                self.f_fechar_log = True

            self.contador += 0.1

            self.nova_linha = False

        if fim_linha:
            self.salvar_log(f"{valor} \n")
            self.nova_linha = True
            if self.f_fechar_log:
                if self.f_luz_ref:
                    self.ids.label_dose.text = f"{self.soma_luz}"
                else:
                    self.ids.label_dose.text = f"{self.soma}"


                self.f_luz_ref = False

                self.f_fechar_log = False
                self.fechar_log()

        else:
            self.salvar_log(f"{valor};")

    # Comandos
    def botao_leitura(self):
        self.string_log = ""
        self.ids.label_dose.text = "0"
        self.ids.label_current.text = "0"
        self.ids.label_light.text = "0"
        self.ids.label_count.text = "0"
        self.f_luz_ref = False
        if not self.serial_aberta():
            self.atualizar_status("Serial desconectada. Verifique a porta.")
            lbl_erro.text = "Connect to OSL System!"
            popupNomeArquivo.open()
        else:
            if not self.ids.nome_arquivo_input.text == "":
                self.ids.LabelDose.text = "Dose (mSv)"
                self.func_botao_log()
            else:
                lbl_erro.text = "Empty File Name!"
                popupNomeArquivo.open()

    def botao_ref_light(self):
        self.ids.label_dose.text = "0"
        self.ids.label_current.text = "0"
        self.ids.label_light.text = "0"
        self.ids.label_count.text = "0"
        self.ids.LabelDose.text = "Integral Light"
        self.soma = 0
        self.soma_luz = 0
        self.f_luz_ref = True
        self.contador = 0
        self.enviar_comando_sudo("leitura")

    def enviar_comando_sudo(self, nome_comando):
        self.enviar_serial(COMANDOS_SUDO[nome_comando])

    def enviar_parametros(self):
        if self.serial_connection:
            tela = self.manager.get_screen("parametros")
            modo = tela.ids.modo_input.text.strip()
            ganho = tela.ids.ganho_input.text.strip()
            tempo_leitura = tela.ids.tempo_leitura_input.text.strip()
            self.tempo_leitura = tempo_leitura
            print(self.tempo_leitura)
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
            lbl_erro.text = "Parameters Updated!"
            popupNomeArquivo.open()
        else:
            lbl_erro.text = "Connect to OSL System!"
            popupNomeArquivo.open()

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


class TelaGraficos(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.arquivo_selecionado = None
        self.png_grafico = Path(tempfile.gettempdir()) / "grafico_osl.png"
        self.operacao_em_andamento = False

    def on_pre_enter(self, *args):
        self.ids.arvore_arquivos.selecao_callback = self.selecionar_no
        self.ids.arvore_arquivos.recarregar(TESTES_DIR)

    def selecionar_no(self, arvore, no):
        caminho = getattr(no, "caminho", None)
        if not caminho or not caminho.is_file():
            return
        self.arquivo_selecionado = caminho
        self.atualizar_status_grafico(
            f"Selecionado: {self.arquivo_selecionado.name}"
        )

    def filtrar_por_data(self):
        texto = self.ids.data_filtro.text.strip()
        try:
            data = datetime.strptime(texto, "%d/%m/%Y").date()
        except ValueError:
            self.atualizar_status_grafico(
                "Informe uma data válida no formato dd/mm/aaaa."
            )
            return

        self.arquivo_selecionado = None
        quantidade = self.ids.arvore_arquivos.recarregar(TESTES_DIR, data)
        if quantidade:
            self.atualizar_status_grafico(
                f"{quantidade} arquivo(s) encontrado(s) em {texto}."
            )
        else:
            self.atualizar_status_grafico(
                f"Nenhum arquivo encontrado em {texto}."
            )

    def limpar_filtro_data(self):
        self.ids.data_filtro.text = ""
        self.arquivo_selecionado = None
        self.ids.arvore_arquivos.recarregar(TESTES_DIR)
        self.atualizar_status_grafico("Mostrando todos os arquivos.")

    def gerar_grafico(self):
        if self.operacao_em_andamento or not self._tem_arquivo():
            return
        opcoes = (
            self.ids.cb_leitura.active,
            self.ids.cb_corrente.active,
            self.ids.cb_luz.active,
        )
        arquivo = self.arquivo_selecionado
        self._definir_operacao(True, "Gerando gráfico...")
        Thread(
            target=self._gerar_grafico_worker,
            args=(arquivo, opcoes),
            daemon=True,
        ).start()

    def _gerar_grafico_worker(self, arquivo, opcoes):
        try:
            caminho_csv, _ = gerar_grafico(
                arquivo,
                self.png_grafico,
                None,
                *opcoes,
            )
        except Exception as erro:
            traceback.print_exc()
            mensagem = f"Erro ao gerar gráfico: {erro}"
            Clock.schedule_once(
                lambda dt, texto=mensagem: self._finalizar_operacao(texto),
                0,
            )
            return
        Clock.schedule_once(
            lambda dt, caminho=caminho_csv: self._mostrar_grafico(caminho),
            0,
        )

    def _mostrar_grafico(self, caminho_csv):
        try:
            self.ids.imagem_grafico.source = str(self.png_grafico)
            self.ids.imagem_grafico.reload()
            self._finalizar_operacao(
                f"Gráfico gerado (CSV: {Path(caminho_csv).name})."
            )
        except Exception as erro:
            traceback.print_exc()
            self._finalizar_operacao(f"Erro ao exibir gráfico: {erro}")

    def exportar_csv(self):
        if self.operacao_em_andamento or not self._tem_arquivo():
            return
        arquivo = self.arquivo_selecionado
        if arquivo.suffix.lower() == ".csv":
            self.atualizar_status_grafico(f"O arquivo já é CSV: {arquivo}")
            return
        self._definir_operacao(True, "Exportando CSV...")
        Thread(
            target=self._exportar_csv_worker,
            args=(arquivo,),
            daemon=True,
        ).start()

    def _exportar_csv_worker(self, arquivo):
        try:
            caminho_csv = escrever_csv(arquivo)
        except Exception as erro:
            traceback.print_exc()
            mensagem = f"Erro ao exportar CSV: {erro}"
            Clock.schedule_once(
                lambda dt, texto=mensagem: self._finalizar_operacao(texto),
                0,
            )
            return

        Clock.schedule_once(
            lambda dt, caminho=caminho_csv: self._finalizar_exportacao(caminho),
            0,
        )

    def _finalizar_exportacao(self, caminho_csv):
        texto_data = self.ids.data_filtro.text.strip()
        data_filtro = None
        if texto_data:
            try:
                data_filtro = datetime.strptime(texto_data, "%d/%m/%Y").date()
            except ValueError:
                data_filtro = None

        self.ids.arvore_arquivos.recarregar(TESTES_DIR, data_filtro)
        self._finalizar_operacao(f"CSV salvo em {caminho_csv}")

    def _tem_arquivo(self):
        if (
            self.arquivo_selecionado
            and self.arquivo_selecionado.is_file()
            and self.arquivo_selecionado.suffix.lower() in (".txt", ".csv")
        ):
            return True
        self.atualizar_status_grafico("Selecione um arquivo de log.")
        return False

    def _definir_operacao(self, ativa, mensagem):
        self.operacao_em_andamento = ativa
        self.ids.botao_plot.disabled = ativa
        self.ids.botao_exportar_csv.disabled = ativa
        self.atualizar_status_grafico(mensagem)

    def _finalizar_operacao(self, mensagem):
        self._definir_operacao(False, mensagem)

    def atualizar_status_grafico(self, mensagem):
        print(mensagem)
        self.ids.status_grafico_label.text = mensagem


class AplicativoInterfaceOSL(App):
    title = "OSLMeter V4.0"

    def build(self):
        return Builder.load_file(resource_path("interface_OSL.kv"))

    def trocar_para_graficos(self):
        self.root.transition.direction = "up"
        self.root.current = "graficos"

    def on_stop(self):
        main = self.root.get_screen("main")
        if main.log_arquivo:
            main.log_arquivo.close()

        main.desconectar_serial(atualizar_botao=False)


def main():
    Window.maximize()
    AplicativoInterfaceOSL().run()


if __name__ == "__main__":
    main()
