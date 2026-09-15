import json
import sqlite3
import tempfile
import traceback
import webbrowser
from collections import deque
from datetime import datetime
from math import hypot
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock, Thread, current_thread
from uuid import uuid4

import serial
import serial.tools.list_ports
import pandas as pd
from kivy.config import Config

# O estado precisa ser definido antes de o provedor SDL2 criar a janela.
# Chamar Window.maximize() apenas antes de App.run() pode ser ignorado no
# Windows, porque nesse momento ainda não existe uma janela nativa.
Config.set("graphics", "window_state", "maximized")

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.screenmanager import ScreenManager
from kivy.uix.screenmanager import Screen
from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.image import Image
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.graphics import Color, Line, Rectangle
from kivy.uix.treeview import TreeView, TreeViewLabel, TreeViewNode

from app_paths import (
    USER_ASSETS_DIR,
    USER_DATA_DIR,
    bundle_dir,
    ensure_user_data,
    resource_path,
)

# O ícone da janela deve vir do pacote, nunca de um arquivo antigo em
# Documentos que possa ter sido copiado com outro conteúdo.
APP_ICON_PATH = str(Path(bundle_dir()) / "assets" / "UI" / "iconeOSL.ico")
Window.icon = APP_ICON_PATH
if Window.initialized:
    Window.set_icon(APP_ICON_PATH)

from conversor import escrever_csv
from database import Database, NEED_RE_READ_STATUS, PERSONAL_DOSE_STATUS
from measurement_workflow import (
    append_filename_observation,
    calculate_dose,
    calculate_high_dose,
    dosimeter_filename,
    parse_number,
    safe_test_filename,
    scanner_text,
)
from Plot_grafico import gerar_grafico
from ref_light_export import REF_LIGHT_XLSX_PATH, append_ref_light_session
from serial_protocol import SerialFrameDecoder, is_exact_complete_frame


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
DATABASE_PAGE_SIZE = 100
PORTA_SERIAL_PREFERIDA = "COM9"
SERIAL_READ_TIMEOUT = 0.05
SERIAL_READ_CHUNK_SIZE = 4096
SERIAL_UI_POLL_SECONDS = 0.01
SERIAL_MAX_FRAMES_PER_UI_TICK = 500
SERIAL_FIRST_FRAME_TIMEOUT = 5.0
SERIAL_SILENCE_TIMEOUT = 2.0

ASSETS_DIR = USER_ASSETS_DIR
TESTES_DIR = ASSETS_DIR / "testes"
LOG_SERIAL_DIR = ASSETS_DIR / "log"
SETTINGS_PATH = USER_DATA_DIR / "configuracoes.json"

COMANDOS_SUDO = {
    "leitura": "#S1%SC1001&",
    "stop": "#S1%SC1010&",
    "zerar": "#S1%SC1011&",
    "liga_led": "#S1%SC1100&",
}
COMANDO_PARAMETROS_PADRAO = "#S1%M1G4L03000P4Z05000Q4&"
COMANDO_INICIAL = COMANDO_PARAMETROS_PADRAO
FRAME_ALTA_DOSE = "#L1%AsatLeit&"
COMANDO_CONFIG_ALTA_DOSE = "#S1%M1G3L03000P1Z01000Q4&"
ESTADO_LEITURA_NORMAL = "LEITURA_NORMAL"
ESTADO_ALTA_DOSE_ENVIANDO_CONFIG = "ALTA_DOSE_ENVIANDO_CONFIG"
ESTADO_ALTA_DOSE_AGUARDANDO_FILTRO = "ALTA_DOSE_AGUARDANDO_FILTRO"
ESTADO_ALTA_DOSE_REINICIANDO = "ALTA_DOSE_REINICIANDO"
ESTADO_LEITURA_ALTA_DOSE = "LEITURA_ALTA_DOSE"
ESTADO_LEITURA_FINALIZADA = "LEITURA_FINALIZADA"
ESTADOS_ALTA_DOSE_PENDENTE = frozenset(
    {
        ESTADO_ALTA_DOSE_ENVIANDO_CONFIG,
        ESTADO_ALTA_DOSE_AGUARDANDO_FILTRO,
        ESTADO_ALTA_DOSE_REINICIANDO,
    }
)
FLED_PADRAO_POR_PLED = {"1": 100.0, "2": None, "3": None, "4": 1.0}

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
    """Campo de data com digitação livre, sem inserir barras automaticamente."""

    pass


class RotuloDose(Label):
    """Valor de dose que abre o snapshot do cálculo em duplo clique."""

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and getattr(touch, "is_double_tap", False):
            aplicativo = App.get_running_app()
            if aplicativo and aplicativo.root:
                aplicativo.root.get_screen("main").mostrar_detalhes_dose()
            return True
        return super().on_touch_down(touch)


class PopupAltaDose(Popup):
    """Modal that cannot be dismissed with Escape while confirmation is pending."""

    def _handle_keyboard(self, _window, key, *args):
        if key == 27:
            return True
        return super()._handle_keyboard(_window, key, *args)


class _PainelModoTouch:
    """Impede que controles de um painel recolhido capturem o mouse."""

    def on_touch_down(self, touch):
        if self.disabled:
            return False
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self.disabled:
            return False
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if self.disabled:
            return False
        return super().on_touch_up(touch)


class PainelModoManual(_PainelModoTouch, GridLayout):
    pass


class PainelModoDosimetro(_PainelModoTouch, BoxLayout):
    pass


class GraficoTempoReal(Widget):
    """Gráfico leve, desenhado pelo Kivy, para acompanhar a serial ao vivo."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.amostras = deque(maxlen=240)
        self.intervalo_amostra = 0.1
        self.tempo_grafico = 0.0
        self.series_ativas = {
            "count": True,
            "current": True,
            "light": True,
        }
        self.unidades_series = {
            "count": "Count (0.1s)",
            "current": "Current (mA)",
            "light": "Light (mV)",
        }
        self._redesenho_agendado = False
        self.bind(pos=self._agendar_redesenho, size=self._agendar_redesenho)
        with self.canvas:
            Color(0.08, 0.08, 0.08, 1)
            self.fundo = Rectangle(pos=self.pos, size=self.size)
            Color(0.25, 0.25, 0.25, 1)
            self.grade_horizontal = []
            self.grade_vertical = []
            for _ in range(5):
                self.grade_horizontal.append(Line(width=1))
                self.grade_vertical.append(Line(width=1))
            Color(0.2, 0.7, 1, 1)
            self.linha_count = Line(width=1.8)
            Color(1, 0.65, 0.2, 1)
            self.linha_current = Line(width=1.8)
            Color(0.35, 0.9, 0.4, 1)
            self.linha_light = Line(width=1.8)

        self.pontos_interativos = []
        self.rotulos_y = [
            Label(
                color=(0.82, 0.82, 0.82, 1),
                font_size="11sp",
                size_hint=(None, None),
                halign="right",
                valign="middle",
            )
            for _ in range(5)
        ]
        self.rotulos_x = [
            Label(
                color=(0.82, 0.82, 0.82, 1),
                font_size="11sp",
                size_hint=(None, None),
                halign="center",
                valign="middle",
            )
            for _ in range(5)
        ]
        self.titulo_x = Label(
            text="Tempo (s)",
            color=(0.9, 0.9, 0.9, 1),
            font_size="12sp",
            size_hint=(None, None),
            halign="center",
            valign="middle",
        )
        self.titulo_y = Label(
            text="Valor",
            color=(0.9, 0.9, 0.9, 1),
            font_size="12sp",
            size_hint=(None, None),
            halign="left",
            valign="middle",
        )
        self.tooltip = Label(
            text="",
            color=(1, 1, 1, 1),
            font_size="11sp",
            size_hint=(None, None),
            size=(190, 42),
            padding=(6, 4),
            halign="left",
            valign="middle",
            opacity=0,
        )
        with self.tooltip.canvas.before:
            Color(0.1, 0.1, 0.1, 0.95)
            self.tooltip_fundo = Rectangle(
                pos=self.tooltip.pos,
                size=self.tooltip.size,
            )
        self.tooltip.bind(
            pos=self._atualizar_fundo_tooltip,
            size=self._atualizar_fundo_tooltip,
        )
        for rotulo in (*self.rotulos_y, *self.rotulos_x, self.titulo_x, self.titulo_y):
            self.add_widget(rotulo)
        self.add_widget(self.tooltip)
        Window.bind(mouse_pos=self._quando_mouse_move)
        self._redesenhar()

    def adicionar_amostra(self, _tempo_origem, count, current, light):
        # O contador da aquisição pode reiniciar ao começar outra leitura.
        # O gráfico mantém um relógio próprio para o eixo X nunca voltar no tempo.
        tempo_continuo = self.tempo_grafico
        self.amostras.append(
            (
                tempo_continuo,
                float(count),
                float(current),
                float(light),
            )
        )
        self.tempo_grafico += self.intervalo_amostra
        self._agendar_redesenho()

    def definir_serie(self, nome, ativa):
        if nome in self.series_ativas:
            self.series_ativas[nome] = bool(ativa)
            self._agendar_redesenho()

    def limpar(self):
        self.amostras.clear()
        self.tempo_grafico = 0.0
        self.tooltip.opacity = 0
        self._agendar_redesenho()

    def _agendar_redesenho(self, *args):
        if not self._redesenho_agendado:
            self._redesenho_agendado = True
            Clock.schedule_once(self._redesenhar, 0)

    def _redesenhar(self, *args):
        self._redesenho_agendado = False
        self.pontos_interativos = []
        self.fundo.pos = self.pos
        self.fundo.size = self.size
        margem_esquerda = min(72, self.width * 0.16)
        margem_direita = min(22, self.width * 0.05)
        # Mantém os rótulos do eixo X afastados dos valores do eixo Y.
        margem_inferior = max(58, min(70, self.height * 0.26))
        # Reserva espaço para o título/unidade do eixo Y, separado do maior valor.
        margem_superior = max(40, min(52, self.height * 0.2))
        esquerda = self.x + margem_esquerda
        direita = self.right - margem_direita
        baixo = self.y + margem_inferior
        alto = self.top - margem_superior
        if direita <= esquerda or alto <= baixo:
            return

        for indice, linha in enumerate(self.grade_horizontal):
            y = baixo + (alto - baixo) * indice / 4
            linha.points = [esquerda, y, direita, y]
        for indice, linha in enumerate(self.grade_vertical):
            x = esquerda + (direita - esquerda) * indice / 4
            linha.points = [x, baixo, x, alto]

        pontos = list(self.amostras)
        series = {
            "count": (1, self.linha_count),
            "current": (2, self.linha_current),
            "light": (3, self.linha_light),
        }
        indices_ativos = [
            indice
            for nome, (indice, _) in series.items()
            if self.series_ativas[nome]
        ]
        self._atualizar_unidade_y()
        for nome, (_, linha) in series.items():
            if not self.series_ativas[nome]:
                linha.points = []

        if not pontos:
            self.linha_count.points = []
            self.linha_current.points = []
            self.linha_light.points = []
            self._atualizar_rotulos(
                esquerda, direita, baixo, alto, 0, 1, 0, 0
            )
            return

        tempo_minimo = pontos[0][0]
        tempo_maximo = pontos[-1][0]
        if tempo_maximo == tempo_minimo:
            tempo_maximo = tempo_minimo + 0.1

        if not indices_ativos:
            minimo, maximo = 0, 1
            self.linha_count.points = []
            self.linha_current.points = []
            self.linha_light.points = []
            self._atualizar_rotulos(
                esquerda,
                direita,
                baixo,
                alto,
                minimo,
                maximo,
                tempo_minimo,
                tempo_maximo,
            )
            return

        minimo = min(
            amostra[indice]
            for amostra in pontos
            for indice in indices_ativos
        )
        maximo = max(
            amostra[indice]
            for amostra in pontos
            for indice in indices_ativos
        )
        if maximo == minimo:
            margem = max(abs(maximo) * 0.05, 1)
            minimo -= margem
            maximo += margem
        else:
            margem = (maximo - minimo) * 0.05
            minimo -= margem
            maximo += margem

        def serie(nome, indice):
            pontos_linha = []
            for amostra in pontos:
                x = esquerda + (
                    (amostra[0] - tempo_minimo)
                    / (tempo_maximo - tempo_minimo)
                    * (direita - esquerda)
                )
                y = baixo + (amostra[indice] - minimo) / (maximo - minimo) * (alto - baixo)
                pontos_linha.extend((x, y))
                self.pontos_interativos.append(
                    (nome, x, y, amostra[0], amostra[indice])
                )
            return pontos_linha

        for nome, (indice, linha) in series.items():
            linha.points = (
                serie(nome, indice) if self.series_ativas[nome] else []
            )

        self._atualizar_rotulos(
            esquerda,
            direita,
            baixo,
            alto,
            minimo,
            maximo,
            tempo_minimo,
            tempo_maximo,
        )

    def _atualizar_fundo_tooltip(self, *args):
        self.tooltip_fundo.pos = self.tooltip.pos
        self.tooltip_fundo.size = self.tooltip.size

    def _ponto_mais_proximo(self, x, y, limite=34):
        if not self.pontos_interativos:
            return None
        ponto = min(
            self.pontos_interativos,
            key=lambda item: hypot(item[1] - x, item[2] - y),
        )
        return ponto if hypot(ponto[1] - x, ponto[2] - y) <= limite else None

    def _quando_mouse_move(self, _window, posicao):
        if not self.get_root_window():
            return
        x, y = self.to_widget(*posicao)
        if not self.collide_point(x, y):
            self.tooltip.opacity = 0
            return

        ponto = self._ponto_mais_proximo(x, y, limite=42)
        if not ponto:
            self.tooltip.opacity = 0
            return

        nome, ponto_x, ponto_y, valor_x, valor_y = ponto
        self.tooltip.text = (
            f"{nome.title()}\n"
            f"X: {valor_x:.3f} s\n"
            f"Y: {self._formatar_numero(valor_y)} {self.unidades_series[nome].split(' ', 1)[-1].strip('()')}"
        )
        self.tooltip.texture_update()
        self.tooltip.size = (190, 54)
        self.tooltip.pos = (
            min(x + 12, self.right - self.tooltip.width - 4),
            min(y + 12, self.top - self.tooltip.height - 4),
        )
        self.tooltip.opacity = 1

    def _atualizar_rotulos(
        self,
        esquerda,
        direita,
        baixo,
        alto,
        minimo,
        maximo,
        tempo_minimo,
        tempo_maximo,
    ):
        for indice, rotulo in enumerate(self.rotulos_y):
            fracao = indice / 4
            y = baixo + (alto - baixo) * fracao
            rotulo.text = self._formatar_numero(
                minimo + (maximo - minimo) * fracao
            )
            rotulo.size = (max(48, esquerda - self.x - 8), 20)
            rotulo.pos = (self.x, y - 10)
            rotulo.text_size = rotulo.size

        for indice, rotulo in enumerate(self.rotulos_x):
            fracao = indice / 4
            x = esquerda + (direita - esquerda) * fracao
            rotulo.text = self._formatar_numero(
                tempo_minimo + (tempo_maximo - tempo_minimo) * fracao
            )
            rotulo.size = (64, 20)
            rotulo.pos = (x - 32, baixo - 32)
            rotulo.text_size = rotulo.size

        self.titulo_y.size = (min(520, self.width - 8), 20)
        self.titulo_y.pos = (self.x + 4, alto + 12)
        self.titulo_y.text_size = self.titulo_y.size
        self.titulo_x.size = (100, 20)
        self.titulo_x.pos = (
            esquerda + (direita - esquerda) / 2 - 50,
            self.y + 1,
        )
        self.titulo_x.text_size = self.titulo_x.size

    def _atualizar_unidade_y(self):
        unidades_ativas = [
            unidade
            for nome, unidade in self.unidades_series.items()
            if self.series_ativas[nome]
        ]
        if unidades_ativas:
            self.titulo_y.text = "Eixo Y: " + " | ".join(unidades_ativas)
        else:
            self.titulo_y.text = "Eixo Y: nenhuma série selecionada"

    @staticmethod
    def _formatar_numero(valor):
        absoluto = abs(valor)
        if absoluto >= 1_000_000 or (0 < absoluto < 0.001):
            return f"{valor:.2e}"
        if absoluto >= 100:
            return f"{valor:.0f}"
        if absoluto >= 10:
            return f"{valor:.1f}"
        return f"{valor:.3f}"



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
        self.duplo_clique_callback = None

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

    # def on_touch_down(self, touch):
    #     if (
    #         self.pasta
    #         and not touch.is_mouse_scrolling
    #         and self.collide_point(*touch.pos)
    #     ):
    #         # Permite abrir/fechar a pasta clicando na linha inteira,
    #         # inclusive no ícone ou no nome, e não somente na seta.
    #         if isinstance(self.parent, TreeView):
    #             self.parent.toggle_node(self)
    #         return True
    #
    #     if (
    #         touch.is_double_tap
    #         and self.caminho
    #         and self.caminho.is_file()
    #         and self.duplo_clique_callback
    #     ):
    #         self.duplo_clique_callback(self)
    #     return super().on_touch_down(touch)


class ArvoreArquivos(TreeView):
    altura_conteudo = NumericProperty(40)

    """Árvore Ano/Mês/Dia dos arquivos de leitura."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.hide_root = True
        self.indent_level = 22
        self.caminho_base = None
        self.selecao_callback = None
        self.duplo_clique_callback = None

    def recarregar(self, caminho_base, data_filtro=None):
        self.caminho_base = Path(caminho_base)
        self.altura_conteudo = 40
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
            self.altura_conteudo = 30
            return 0

        nos_pasta = {}
        quantidade_nos = 0
        for arquivo in arquivos:
            relativo = arquivo.parent.relative_to(self.caminho_base)
            pai = self.root
            acumulado = self.caminho_base
            for parte in relativo.parts:
                acumulado = acumulado / parte
                if acumulado not in nos_pasta:
                    no_pasta = self.add_node(NoArvoreArquivos(acumulado, pasta=True), pai)
                    # Mantem a arvore compacta: abre somente Ano e Mes
                    # (por exemplo, 2026/07). Os dias ficam recolhidos.
                    nivel = len(acumulado.relative_to(self.caminho_base).parts)
                    no_pasta.is_open = nivel <= 2
                    nos_pasta[acumulado] = no_pasta
                    quantidade_nos += 1
                pai = nos_pasta[acumulado]
            no_arquivo = self.add_node(NoArvoreArquivos(arquivo), pai)
            no_arquivo.bind(is_selected=self._quando_selecionado)
            no_arquivo.duplo_clique_callback = self._quando_duplo_clique
            quantidade_nos += 1
        self.altura_conteudo = max(40, quantidade_nos * 30)
        return len(arquivos)

    def _quando_selecionado(self, no, selecionado):
        if selecionado and self.selecao_callback:
            self.selecao_callback(self, no)

    def _quando_duplo_clique(self, no):
        if self.selecao_callback:
            self.selecao_callback(self, no)
        if self.duplo_clique_callback:
            self.duplo_clique_callback(self, no)


class TelaPrincipalLeitora(Screen):
    test_mode = StringProperty("MANUAL")
    reading_type = StringProperty("PERSONAL_DOSE")
    dose_channel = StringProperty("HP10")
    dosimeter_status = StringProperty(
        "Aguardando leitura do código de barras"
    )
    start_allowed = BooleanProperty(False)
    loaded_ecc = StringProperty("—")
    loaded_bl = StringProperty("—")
    loaded_rcf = StringProperty("—")
    automatic_base_file_name = StringProperty("—")
    automatic_file_name = StringProperty("—")
    acquisition_active = BooleanProperty(False)
    test_session_active = BooleanProperty(False)
    hp10_complete = BooleanProperty(False)
    hp007_complete = BooleanProperty(False)
    baseline_mode_active = BooleanProperty(False)
    bl_update_mode = StringProperty("MANUAL")
    bl_hp10_count = NumericProperty(0)
    bl_hp007_count = NumericProperty(0)
    bl_hp10_target = NumericProperty(1)
    bl_hp007_target = NumericProperty(1)
    bl_target_reached = BooleanProperty(False)
    ref_light_mode_active = BooleanProperty(False)
    ref_light_reading_active = BooleanProperty(False)
    ref_light_repetition_count = NumericProperty(0)
    ref_light_target = NumericProperty(1)
    ref_light_target_reached = BooleanProperty(False)
    ref_light_average = NumericProperty(0)
    high_dose_state = StringProperty(ESTADO_LEITURA_NORMAL)

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
        self.database = None
        self.caminho_arquivo = None
        self.serial_connection = None
        self.buffer_serial = ""
        self.serial_reader_thread = None
        self.serial_stop_event = Event()
        self.serial_frame_queue = Queue()
        self.serial_decoder = SerialFrameDecoder()
        self.serial_log_lock = Lock()
        self.serial_bytes_received = 0
        self.serial_frames_received = 0
        self.serial_invalid_frames = 0
        self.serial_last_error = None
        self.serial_first_frame_event = None
        self.serial_silence_event = None
        self.serial_sample_received = False
        self._respondeu_solicitacao_parametros = False
        self.valor_count = 0
        self.valor_current = 0
        self.valor_light = 0
        self.log_arquivo = None
        self.log_serial_arquivo = None
        self.caminho_log_serial = None
        self.leitura_evento = None
        self.nova_linha = True
        self.current_measurement_id = None
        self.validated_dosimeter = None
        self.validated_reader = None
        self.applied_parameters = None
        self.active_test_session_id = None
        self.active_test_dosimeter_id = None
        self.active_test_reading_type = None
        self.bl_selection_popup = None
        self.re_read_popup = None
        self.baseline_save_popup = None
        self.high_dose_popup = None
        self.high_dose_restart_button = None
        self.high_dose_restart_locked = False
        self.last_dose_details = None
        self.fled_by_pled = dict(FLED_PADRAO_POR_PLED)
        self._selected_pled = "4"
        self.ref_light_readings = []
        self._bl_apply_button = None
        self._bl_selection_summary = None
        self.bl_selected_measurements = {"HP10": None, "HP007": None}
        self.bl_selected_values = {"HP10": None, "HP007": None}
        Clock.schedule_once(self.atualizar_portas_serial, 0)
        Clock.schedule_once(self.atualizar_leitoras_cadastradas, 0)
        # O tamanho do conteúdo do ScrollView só fica definitivo após o
        # primeiro ciclo de layout. Reposiciona no topo para não esconder os
        # controles de conexão em resoluções menores.
        Clock.schedule_once(self._mostrar_topo, 0)

    def _mostrar_topo(self, _dt):
        try:
            self.ids.rolagem_principal.scroll_y = 1
        except KeyError:
            pass

    def obter_database(self):
        if self.database is not None:
            return self.database
        aplicativo = App.get_running_app()
        if aplicativo is None or not hasattr(aplicativo, "database"):
            raise RuntimeError("Banco de dados não inicializado")
        self.database = aplicativo.database
        return self.database

    def selecionar_modo(self, mode):
        normalized_mode = str(mode).strip().upper()
        if normalized_mode not in ("MANUAL", "DOSIMETER_ID"):
            raise ValueError("Modo de teste inválido")
        if self.log_arquivo:
            self.atualizar_status(
                "Finalize ou interrompa a leitura antes de trocar o modo."
            )
            return
        if self.ref_light_mode_active:
            self.atualizar_status(
                "Finalize o modo Ref Light antes de trocar o modo."
            )
            return
        if self.baseline_mode_active and normalized_mode != self.test_mode:
            self.atualizar_status(
                "Finalize ou cancele o modo BL antes de trocar o modo."
            )
            return
        if self.test_session_active:
            self.atualizar_status(
                "Conclua Hp(10) e Hp(0,07) antes de trocar o modo."
            )
            return
        self.test_mode = normalized_mode
        self.ids.mode_manager.current = self.test_mode
        manual_active = normalized_mode == "MANUAL"
        self.ids.manual_panel.opacity = 1 if manual_active else 0
        self.ids.manual_panel.disabled = not manual_active
        self.ids.dosimeter_panel.opacity = 0 if manual_active else 1
        self.ids.dosimeter_panel.disabled = manual_active
        if normalized_mode == "MANUAL":
            self.reading_type = "PERSONAL_DOSE"
        self.start_allowed = normalized_mode == "MANUAL"
        if normalized_mode == "DOSIMETER_ID":
            self.atualizar_leitoras_cadastradas()
            self._invalidar_dosimetro(
                "Aguardando leitura do código de barras"
            )
            self.agendar_foco_dosimetro()

    def botao_apagar(self):
        if self.log_arquivo:
            self.atualizar_status(
                "Finalize ou interrompa a leitura antes de apagar."
            )
            return
        if self.ref_light_mode_active:
            self.atualizar_status(
                "Finalize o modo Ref Light antes de apagar."
            )
            return
        if self.test_mode == "DOSIMETER_ID":
            if self.baseline_mode_active:
                if self.bl_update_mode == "AUTOMATICO":
                    self.aplicar_ultimas_leituras_bl()
                else:
                    self.abrir_selecao_bl()
                return
            if self.test_session_active:
                self.atualizar_status(
                    "Conclua o teste atual antes de realizar outro zeramento."
                )
                return
            self._resetar_estado_bl()
            self.baseline_mode_active = True
            self.reading_type = "BACKGROUND"
            self.dosimeter_status = (
                "MODO BL ATIVO • escolha a grandeza e a quantidade de leituras"
            )
            self.atualizar_status(
                "Zeramento iniciado; modo BL ativo sem troca automática de grandeza."
            )
            self._atualizar_parametros_grandeza()
        self.enviar_comando_sudo("zerar")

    def carregar_configuracoes(self):
        """Load user preferences without storing them in the database."""
        mode = "MANUAL"
        fled_by_pled = dict(FLED_PADRAO_POR_PLED)
        try:
            if SETTINGS_PATH.is_file():
                settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                saved_mode = str(settings.get("bl_update_mode", "")).upper()
                if saved_mode in ("AUTOMATICO", "MANUAL"):
                    mode = saved_mode
                saved_fled = settings.get("fled_by_pled", {})
                if isinstance(saved_fled, dict):
                    for pled in FLED_PADRAO_POR_PLED:
                        value = saved_fled.get(pled)
                        if value is None and pled in ("2", "3"):
                            fled_by_pled[pled] = None
                        elif value is not None:
                            fled_by_pled[pled] = parse_number(
                                value,
                                f"fLed P{pled}",
                                positive=True,
                            )
        except (AttributeError, OSError, TypeError, ValueError, json.JSONDecodeError):
            mode = "MANUAL"
        self.bl_update_mode = mode
        self.fled_by_pled = fled_by_pled
        self._sincronizar_botao_modo_bl()
        self.atualizar_fled_exibido(self._selected_pled)
        return mode

    def _salvar_configuracoes(self):
        settings = {}
        try:
            if SETTINGS_PATH.is_file():
                loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    settings.update(loaded)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        settings["bl_update_mode"] = self.bl_update_mode
        settings["fled_by_pled"] = self.fled_by_pled
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = SETTINGS_PATH.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(SETTINGS_PATH)

    def atualizar_fled_exibido(self, pled):
        pled = str(pled).strip()
        if pled not in FLED_PADRAO_POR_PLED:
            return
        self._selected_pled = pled
        try:
            field = self.manager.get_screen("parametros").ids.fled_input
        except (AttributeError, KeyError):
            return
        value = self.fled_by_pled.get(pled)
        field.text = "" if value is None else f"{float(value):.10g}"

    def salvar_fled_atual(self):
        """Validate and persist the fLed associated with the selected PLed."""
        try:
            screen = self.manager.get_screen("parametros")
            pled = screen.ids.potencia_input.text.strip()
            text_value = screen.ids.fled_input.text.strip()
        except (AttributeError, KeyError):
            return False
        if pled not in FLED_PADRAO_POR_PLED:
            self.atualizar_status("PLed inválido para salvar fLed.")
            return False
        if not text_value:
            if pled not in ("2", "3"):
                self.atualizar_status(f"fLed de P{pled} deve ser maior que zero.")
                return False
            value = None
        else:
            try:
                value = parse_number(text_value, f"fLed P{pled}", positive=True)
            except ValueError as error:
                self.atualizar_status(str(error))
                return False
        self.fled_by_pled[pled] = value
        try:
            self._salvar_configuracoes()
        except OSError as error:
            self.atualizar_status(f"Não foi possível salvar fLed: {error}")
            return False
        return True

    def obter_fled(self, pled):
        pled = str(pled).strip()
        value = self.fled_by_pled.get(pled)
        if value is None:
            raise ValueError(f"fLed de P{pled} ainda não foi calibrado")
        return parse_number(value, f"fLed P{pled}", positive=True)

    def _sincronizar_botao_modo_bl(self):
        try:
            button = self.manager.get_screen("parametros").ids.bl_mode_button
        except (AttributeError, KeyError):
            return
        automatic = self.bl_update_mode == "AUTOMATICO"
        button.text = (
            "Modo BL: Automático — usar a última leitura"
            if automatic
            else "Modo BL: Manual — escolher a leitura ao finalizar"
        )
        button.background_color = (
            (0.08, 0.55, 0.95, 1)
            if automatic
            else (0.36, 0.36, 0.36, 1)
        )

    def alternar_modo_bl(self):
        self.bl_update_mode = (
            "MANUAL" if self.bl_update_mode == "AUTOMATICO" else "AUTOMATICO"
        )
        self._sincronizar_botao_modo_bl()
        try:
            self._salvar_configuracoes()
            persistence = "Configuração salva."
        except OSError as error:
            persistence = f"Não foi possível salvar a preferência: {error}"
        behavior = (
            "a última leitura de cada grandeza será aplicada ao finalizar."
            if self.bl_update_mode == "AUTOMATICO"
            else "o operador escolherá as leituras ao finalizar."
        )
        display_mode = (
            "automático" if self.bl_update_mode == "AUTOMATICO" else "manual"
        )
        self.atualizar_status(
            f"Modo BL {display_mode}: {behavior} {persistence}"
        )
        return self.bl_update_mode

    def _resetar_estado_bl(self):
        self.bl_hp10_count = 0
        self.bl_hp007_count = 0
        self.bl_hp10_target = 1
        self.bl_hp007_target = 1
        self.bl_target_reached = False
        self.bl_selected_measurements = {"HP10": None, "HP007": None}
        self.bl_selected_values = {"HP10": None, "HP007": None}
        try:
            self.ids.bl_repetition_input.text = "1"
        except KeyError:
            pass

    def definir_repeticoes_bl(self, value):
        if not self.baseline_mode_active:
            return
        text = str(value).strip()
        if not text:
            return
        try:
            target = int(text)
        except ValueError:
            return
        target = min(max(target, 1), 99)
        if self.dose_channel == "HP007":
            self.bl_hp007_target = target
        else:
            self.bl_hp10_target = target
        self._atualizar_meta_bl()

    def _contagem_bl_atual(self):
        return (
            int(self.bl_hp007_count)
            if self.dose_channel == "HP007"
            else int(self.bl_hp10_count)
        )

    def _meta_bl_atual(self):
        return (
            int(self.bl_hp007_target)
            if self.dose_channel == "HP007"
            else int(self.bl_hp10_target)
        )

    def _atualizar_meta_bl(self):
        if not self.baseline_mode_active:
            self.bl_target_reached = False
            return
        self.bl_target_reached = (
            self._contagem_bl_atual() >= self._meta_bl_atual()
        )

    def _resetar_estado_ref_light(self):
        self.ref_light_readings = []
        self.ref_light_repetition_count = 0
        self.ref_light_target = 1
        self.ref_light_target_reached = False
        self.ref_light_average = 0
        try:
            self.ids.ref_light_repetition_input.text = "1"
        except KeyError:
            pass

    def definir_repeticoes_ref_light(self, value):
        if not self.ref_light_mode_active:
            return
        text = str(value).strip()
        if not text:
            return
        try:
            target = int(text)
        except ValueError:
            return
        if target < 1:
            target = 1
        self.ref_light_target = target
        self.ref_light_target_reached = (
            self.ref_light_repetition_count >= self.ref_light_target
        )
        self._atualizar_status_ref_light()

    def _atualizar_status_ref_light(self):
        if not self.ref_light_mode_active:
            return
        count = int(self.ref_light_repetition_count)
        target = int(self.ref_light_target)
        if self.ref_light_reading_active:
            self.dosimeter_status = (
                f"MODO REF LIGHT • leitura {count + 1}/{target} em andamento"
            )
        elif self.ref_light_target_reached:
            self.dosimeter_status = (
                f"MODO REF LIGHT • {count}/{target} • finalizando"
            )
        else:
            self.dosimeter_status = (
                f"MODO REF LIGHT • {count}/{target} • pressione Start"
            )

    def _iniciar_ref_light_leitura(self):
        if not self.ref_light_mode_active:
            return False
        if self.ref_light_target_reached:
            self.atualizar_status(
                "A quantidade de repetições foi atingida; finalize o modo Ref Light."
            )
            return False
        if self.ref_light_reading_active or self.acquisition_active:
            self.atualizar_status("Já existe uma leitura Ref Light em andamento.")
            return False
        if not self.serial_aberta():
            self.atualizar_status("Serial desconectada. Verifique a porta.")
            lbl_erro.text = "Connect to OSL System!"
            popupNomeArquivo.open()
            return False

        self.string_log = ""
        self.ids.label_dose.text = "0.000"
        self.ids.label_current.text = "0"
        self.ids.label_light.text = "0"
        self.ids.label_count.text = "0"
        self.ids.LabelDose.text = "Integral Light"
        self.soma = 0
        self.soma_luz = 0
        self.contador = 0
        self.f_fechar_log = False
        self.f_luz_ref = True
        self.ref_light_reading_active = True
        self.acquisition_active = True
        self.nova_linha = True
        try:
            self.ids.grafico_tempo_real.limpar()
        except (AttributeError, KeyError):
            pass
        self._atualizar_status_ref_light()
        self._armar_watchdog_primeiro_frame()
        self.enviar_comando_sudo("leitura")
        return True

    def _finalizar_ref_light_leitura(self, status="CONCLUIDO", notes=None):
        if not self.ref_light_reading_active:
            return False
        self._cancelar_watchdogs_serial()
        self.ref_light_reading_active = False
        self.acquisition_active = False
        self.f_luz_ref = False
        self.f_fechar_log = False

        if status != "CONCLUIDO":
            self.atualizar_status(
                f"Leitura Ref Light interrompida: {notes or status}."
            )
            self._atualizar_status_ref_light()
            return False

        self.ref_light_readings.append(float(self.soma_luz))
        self.ref_light_repetition_count = len(self.ref_light_readings)
        self.ref_light_average = sum(self.ref_light_readings) / len(
            self.ref_light_readings
        )
        self.ids.label_dose.text = self.formatar_dose(self.soma_luz)
        self.ref_light_target_reached = (
            self.ref_light_repetition_count >= self.ref_light_target
        )
        self._atualizar_status_ref_light()
        if self.ref_light_target_reached:
            self._finalizar_modo_ref_light()
        return True

    def _finalizar_modo_ref_light(self):
        if self.ref_light_reading_active:
            self.atualizar_status(
                "Aguarde o término da leitura Ref Light antes de finalizar."
            )
            return False
        if not self.ref_light_readings:
            self.ref_light_mode_active = False
            self.ref_light_target_reached = False
            self.dosimeter_status = "Modo Ref Light encerrado sem leituras."
            return False

        try:
            workbook_path, average = append_ref_light_session(
                self.ref_light_readings,
                output_path=REF_LIGHT_XLSX_PATH,
            )
        except (ImportError, OSError, RuntimeError, TypeError, ValueError) as error:
            message = f"Erro ao salvar Ref Light no XLSX: {error}"
            # Keep the mode active so the operator can retry after closing the
            # workbook or correcting the installation. Do not leave the
            # dosimeter panel showing the ambiguous status "finalizando".
            self.dosimeter_status = message
            self.atualizar_status(message)
            return False

        self.ref_light_average = average
        self.ref_light_mode_active = False
        self.ref_light_target_reached = False
        self.ids.LabelDose.text = "Média Ref Light"
        self.ids.label_dose.text = self.formatar_dose(average)
        self.dosimeter_status = (
            f"Ref Light concluído • {len(self.ref_light_readings)} leitura(s) • "
            f"média {average:.10g} • {workbook_path.name}"
        )
        self.atualizar_status(
            f"Ref Light salvo em {workbook_path} • média {average:.10g}"
        )
        return True

    def agendar_foco_dosimetro(self, selecionar=True):

        Clock.schedule_once(
            lambda _dt: self._focar_dosimetro(selecionar),
            0,
        )

    def _focar_dosimetro(self, selecionar):
        if self.test_mode != "DOSIMETER_ID":
            return
        try:
            field = self.ids.dosimeter_id_input
        except KeyError:
            return
        field.focus = True
        if selecionar and field.text:
            field.select_all()

    def dosimetro_texto_alterado(self, value):
        if self.test_mode != "DOSIMETER_ID":
            return
        if self.test_session_active:
            return
        normalized = scanner_text(value)
        current_id = (
            self.validated_dosimeter["dosimeter_id"]
            if self.validated_dosimeter
            else None
        )
        if normalized != current_id:
            self._invalidar_dosimetro(
                "Pressione Enter para consultar o dosímetro",
                preserve_filename=False,
            )
            # Permite iniciar clicando em Start depois de preencher o ID
            # manualmente. O Enter continua funcionando para leitoras de
            # código de barras, mas não deve ser obrigatório para o operador.
            reader_id = self.ids.reader_spinner.text.strip()
            if len(normalized) == 10 and reader_id not in (
                "",
                "Selecione a leitora",
            ):
                self.confirmar_codigo_dosimetro(normalized)

    def confirmar_codigo_dosimetro(self, value=None):
        try:
            field = self.ids.dosimeter_id_input
        except KeyError:
            return False
        normalized = scanner_text(field.text if value is None else value)
        field.text = normalized
        try:
            dosimeter = self.obter_database().get_valid_dosimeter_for_test(
                normalized
            )
            reader_id = self.ids.reader_spinner.text.strip()
            if reader_id in ("", "Selecione a leitora"):
                raise ValueError("Selecione uma leitora antes de iniciar")
            reader = self.obter_database().get_valid_reader_for_test(reader_id)
        except (TypeError, ValueError) as error:
            self._invalidar_dosimetro(str(error))
            self.agendar_foco_dosimetro()
            return False

        self.validated_dosimeter = dosimeter
        self.validated_reader = reader
        self.loaded_rcf = self._formatar_coeficiente(reader["rcf"])
        self._atualizar_parametros_grandeza()
        if self.baseline_mode_active:
            self.dosimeter_status = (
                f"MODO BL ATIVO • dosímetro válido • "
                f"{self._nome_grandeza(self.dose_channel)} • "
                f"{self._contagem_bl_atual()}/{self._meta_bl_atual()} leituras"
            )
        else:
            self.dosimeter_status = (
                f"Dosímetro válido • leitora {reader['reader_id']} • "
                f"{self._nome_grandeza(self.dose_channel)} selecionado • "
                "pressione Start"
            )
        self.start_allowed = True
        self.agendar_foco_dosimetro()
        return True

    def leitora_selecionada(self, _reader_id):
        if self.test_mode == "DOSIMETER_ID":
            try:
                field = self.ids.dosimeter_id_input
            except KeyError:
                return
            if scanner_text(field.text):
                self.confirmar_codigo_dosimetro()

    @staticmethod
    def _nome_grandeza(channel):
        return "Hp(0,07)" if channel == "HP007" else "Hp(10)"

    def selecionar_grandeza(self, channel):
        normalized = str(channel).strip().upper()
        if normalized not in ("HP10", "HP007"):
            raise ValueError("Grandeza deve ser Hp(10) ou Hp(0,07)")
        if self.log_arquivo:
            self.atualizar_status(
                "Finalize a aquisição atual antes de trocar a grandeza."
            )
            return False
        if self.baseline_mode_active:
            self.dose_channel = normalized
            target = (
                self.bl_hp007_target
                if normalized == "HP007"
                else self.bl_hp10_target
            )
            try:
                self.ids.bl_repetition_input.text = str(int(target))
            except KeyError:
                pass
            self._atualizar_meta_bl()
            self._atualizar_parametros_grandeza()
            self.dosimeter_status = (
                f"MODO BL ATIVO • {self._nome_grandeza(normalized)} • "
                f"{self._contagem_bl_atual()}/{self._meta_bl_atual()} leituras"
            )
            return True
        if self.test_session_active and normalized != self.dose_channel:
            self.atualizar_status(
                f"Conclua {self._nome_grandeza(self.dose_channel)} antes de "
                "comutar a grandeza."
            )
            return False
        if self.test_session_active and (
            (normalized == "HP10" and self.hp10_complete)
            or (normalized == "HP007" and self.hp007_complete)
        ):
            self.atualizar_status(
                f"{self._nome_grandeza(normalized)} já foi concluído nesta sessão."
            )
            return False
        self.dose_channel = normalized
        self._atualizar_parametros_grandeza()
        if self.validated_dosimeter:
            self.dosimeter_status = (
                f"{self._nome_grandeza(normalized)} selecionado • pressione Start"
            )
        return True

    def _atualizar_parametros_grandeza(self):
        dosimeter = self.validated_dosimeter
        if not dosimeter:
            return
        if self.dose_channel == "HP007":
            ecc = dosimeter["ecc_hp007"]
            baseline = dosimeter["bl_hp007"]
        else:
            ecc = dosimeter["ecc_hp10"]
            baseline = dosimeter["bl_hp10"]
        self.loaded_ecc = self._formatar_coeficiente(ecc)
        self.loaded_bl = self._formatar_coeficiente(baseline)
        self.automatic_base_file_name = dosimeter_filename(
            dosimeter["dosimeter_id"],
            dose_channel=self.dose_channel,
            reading_type=self.reading_type,
        )
        self.atualizar_observacao_arquivo()

    def atualizar_observacao_arquivo(self, _value=None):
        """Refresh the generated filename with the optional observation."""
        base_name = self.automatic_base_file_name
        if base_name in ("", "—"):
            return
        try:
            observation = self.ids.arquivo_observacao_input.text
            self.automatic_file_name = append_filename_observation(
                base_name,
                observation,
            )
        except (KeyError, ValueError):
            self.automatic_file_name = base_name

    def atualizar_leitoras_cadastradas(self, *_args):
        try:
            spinner = self.ids.reader_spinner
        except KeyError:
            return
        try:
            readers = self.obter_database().search_readers(active=True)
        except (OSError, sqlite3.Error, RuntimeError) as error:
            self.atualizar_status(f"Erro ao carregar leitoras: {error}")
            return
        values = tuple(reader["reader_id"] for reader in readers)
        previous = spinner.text
        spinner.values = values
        if previous in values:
            spinner.text = previous
        elif len(values) == 1:
            spinner.text = values[0]
        else:
            spinner.text = "Selecione a leitora"

    def preparar_proximo_dosimetro(self):
        if self.test_mode != "DOSIMETER_ID":
            return
        try:
            self.ids.dosimeter_id_input.text = ""
        except KeyError:
            pass
        self.active_test_session_id = None
        self.active_test_dosimeter_id = None
        self.active_test_reading_type = None
        self.test_session_active = False
        self.hp10_complete = False
        self.hp007_complete = False
        self.dose_channel = "HP10"
        self._invalidar_dosimetro(
            "Aguardando leitura do código de barras"
        )
        self.agendar_foco_dosimetro(selecionar=False)

    def _invalidar_dosimetro(self, message, preserve_filename=False):
        self.validated_dosimeter = None
        self.validated_reader = None
        self.loaded_ecc = "—"
        self.loaded_bl = "—"
        self.loaded_rcf = "—"
        self.automatic_base_file_name = "—"
        if not preserve_filename:
            self.automatic_file_name = "—"
        try:
            self.ids.arquivo_observacao_input.text = ""
        except KeyError:
            pass
        self.dosimeter_status = message
        self.start_allowed = False

    @staticmethod
    def _formatar_coeficiente(value):
        return f"{float(value):.10g}"

    def _preparar_contexto_teste(self):
        fang = parse_number(
            self.ids.fcal_textInput.text,
            "Fang",
            positive=True,
        )
        fenerg = parse_number(
            self.ids.fenerg_textInput.text,
            "Fenerg",
            positive=True,
        )

        if self.test_mode == "MANUAL":
            baseline = parse_number(
                self.ids.branco_textInput.text,
                "Base Line",
                positive=False,
            )
            ecc = parse_number(
                self.ids.ecc_textInput.text,
                "ECC",
                positive=True,
            )
            rcf = parse_number(
                self.ids.rcf_textInput.text,
                "RCF",
                positive=True,
            )
            file_name = safe_test_filename(
                self.ids.nome_arquivo_input.text
            )
            return {
                "test_mode": "MANUAL",
                "reader_id": None,
                "dosimeter_id": None,
                "file_name": file_name,
                "ecc": ecc,
                "rcf": rcf,
                "fang": fang,
                "fenerg": fenerg,
                "baseline": baseline,
            }

        if not self.start_allowed or not (
            self.validated_dosimeter and self.validated_reader
        ):
            if not self.confirmar_codigo_dosimetro():
                raise ValueError(self.dosimeter_status)
        dosimeter_id = self.validated_dosimeter["dosimeter_id"]
        if self.baseline_mode_active and (
            self._contagem_bl_atual() >= self._meta_bl_atual()
        ):
            raise ValueError(
                f"A meta de {self._meta_bl_atual()} leitura(s) de "
                f"{self._nome_grandeza(self.dose_channel)} foi atingida. "
                "Aumente a quantidade, escolha outra grandeza ou finalize o modo BL."
            )
        if self.test_session_active and (
            dosimeter_id != self.active_test_dosimeter_id
            or self.reading_type != self.active_test_reading_type
        ):
            raise ValueError(
                "A sessão atual deve ser concluída com o mesmo dosímetro e tipo."
            )
        if self.active_test_session_id is None:
            self.active_test_session_id = uuid4().hex
            self.active_test_dosimeter_id = dosimeter_id
            self.active_test_reading_type = self.reading_type
            self.test_session_active = True
        if self.dose_channel == "HP007":
            ecc = float(self.validated_dosimeter["ecc_hp007"])
            baseline = float(self.validated_dosimeter["bl_hp007"])
        else:
            ecc = float(self.validated_dosimeter["ecc_hp10"])
            baseline = float(self.validated_dosimeter["bl_hp10"])
        rcf = float(self.validated_reader["rcf"])
        if self.reading_type == "BACKGROUND":
            ecc = 1.0
            rcf = 1.0
            baseline = 0.0
        self._atualizar_parametros_grandeza()
        file_name = append_filename_observation(
            self.automatic_base_file_name,
            self.ids.arquivo_observacao_input.text,
        )
        self.automatic_file_name = file_name
        return {
            "test_mode": "DOSIMETER_ID",
            "reading_type": self.reading_type,
            "dose_channel": self.dose_channel,
            "test_session_id": self.active_test_session_id,
            "reader_id": self.validated_reader["reader_id"],
            "dosimeter_id": dosimeter_id,
            "file_name": file_name,
            "ecc": ecc,
            "rcf": rcf,
            "fang": fang,
            "fenerg": fenerg,
            "baseline": baseline,
        }

    # Log
    def func_botao_log(self, context=None):
        if not self.log_arquivo:
            self.iniciar_log(context)

    @staticmethod
    def _nome_arquivo_disponivel(directory, filename):
        """Keep second-level filenames short while avoiding same-second collisions."""
        candidate = directory / filename
        if not candidate.exists():
            return filename
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        for sequence in range(2, 1000):
            alternative = safe_test_filename(
                f"{stem}-{sequence}{suffix}"
            )
            if not (directory / alternative).exists():
                return alternative
        raise ValueError("Não foi possível gerar um nome de arquivo disponível")

    def iniciar_log(self, context=None):
        try:
            context = context or self._preparar_contexto_teste()
            nome_arquivo = safe_test_filename(context["file_name"])
        except ValueError as error:
            self.atualizar_status(str(error))
            return False

        data_atual = datetime.now()
        testes_dia_dir = TESTES_DIR / data_atual.strftime("%Y/%m/%d")
        testes_dia_dir.mkdir(parents=True, exist_ok=True)
        nome_arquivo = self._nome_arquivo_disponivel(
            testes_dia_dir,
            nome_arquivo,
        )
        self.automatic_file_name = nome_arquivo
        self.applied_parameters = dict(context)
        self.applied_parameters["high_dose"] = False
        self.applied_parameters["fled"] = 1.0

        try:
            self.current_measurement_id = self.obter_database().add_measurement(
                reader_id=context["reader_id"],
                dosimeter_id=context["dosimeter_id"],
                test_mode=context["test_mode"],
                reading_type=context.get("reading_type"),
                dose_channel=context.get("dose_channel"),
                test_session_id=context.get("test_session_id"),
                file_name=nome_arquivo,
                ecc_applied=context["ecc"],
                rcf_applied=context["rcf"],
                fang_applied=context["fang"],
                fenerg_applied=context["fenerg"],
                baseline_applied=context["baseline"],
                status="EM_ANDAMENTO",
            )

            self.caminho_arquivo = (testes_dia_dir / nome_arquivo).resolve()
            if not self.caminho_arquivo.is_relative_to(TESTES_DIR.resolve()):
                raise ValueError("O arquivo deve permanecer em assets/testes")
            try:
                self.log_arquivo = open(
                    self.caminho_arquivo,
                    "x+",
                    encoding="utf-8",
                    buffering=1,
                )
            except FileExistsError:
                self._atualizar_medicao_com_erro("Arquivo já existe")
                self.current_measurement_id = None
                lbl_erro.text = "File Already Exists."
                popupNomeArquivo.open()
                self.atualizar_status(
                    f"Arquivo já existe: {self.caminho_arquivo}"
                )
                return False

            self.atualizar_status(f"Log iniciado em {self.caminho_arquivo}")

            self.nova_linha = True
            for linha in (
                data_atual.strftime("%d/%m/%Y %H:%M:%S"),
                nome_arquivo,
                "Integral:",
                (
                    "Dose mSv:"
                    if (
                        context.get("reading_type") == "BACKGROUND"
                        and self.bl_update_mode == "AUTOMATICO"
                    )
                    else (
                        "Contagens:"
                        if context.get("reading_type") == "BACKGROUND"
                        else "Dose mSv:"
                    )
                ),
                "Time;Count;Current;Light",
            ):
                self.salvar_log(f"{linha} \n")

            self.contador = 0.1
            self.soma = 0
            self.soma_luz = 0
            self.nova_linha = True
            self.ids.grafico_tempo_real.limpar()
            self.acquisition_active = True
            self._armar_watchdog_primeiro_frame()
            if self.test_mode == "DOSIMETER_ID":
                self.dosimeter_status = (
                    f"Lendo {self._nome_grandeza(self.dose_channel)} • "
                    "aguarde o término da leitura"
                )
            self.enviar_comando_sudo("leitura")
            return True

        except (OSError, sqlite3.Error, TypeError, ValueError) as erro:
            self._atualizar_medicao_com_erro(str(erro))
            self.current_measurement_id = None
            self.log_arquivo = None
            self.acquisition_active = False
            self.atualizar_status(f"Erro ao criar arquivo: {erro}")
            return False

    def fechar_log(self, status="CONCLUIDO", notes=None):
        self._cancelar_watchdogs_serial()
        if not self.log_arquivo:
            return
        nome = self.log_arquivo.name
        completed_channel = (
            self.applied_parameters.get("dose_channel")
            if self.applied_parameters
            else None
        )
        test_complete = False
        final_status = status
        try:
            invalid_high_dose = bool(
                self.applied_parameters
                and self.applied_parameters.get("high_dose")
                and status != "CONCLUIDO"
            )
            if invalid_high_dose:
                dose = 0.0
                self.last_dose_details = None
                self.ids.label_dose.text = "0"
            else:
                dose = self.atualizar_soma_no_log()
            self.log_arquivo.close()
            self.log_arquivo = None
            test_complete = self._finalizar_medicao(status, dose, notes)
            self.atualizar_status(f"Log encerrado: {nome}")
        except (OSError, sqlite3.Error, TypeError, ValueError) as error:
            final_status = "ERRO"
            if self.log_arquivo:
                try:
                    self.log_arquivo.close()
                except OSError:
                    pass
            self.log_arquivo = None
            self._atualizar_medicao_com_erro(str(error))
            self.atualizar_status(f"Erro ao finalizar leitura: {error}")
        finally:
            self.acquisition_active = False
            if self.test_mode == "MANUAL":
                self.ids.nome_arquivo_input.text = ""
            elif test_complete:
                self.preparar_proximo_dosimetro()
            else:
                self._preparar_proxima_grandeza(
                    completed_channel,
                    status=final_status,
                )
            self.applied_parameters = None
            self.current_measurement_id = None
            if self.high_dose_state != ESTADO_LEITURA_NORMAL:
                self._definir_estado_alta_dose(ESTADO_LEITURA_FINALIZADA)
                self._resetar_estado_alta_dose()

    def salvar_log(self, mensagem):
        if self.log_arquivo:
            texto = f"{mensagem}"
            self.log_arquivo.write(texto)
            self.log_arquivo.flush()
            self.string_log += texto

    def atualizar_soma_no_log(self):
        if not self.log_arquivo:
            return 0.0

        self.log_arquivo.flush()
        self.log_arquivo.seek(0)
        linhas = self.log_arquivo.readlines()

        linhas_string = self.string_log.splitlines()

        while len(linhas) < 4:
            linhas.append("\n")

        while len(linhas_string) < 4:
            linhas_string.append("\n")


        baseline_reading = bool(
            self.applied_parameters
            and self.applied_parameters.get("reading_type") == "BACKGROUND"
        )
        display_baseline_as_dose = (
            baseline_reading and self.bl_update_mode == "AUTOMATICO"
        )
        result = (
            self._calcular_dose_exibida_bl_automatico()
            if display_baseline_as_dose
            else (float(self.soma) if baseline_reading else self.calcular_dose())
        )
        linhas[2] = f"Soma: {self.soma}\n"
        result_label = (
            "Dose"
            if display_baseline_as_dose or not baseline_reading
            else "Contagens"
        )
        formatted_result = (
            self.formatar_dose(result)
            if display_baseline_as_dose or not baseline_reading
            else f"{result:.10g}"
        )
        linhas[3] = f"{result_label}: {formatted_result}\n"

        self.log_arquivo.seek(0)
        self.log_arquivo.writelines(linhas)
        self.log_arquivo.truncate()
        self.log_arquivo.flush()

        linhas_string[2] = f"Soma: {self.soma}"
        linhas_string[3] = f"{result_label}: {formatted_result}"

        self.ids.label_dose.text = formatted_result

        self.string_log = "\n".join(linhas_string)
        if not baseline_reading:
            self._registrar_auditoria_dose()
        return result

        #with open(nome_arquivo, "w", encoding="utf-8") as arquivo:
        #    arquivo.writelines(linhas)

    def calcular_dose(self):
        context = self.applied_parameters
        if context is None:
            context = self._preparar_contexto_teste()
        high_dose = bool(context.get("high_dose")) or (
            self.high_dose_state == ESTADO_LEITURA_ALTA_DOSE
        )
        fled = float(context.get("fled", 1.0))
        if high_dose:
            result = calculate_high_dose(
                self.soma,
                fled=fled,
                baseline=context["baseline"],
                rcf=context["rcf"],
                ecc=context["ecc"],
                fang=context["fang"],
                fenerg=context["fenerg"],
            )
            net_signal = (float(self.soma) * fled) - float(context["baseline"])
            formula = (
                "|(soma × fLed) − linha_de_base| × RCF × ECC × Fang × Fenerg"
            )
        else:
            result = calculate_dose(
                self.soma,
                baseline=context["baseline"],
                rcf=context["rcf"],
                ecc=context["ecc"],
                fang=context["fang"],
                fenerg=context["fenerg"],
            )
            net_signal = float(self.soma) - float(context["baseline"])
            formula = "|soma − linha_de_base| × RCF × ECC × Fang × Fenerg"
        self.last_dose_details = {
            "mode": "Alta dose" if high_dose else "Normal",
            "formula": formula,
            "sum": float(self.soma),
            "fled": fled if high_dose else None,
            "baseline": float(context["baseline"]),
            "rcf": float(context["rcf"]),
            "ecc": float(context["ecc"]),
            "fang": float(context["fang"]),
            "fenerg": float(context["fenerg"]),
            "net_signal": net_signal,
            "absolute_signal": abs(net_signal),
            "dose": float(result),
        }
        return result

    @staticmethod
    def _numero_auditoria(value):
        return f"{float(value):.15g}"

    def _registrar_auditoria_dose(self):
        details = self.last_dose_details
        if not details:
            return
        text = (
            f"modo={details['mode']}; soma={self._numero_auditoria(details['sum'])}; "
            f"fLed={'—' if details['fled'] is None else self._numero_auditoria(details['fled'])}; "
            f"linha_de_base={self._numero_auditoria(details['baseline'])}; "
            f"RCF={self._numero_auditoria(details['rcf'])}; "
            f"ECC={self._numero_auditoria(details['ecc'])}; "
            f"Fang={self._numero_auditoria(details['fang'])}; "
            f"Fenerg={self._numero_auditoria(details['fenerg'])}; "
            f"sinal_liquido={self._numero_auditoria(details['net_signal'])}; "
            f"modulo={self._numero_auditoria(details['absolute_signal'])}; "
            f"dose={self._numero_auditoria(details['dose'])} mSv"
        )
        self._registrar_log_serial("CALCULO", text)
        self.salvar_log(f"\nAuditoria dose: {text}\n")

    def _calcular_dose_exibida_bl_automatico(self):
        """Convert BL counts to display-only dose in automatic BL mode."""
        context = self.applied_parameters or {}
        dosimeter = self.validated_dosimeter
        reader = self.validated_reader
        if not dosimeter or not reader:
            return float(self.soma)
        channel = context.get("dose_channel", self.dose_channel)
        ecc = float(
            dosimeter["ecc_hp007"]
            if channel == "HP007"
            else dosimeter["ecc_hp10"]
        )
        return calculate_dose(
            self.soma,
            baseline=0.0,
            rcf=float(reader["rcf"]),
            ecc=ecc,
            fang=float(context.get("fang", 1)),
            fenerg=float(context.get("fenerg", 1)),
        )

    def _finalizar_medicao(self, status, result, notes=None):
        if self.current_measurement_id is None:
            return False
        baseline_reading = bool(
            self.applied_parameters
            and self.applied_parameters.get("reading_type") == "BACKGROUND"
        )
        high_dose = bool(
            self.applied_parameters
            and self.applied_parameters.get("high_dose")
        )
        valid_result = result
        if high_dose and status != "CONCLUIDO":
            valid_result = 0.0
        persisted_notes = notes
        if high_dose:
            high_dose_note = (
                "Alta dose; fLed="
                f"{self._numero_auditoria(self.applied_parameters.get('fled', 1.0))}"
            )
            persisted_notes = (
                f"{notes}; {high_dose_note}" if notes else high_dose_note
            )
        self.obter_database().update_measurement(
            self.current_measurement_id,
            count_01s=self.valor_count,
            current_ma=self.valor_current,
            light_mv=self.valor_light,
            raw_signal=self.soma,
            dose_msv=0.0 if baseline_reading else valid_result,
            file_path=str(self.caminho_arquivo),
            status=status,
            notes=persisted_notes,
        )
        if status == "CONCLUIDO":
            if self.baseline_mode_active and baseline_reading:
                if self.applied_parameters.get("dose_channel") == "HP007":
                    self.bl_hp007_count += 1
                else:
                    self.bl_hp10_count += 1
                self._atualizar_meta_bl()
                return False
            history = self.obter_database().sync_measurement_history(
                self.current_measurement_id
            )
            self._mostrar_alerta_releitura(history)
            self._mostrar_confirmacao_baseline(history)
            if history is not None and (
                self.applied_parameters
                and self.applied_parameters.get("reading_type") == "BACKGROUND"
            ):
                self.reading_type = "PERSONAL_DOSE"
            return history is not None
        return False

    @staticmethod
    def _formatar_doses_historico(history):
        doses = []
        for column, label in (
            ("hp10_dos", "Hp(10)"),
            ("hp007_dos", "Hp(0,07)"),
        ):
            value = history.get(column)
            if value is not None:
                doses.append(f"{label}: {float(value):.10g} mSv")
        return "\n".join(doses)

    def _mostrar_alerta_releitura(self, history):
        """Warn the operator when the consolidated dose requires a new reading."""
        if not history or history.get("status_dos") != NEED_RE_READ_STATUS:
            return None

        dose = float(history["dose_dos"])
        channel_doses = self._formatar_doses_historico(history)
        if self.re_read_popup is not None:
            self.re_read_popup.dismiss()

        content = BoxLayout(
            orientation="vertical",
            spacing="12dp",
            padding="16dp",
        )
        content.add_widget(
            Label(
                text=(
                    f"Dose consolidada: {dose:.10g} mSv\n"
                    f"{channel_doses}\n\n"
                    "A dose é maior ou igual a 2 mSv.\n"
                    "Refaça a leitura.\n\n"
                    f'Tag gravada no banco: "{NEED_RE_READ_STATUS}"'
                ),
                halign="center",
                valign="middle",
            )
        )
        close_button = Button(
            text="OK",
            size_hint_y=None,
            height="42dp",
        )
        content.add_widget(close_button)
        popup = Popup(
            title="Refazer leitura",
            content=content,
            size_hint=(0.72, 0.42),
            auto_dismiss=False,
        )
        self.re_read_popup = popup
        close_button.bind(on_release=popup.dismiss)
        popup.bind(on_dismiss=lambda *_args: setattr(self, "re_read_popup", None))
        popup.open()
        return popup

    def _mostrar_confirmacao_baseline(self, history):
        """Ask whether a sub-background personal dose should become BL counts."""
        if not history or history.get("status_dos") != PERSONAL_DOSE_STATUS:
            return None

        dose = float(history["dose_dos"])
        channel_doses = self._formatar_doses_historico(history)
        if self.baseline_save_popup is not None:
            self.baseline_save_popup.dismiss()

        content = BoxLayout(
            orientation="vertical",
            spacing="12dp",
            padding="16dp",
        )
        content.add_widget(
            Label(
                text=(
                    f"Dose consolidada: {dose:.10g} mSv\n"
                    f"{channel_doses}\n\n"
                    "A dose é menor que 0,01 mSv.\n"
                    "Deseja salvar esta leitura como baseline "
                    "usando as contagens?"
                ),
                halign="center",
                valign="middle",
            )
        )
        actions = BoxLayout(size_hint_y=None, height="42dp", spacing="8dp")
        no_button = Button(text="Não")
        yes_button = Button(text="Sim, salvar contagens")
        actions.add_widget(no_button)
        actions.add_widget(yes_button)
        content.add_widget(actions)
        popup = Popup(
            title="Salvar como baseline?",
            content=content,
            size_hint=(0.78, 0.46),
            auto_dismiss=False,
        )
        self.baseline_save_popup = popup
        no_button.bind(on_release=popup.dismiss)
        yes_button.bind(
            on_release=lambda *_args: self._salvar_dose_como_baseline(
                popup,
                history,
            )
        )
        popup.bind(
            on_dismiss=lambda *_args: setattr(
                self,
                "baseline_save_popup",
                None,
            )
        )
        popup.open()
        return popup

    def _salvar_dose_como_baseline(self, popup, history):
        try:
            baseline = self.obter_database().save_personal_dose_as_baseline(
                int(history["id"]),
            )
        except (sqlite3.Error, TypeError, ValueError) as error:
            self.atualizar_status(f"Erro ao salvar baseline: {error}")
            return False

        if popup is not None:
            popup.dismiss()
        self.atualizar_status(
            "Leitura salva como baseline em contagens: "
            f"Hp(10)={float(baseline['hp10_counts']):.10g}, "
            f"Hp(0,07)={float(baseline['hp007_counts']):.10g}"
        )
        return True

    def _preparar_proxima_grandeza(self, completed_channel, *, status):
        if self.test_mode != "DOSIMETER_ID" or not self.test_session_active:
            return
        if self.baseline_mode_active:
            self._atualizar_meta_bl()
            if status == "CONCLUIDO":
                self.dosimeter_status = (
                    f"MODO BL ATIVO • {self._nome_grandeza(completed_channel)} "
                    f"{self._contagem_bl_atual()}/{self._meta_bl_atual()} • "
                    "repita, escolha outra grandeza ou finalize"
                )
            else:
                self.dosimeter_status = (
                    f"Leitura BL de {self._nome_grandeza(self.dose_channel)} "
                    "não concluída • pressione Start para repetir"
                )
            self.start_allowed = True
            self._atualizar_parametros_grandeza()
            return
        if status == "CONCLUIDO" and completed_channel == "HP10":
            self.hp10_complete = True
        elif status == "CONCLUIDO" and completed_channel == "HP007":
            self.hp007_complete = True

        if status != "CONCLUIDO":
            self.dosimeter_status = (
                f"{self._nome_grandeza(self.dose_channel)} não foi concluído • "
                "pressione Start para repetir"
            )
            self.start_allowed = True
            self._atualizar_parametros_grandeza()
            return

        missing_channel = "HP007" if not self.hp007_complete else "HP10"
        self.dose_channel = missing_channel
        self._atualizar_parametros_grandeza()
        self.dosimeter_status = (
            f"{self._nome_grandeza(completed_channel)} concluído • "
            f"faça a leitura de {self._nome_grandeza(missing_channel)}"
        )
        self.start_allowed = True

    def abrir_selecao_bl(self):
        if not self.baseline_mode_active:
            return False
        if self.acquisition_active or self.log_arquivo:
            self.atualizar_status(
                "Finalize ou interrompa a leitura atual antes de encerrar o modo BL."
            )
            return False
        records = []
        if self.active_test_session_id:
            try:
                records = self.obter_database().get_baseline_session_measurements(
                    self.active_test_session_id
                )
            except (sqlite3.Error, TypeError, ValueError) as error:
                self.atualizar_status(f"Erro ao carregar leituras BL: {error}")
                return False

        self.bl_selected_measurements = {"HP10": None, "HP007": None}
        self.bl_selected_values = {"HP10": None, "HP007": None}
        content = BoxLayout(orientation="vertical", spacing=8, padding=10)
        content.add_widget(
            Label(
                text=(
                    "Escolha uma leitura por grandeza ou a média das 3 menores. "
                    "Somente as escolhidas atualizarão o dosímetro."
                    if records
                    else "Nenhuma leitura BL concluída nesta sessão."
                ),
                size_hint_y=None,
                height="48dp",
                halign="left",
                valign="middle",
                text_size=(760, None),
            )
        )

        scroll = ScrollView()
        rows = BoxLayout(
            orientation="vertical",
            spacing=5,
            size_hint_y=None,
        )
        rows.bind(minimum_height=rows.setter("height"))
        grouped_records = {"HP10": [], "HP007": []}
        for record in records:
            grouped_records[record["dose_channel"]].append(record)

        for channel in ("HP10", "HP007"):
            channel_records = grouped_records[channel]
            if len(channel_records) < 3:
                continue
            lowest = sorted(
                channel_records,
                key=lambda item: float(item["raw_signal"]),
            )[:3]
            average = sum(
                float(item["raw_signal"]) for item in lowest
            ) / 3
            average_button = ToggleButton(
                text=(
                    f"{self._nome_grandeza(channel)} • "
                    f"Salvar média das 3 menores: {average:.10g} contagens"
                ),
                group=f"bl-{self.active_test_session_id}-{channel}",
                allow_no_selection=True,
                size_hint_y=None,
                height="46dp",
                halign="left",
                valign="middle",
            )
            average_button.bind(
                state=lambda _button, state, selected_channel=channel,
                selected_average=average: self._selecionar_media_bl(
                    selected_channel,
                    selected_average,
                    state,
                )
            )
            rows.add_widget(average_button)

        sequence = {"HP10": 0, "HP007": 0}
        for record in records:
            channel = record["dose_channel"]
            sequence[channel] += 1
            button = ToggleButton(
                text=(
                    f"{self._nome_grandeza(channel)} • leitura {sequence[channel]}"
                    f" • {float(record['raw_signal']):.10g} contagens"
                    f" • {record['measured_at']} • {record['file_name']}"
                ),
                group=f"bl-{self.active_test_session_id}-{channel}",
                allow_no_selection=True,
                size_hint_y=None,
                height="46dp",
                halign="left",
                valign="middle",
            )
            button.bind(
                state=lambda _button, state, selected_channel=channel,
                measurement_id=record["id"]: self._selecionar_leitura_bl(
                    selected_channel,
                    measurement_id,
                    state,
                )
            )
            rows.add_widget(button)
        scroll.add_widget(rows)
        content.add_widget(scroll)

        self._bl_selection_summary = Label(
            text="Hp(10): não alterar   •   Hp(0,07): não alterar",
            size_hint_y=None,
            height="34dp",
        )
        content.add_widget(self._bl_selection_summary)

        actions = BoxLayout(size_hint_y=None, height="44dp", spacing=8)
        continue_button = Button(text="Continuar leituras")
        discard_button = Button(text="Encerrar sem atualizar")
        apply_button = Button(
            text="Aplicar leituras selecionadas",
            disabled=True,
        )
        actions.add_widget(continue_button)
        actions.add_widget(discard_button)
        actions.add_widget(apply_button)
        content.add_widget(actions)

        popup = Popup(
            title="Finalizar modo BL",
            content=content,
            size_hint=(0.92, 0.86),
            auto_dismiss=False,
        )
        self.bl_selection_popup = popup
        self._bl_apply_button = apply_button
        continue_button.bind(on_release=popup.dismiss)
        discard_button.bind(on_release=self.encerrar_modo_bl_sem_atualizar)
        apply_button.bind(on_release=lambda _button: self.aplicar_selecao_bl())
        popup.open()
        return True

    def aplicar_ultimas_leituras_bl(self):
        """Apply the latest completed count for each channel in the BL session."""
        if not self.baseline_mode_active:
            return None
        if self.acquisition_active or self.log_arquivo:
            self.atualizar_status(
                "Finalize ou interrompa a leitura atual antes de encerrar o modo BL."
            )
            return None
        if not self.active_test_session_id:
            self.atualizar_status(
                "Nenhuma sessão BL com leituras concluídas para atualizar."
            )
            return None
        try:
            records = self.obter_database().get_baseline_session_measurements(
                self.active_test_session_id
            )
        except (sqlite3.Error, TypeError, ValueError) as error:
            self.atualizar_status(f"Erro ao carregar leituras BL: {error}")
            return None

        latest_ids = {"HP10": None, "HP007": None}
        for record in records:
            latest_ids[record["dose_channel"]] = int(record["id"])
        if all(measurement_id is None for measurement_id in latest_ids.values()):
            self.atualizar_status(
                "Nenhuma leitura BL concluída; o modo BL permanece ativo."
            )
            return None
        return self.aplicar_selecao_bl(
            hp10_measurement_id=latest_ids["HP10"],
            hp007_measurement_id=latest_ids["HP007"],
        )

    def _selecionar_leitura_bl(self, channel, measurement_id, state):
        if state == "down":
            self.bl_selected_measurements[channel] = int(measurement_id)
            self.bl_selected_values[channel] = None
        elif self.bl_selected_measurements.get(channel) == int(measurement_id):
            self.bl_selected_measurements[channel] = None
        self._atualizar_selecao_bl()

    def _selecionar_media_bl(self, channel, average, state):
        if state == "down":
            self.bl_selected_measurements[channel] = None
            self.bl_selected_values[channel] = float(average)
        elif self.bl_selected_values.get(channel) == float(average):
            self.bl_selected_values[channel] = None
        self._atualizar_selecao_bl()

    def _atualizar_selecao_bl(self):
        try:
            descriptions = []
            for channel, label in (("HP10", "Hp(10)"), ("HP007", "Hp(0,07)")):
                value = self.bl_selected_values.get(channel)
                measurement_id = self.bl_selected_measurements.get(channel)
                if value is not None:
                    description = f"média = {float(value):.10g}"
                elif measurement_id is not None:
                    description = f"leitura ID {measurement_id}"
                else:
                    description = "não alterar"
                descriptions.append(f"{label}: {description}")
            self._bl_apply_button.disabled = not any(
                value is not None
                for value in (
                    self.bl_selected_values["HP10"],
                    self.bl_selected_values["HP007"],
                    self.bl_selected_measurements["HP10"],
                    self.bl_selected_measurements["HP007"],
                )
            )
            self._bl_selection_summary.text = "   •   ".join(descriptions)
        except AttributeError:
            pass

    def aplicar_selecao_bl(
        self,
        hp10_measurement_id=None,
        hp007_measurement_id=None,
    ):
        if not self.baseline_mode_active or not self.active_test_session_id:
            self.atualizar_status("Não existe uma sessão BL ativa para aplicar.")
            return None
        hp10_id = (
            self.bl_selected_measurements.get("HP10")
            if hp10_measurement_id is None
            else hp10_measurement_id
        )
        hp007_id = (
            self.bl_selected_measurements.get("HP007")
            if hp007_measurement_id is None
            else hp007_measurement_id
        )
        hp10_value = (
            self.bl_selected_values.get("HP10") if hp10_id is None else None
        )
        hp007_value = (
            self.bl_selected_values.get("HP007") if hp007_id is None else None
        )
        if (
            hp10_id is None
            and hp007_id is None
            and hp10_value is None
            and hp007_value is None
        ):
            self.atualizar_status("Selecione ao menos uma leitura para aplicar.")
            return None
        try:
            result = self.obter_database().apply_baseline_selection(
                self.active_test_session_id,
                self.active_test_dosimeter_id,
                hp10_measurement_id=hp10_id,
                hp007_measurement_id=hp007_id,
                hp10_counts=hp10_value,
                hp007_counts=hp007_value,
            )
        except (sqlite3.Error, TypeError, ValueError) as error:
            self.atualizar_status(f"Erro ao aplicar BL: {error}")
            return None
        selected_values = []
        if result.get("hp10_counts") is not None:
            selected_values.append(
                f"Hp(10)={float(result['hp10_counts']):.10g}"
            )
        if result.get("hp007_counts") is not None:
            selected_values.append(
                f"Hp(0,07)={float(result['hp007_counts']):.10g}"
            )
        self._encerrar_modo_bl(
            "BL atualizado no dosímetro: " + ", ".join(selected_values)
        )
        return result

    def encerrar_modo_bl_sem_atualizar(self, _button=None):
        if not self.baseline_mode_active:
            return False
        self._encerrar_modo_bl(
            "Modo BL encerrado sem alterar o cadastro do dosímetro."
        )
        return True

    def _encerrar_modo_bl(self, message):
        try:
            if self.bl_selection_popup:
                self.bl_selection_popup.dismiss()
        except AttributeError:
            pass
        self.bl_selection_popup = None
        self._bl_apply_button = None
        self.baseline_mode_active = False
        self.reading_type = "PERSONAL_DOSE"
        self.test_session_active = False
        self.active_test_session_id = None
        self.active_test_dosimeter_id = None
        self.active_test_reading_type = None
        self.hp10_complete = False
        self.hp007_complete = False
        self.dose_channel = "HP10"
        self._resetar_estado_bl()
        try:
            self.ids.dosimeter_id_input.text = ""
            self.ids.LabelDose.text = "Dose (mSv)"
        except KeyError:
            pass
        self._invalidar_dosimetro(message)
        self.atualizar_status(message)
        self.agendar_foco_dosimetro(selecionar=False)

    def _atualizar_medicao_com_erro(self, notes):
        if self.current_measurement_id is None:
            return
        try:
            self.obter_database().update_measurement(
                self.current_measurement_id,
                file_path=(
                    str(self.caminho_arquivo)
                    if self.caminho_arquivo is not None
                    else None
                ),
                status="ERRO",
                notes=notes,
            )
        except (sqlite3.Error, TypeError, ValueError):
            traceback.print_exc()

    @staticmethod
    def formatar_dose(valor):
        """Show real zero as 0 and every non-zero dose with three decimals."""
        valor = float(valor)
        return "0" if valor == 0 else f"{valor:.3f}"

    def mostrar_detalhes_dose(self):
        details = self.last_dose_details
        content = BoxLayout(orientation="vertical", spacing=8, padding=12)
        if not details:
            content.add_widget(
                Label(text="Os detalhes ainda não estão disponíveis.")
            )
        else:
            rows = (
                ("Modo", details["mode"]),
                ("Fórmula", details["formula"]),
                ("Soma", self._numero_auditoria(details["sum"])),
                (
                    "fLed",
                    "—" if details["fled"] is None else self._numero_auditoria(details["fled"]),
                ),
                ("Linha de base", self._numero_auditoria(details["baseline"])),
                ("RCF", self._numero_auditoria(details["rcf"])),
                ("ECC", self._numero_auditoria(details["ecc"])),
                ("Fang", self._numero_auditoria(details["fang"])),
                ("Fenerg", self._numero_auditoria(details["fenerg"])),
                ("Dose calculada", f"{self._numero_auditoria(details['dose'])} mSv"),
            )
            grid = GridLayout(cols=2, spacing=6)
            for name, value in rows:
                grid.add_widget(Label(text=str(name), halign="right"))
                grid.add_widget(Label(text=str(value), halign="left"))
            content.add_widget(grid)
        close_button = Button(text="Fechar", size_hint_y=None, height=42)
        content.add_widget(close_button)
        popup = Popup(
            title="Detalhes do cálculo da dose",
            content=content,
            size_hint=(0.78, 0.82),
            auto_dismiss=False,
        )
        close_button.bind(on_release=popup.dismiss)
        popup.open()
        return popup

    def _definir_estado_alta_dose(self, new_state):
        old_state = self.high_dose_state
        self.high_dose_state = new_state
        self._registrar_log_serial(
            "ESTADO",
            f"alta dose: {old_state} -> {new_state}",
        )

    def _resetar_estado_alta_dose(self):
        popup = self.high_dose_popup
        self.high_dose_popup = None
        if popup is not None:
            popup.dismiss()
        self.high_dose_restart_button = None
        self.high_dose_restart_locked = False
        self.high_dose_state = ESTADO_LEITURA_NORMAL

    def _abrir_popup_alta_dose(self):
        content = BoxLayout(orientation="vertical", spacing=10, padding=14)
        content.add_widget(
            Label(
                text=(
                    "A leitura está indicando alta dose.\n"
                    "Ajuste manualmente o filtro antes de continuar.\n\n"
                    "Após ajustar o filtro, pressione OK para reiniciar a leitura."
                ),
                halign="center",
            )
        )
        button = Button(text="OK", size_hint_y=None, height=46)
        content.add_widget(button)
        popup = PopupAltaDose(
            title="Alta dose detectada",
            content=content,
            size_hint=(0.72, 0.48),
            auto_dismiss=False,
        )
        self.high_dose_popup = popup
        self.high_dose_restart_button = button
        button.bind(on_release=self._confirmar_filtro_alta_dose)
        popup.open()
        return popup

    def _tratar_saturacao_alta_dose(self):
        self._registrar_log_serial("EVENTO", FRAME_ALTA_DOSE)
        if self.high_dose_state in ESTADOS_ALTA_DOSE_PENDENTE:
            self._registrar_log_serial(
                "EVENTO",
                "Saturação duplicada ignorada enquanto há uma pendência",
            )
            return
        if self.high_dose_state == ESTADO_LEITURA_ALTA_DOSE:
            self.acquisition_active = False
            self.fechar_log(
                status="ERRO",
                notes="Saturação persistente após reinício em alta dose",
            )
            return
        if not self.log_arquivo or not self.acquisition_active:
            self._registrar_log_serial(
                "EVENTO",
                "Saturação ignorada sem leitura ativa",
            )
            return

        self._cancelar_watchdogs_serial()
        self.acquisition_active = False
        self._definir_estado_alta_dose(ESTADO_ALTA_DOSE_ENVIANDO_CONFIG)
        try:
            fled = self.obter_fled("1")
            self.applied_parameters["high_dose"] = True
            self.applied_parameters["fled"] = fled
        except (AttributeError, TypeError, ValueError) as error:
            self.fechar_log(status="ERRO", notes=f"Falha ao preparar alta dose: {error}")
            return

        if not self.enviar_serial(COMANDO_CONFIG_ALTA_DOSE, finalizar_em_erro=False):
            self.fechar_log(
                status="ERRO",
                notes="ERRO TX ao enviar configuração P1 de alta dose",
            )
            return
        self._definir_estado_alta_dose(ESTADO_ALTA_DOSE_AGUARDANDO_FILTRO)
        self._abrir_popup_alta_dose()

    def _reinicializar_tentativa_alta_dose(self):
        self.soma = 0
        self.soma_luz = 0
        self.contador = 0.1
        self.valor_count = 0
        self.valor_current = 0
        self.valor_light = 0
        self.nova_linha = True
        self.f_fechar_log = False
        self.serial_sample_received = False
        for widget_id in ("label_dose", "label_current", "label_light", "label_count"):
            self.ids[widget_id].text = "0"
        self.ids.grafico_tempo_real.limpar()
        if self.log_arquivo:
            self.log_arquivo.flush()
            self.log_arquivo.seek(0)
            header = self.log_arquivo.readlines()[:5]
            while len(header) < 5:
                header.append("\n")
            header[2] = "Soma: 0\n"
            header[3] = "Dose mSv: 0\n"
            self.log_arquivo.seek(0)
            self.log_arquivo.writelines(header)
            self.log_arquivo.truncate()
            self.log_arquivo.flush()
            self.string_log = "".join(header)

    def _confirmar_filtro_alta_dose(self, _button=None):
        if (
            self.high_dose_state != ESTADO_ALTA_DOSE_AGUARDANDO_FILTRO
            or self.high_dose_restart_locked
        ):
            return False
        self.high_dose_restart_locked = True
        if self.high_dose_restart_button is not None:
            self.high_dose_restart_button.disabled = True
        if self.high_dose_popup is not None:
            self.high_dose_popup.dismiss()
            self.high_dose_popup = None
        self._reinicializar_tentativa_alta_dose()
        self._definir_estado_alta_dose(ESTADO_ALTA_DOSE_REINICIANDO)
        self.acquisition_active = True
        if not self.enviar_serial(COMANDOS_SUDO["leitura"], finalizar_em_erro=False):
            self.acquisition_active = False
            self.fechar_log(
                status="ERRO",
                notes="ERRO TX ao reiniciar leitura de alta dose",
            )
            return False
        self._armar_watchdog_primeiro_frame()
        self.atualizar_status(
            "Filtro confirmado; aguardando o primeiro frame da leitura de alta dose."
        )
        return True

    # Serial
    def _iniciar_log_serial(self, porta):
        self._fechar_log_serial()
        LOG_SERIAL_DIR.mkdir(parents=True, exist_ok=True)
        agora = datetime.now()
        nome = agora.strftime("serial_%Y%m%d_%H%M%S_%f.txt")
        self.caminho_log_serial = LOG_SERIAL_DIR / nome
        self.log_serial_arquivo = open(
            self.caminho_log_serial,
            "x",
            encoding="utf-8",
            buffering=1,
        )
        self._registrar_log_serial(
            "SISTEMA",
            f"Conectado em {porta} @ {BAUD_RATE}",
        )

    def _registrar_log_serial(self, direcao, dados):
        if not self.log_serial_arquivo:
            return

        # Mantém cada evento em uma linha sem perder CR/LF recebidos.
        if isinstance(dados, (bytes, bytearray, memoryview)):
            texto = bytes(dados).decode("ascii", errors="backslashreplace")
        else:
            texto = str(dados)
        texto = texto.replace("\r", "\\r").replace("\n", "\\n")
        horario = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with self.serial_log_lock:
            try:
                self.log_serial_arquivo.write(
                    f"[{horario}] [{direcao}] {texto}\n"
                )
                self.log_serial_arquivo.flush()
            except OSError:
                traceback.print_exc()

    def _fechar_log_serial(self):
        if not self.log_serial_arquivo:
            return

        self._registrar_log_serial("SISTEMA", "Comunicação encerrada")
        try:
            self.log_serial_arquivo.close()
        except OSError:
            traceback.print_exc()
        finally:
            self.log_serial_arquivo = None

    def atualizar_portas_serial(self, *args):
        portas_detectadas = [
            porta.device for porta in serial.tools.list_ports.comports()
        ]
        portas = list(dict.fromkeys(portas_detectadas + PORTAS_SERIAL))
        if PORTA_SERIAL_PREFERIDA in portas:
            portas.remove(PORTA_SERIAL_PREFERIDA)
            portas.insert(0, PORTA_SERIAL_PREFERIDA)

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
        if porta in ("", "Porta", "COM Port"):
            self.atualizar_status("Selecione uma porta serial.")
            return

        try:
            self.desconectar_serial(atualizar_botao=False)
            self.serial_connection = serial.Serial(
                port=porta,
                baudrate=BAUD_RATE,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=SERIAL_READ_TIMEOUT,
                write_timeout=1.0,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )
            self.serial_decoder.reset()
            self._limpar_fila_serial()
            self._respondeu_solicitacao_parametros = False
            self._iniciar_log_serial(porta)
            self._iniciar_leitor_serial()
            self.leitura_evento = Clock.schedule_interval(
                self.ler_serial,
                SERIAL_UI_POLL_SECONDS,
            )
            Clock.schedule_once(
                lambda dt: self.enviar_serial(COMANDO_INICIAL), 0.2
            )

            self.ids.botao_conexao_serial.text = "Disconnect"
            self.atualizar_status(f"Conectado em {porta} @ {BAUD_RATE}")

        except (OSError, serial.SerialException) as erro:
            self.desconectar_serial(atualizar_botao=False)
            self.atualizar_status(f"Erro ao conectar: {erro}")

    def _limpar_fila_serial(self):
        while True:
            try:
                self.serial_frame_queue.get_nowait()
            except Empty:
                return

    def _iniciar_leitor_serial(self):
        self.serial_stop_event.clear()
        self.serial_reader_thread = Thread(
            target=self._loop_leitor_serial,
            name="OSLMeter-SerialReader",
            daemon=True,
        )
        self.serial_reader_thread.start()

    def _parar_leitor_serial(self):
        self.serial_stop_event.set()
        connection = self.serial_connection
        if connection is not None:
            cancel_read = getattr(connection, "cancel_read", None)
            if callable(cancel_read):
                try:
                    cancel_read()
                except (OSError, serial.SerialException):
                    pass
            try:
                if connection.is_open:
                    connection.close()
            except (OSError, serial.SerialException):
                pass

        reader = self.serial_reader_thread
        if reader and reader.is_alive() and reader is not current_thread():
            reader.join(timeout=0.5)
        self.serial_reader_thread = None

    def _loop_leitor_serial(self):
        """Drena a USB/COM continuamente, sem depender do ciclo da UI."""

        while not self.serial_stop_event.is_set():
            connection = self.serial_connection
            if connection is None or not connection.is_open:
                break
            try:
                # read() com tamanho fixo evita a janela entre consultar
                # in_waiting e ler: nesse intervalo mais bytes podem chegar.
                dados = connection.read(SERIAL_READ_CHUNK_SIZE)
                if not dados:
                    continue
                self.serial_bytes_received += len(dados)
                self._registrar_log_serial("RX", dados)
                for frame in self.serial_decoder.feed(dados):
                    self.serial_frame_queue.put(("FRAME", frame))
            except (OSError, serial.SerialException) as erro:
                if not self.serial_stop_event.is_set():
                    self.serial_frame_queue.put(("ERROR", str(erro)))
                break

    def _processar_fila_serial(self, _dt=None):
        processados = 0
        while processados < SERIAL_MAX_FRAMES_PER_UI_TICK:
            try:
                tipo, payload = self.serial_frame_queue.get_nowait()
            except Empty:
                break
            processados += 1

            if tipo == "ERROR":
                self.serial_last_error = payload
                self._registrar_log_serial("ERRO RX", payload)
                self.atualizar_status(f"Erro na leitura serial: {payload}")
                if self.log_arquivo:
                    self.fechar_log(status="ERRO", notes=str(payload))
                elif self.ref_light_reading_active:
                    self._finalizar_ref_light_leitura(
                        status="ERRO",
                        notes=str(payload),
                    )
                continue

            frame_bytes = payload
            try:
                frame = frame_bytes.decode("ascii")
            except UnicodeDecodeError as erro:
                self.serial_invalid_frames += 1
                self._registrar_log_serial(
                    "ERRO FRAME",
                    f"ASCII inválido: {frame_bytes!r} ({erro})",
                )
                continue

            self.serial_frames_received += 1
            try:
                # O decoder só libera frames depois de encontrar '&'. Recoloca
                # o terminador para que gatilhos críticos validem o pacote inteiro.
                self.processar_frame(f"{frame}&")
            except (TypeError, ValueError, IndexError) as erro:
                self.serial_invalid_frames += 1
                self._registrar_log_serial(
                    "ERRO FRAME",
                    f"{frame!r}: {erro}",
                )
                self.atualizar_status(f"Frame serial inválido: {frame}")

    def _cancelar_watchdogs_serial(self):
        for atributo in ("serial_first_frame_event", "serial_silence_event"):
            evento = getattr(self, atributo, None)
            if evento:
                evento.cancel()
                setattr(self, atributo, None)

    def _armar_watchdog_primeiro_frame(self):
        self._cancelar_watchdogs_serial()
        self.serial_sample_received = False
        self.serial_first_frame_event = Clock.schedule_once(
            self._timeout_primeiro_frame,
            SERIAL_FIRST_FRAME_TIMEOUT,
        )

    def _marcar_dado_serial_recebido(self):
        if not self.acquisition_active or (
            not self.log_arquivo and not self.ref_light_reading_active
        ):
            return
        self.serial_sample_received = True
        if self.serial_first_frame_event:
            self.serial_first_frame_event.cancel()
            self.serial_first_frame_event = None
        if self.serial_silence_event:
            self.serial_silence_event.cancel()
        self.serial_silence_event = Clock.schedule_once(
            self._timeout_silencio_serial,
            SERIAL_SILENCE_TIMEOUT,
        )

    def _timeout_primeiro_frame(self, _dt):
        self.serial_first_frame_event = None
        if not self.acquisition_active or (
            not self.log_arquivo and not self.ref_light_reading_active
        ):
            return
        if not self.serial_sample_received:
            self._encerrar_por_timeout_serial(
                f"Nenhum frame recebido da leitora em "
                f"{SERIAL_FIRST_FRAME_TIMEOUT:.1f} s após Start"
            )

    def _timeout_silencio_serial(self, _dt):
        self.serial_silence_event = None
        if not self.acquisition_active or (
            not self.log_arquivo and not self.ref_light_reading_active
        ):
            return
        self._encerrar_por_timeout_serial(
            f"Comunicação serial sem dados por "
            f"{SERIAL_SILENCE_TIMEOUT:.1f} s durante a leitura"
        )

    def _encerrar_por_timeout_serial(self, motivo):
        if not self.log_arquivo and not self.ref_light_reading_active:
            return
        self._registrar_log_serial("TIMEOUT", motivo)
        self.atualizar_status(motivo)
        if self.serial_aberta():
            self.enviar_comando_sudo("stop")
        if self.ref_light_reading_active:
            self._finalizar_ref_light_leitura(status="ERRO", notes=motivo)
        else:
            self.fechar_log(status="ERRO", notes=motivo)

    def desconectar_serial(self, atualizar_botao=True):
        self._parar_leitor_serial()
        # Processa o que já foi recebido antes de marcar a aquisição como
        # interrompida; fechar a COM não deve descartar frames que chegaram.
        self._processar_fila_serial()
        if self.log_arquivo:
            self.fechar_log(
                status="INTERROMPIDO",
                notes="Conexão serial encerrada durante a leitura",
            )
        elif self.ref_light_reading_active:
            self._finalizar_ref_light_leitura(
                status="INTERROMPIDO",
                notes="Conexão serial encerrada durante a leitura",
            )
        if self.leitura_evento:
            self.leitura_evento.cancel()
            self.leitura_evento = None

        if self.serial_aberta():
            self.serial_connection.close()

        self.serial_connection = None
        self.serial_decoder.reset()
        self._limpar_fila_serial()
        self._fechar_log_serial()

        if atualizar_botao:
            self.ids.botao_conexao_serial.text = "Connect"
            self.atualizar_status("Serial desconectada.")

    def serial_aberta(self):
        return self.serial_connection and self.serial_connection.is_open

    def enviar_serial(self, comando, *, finalizar_em_erro=True):
        if not self.serial_aberta():
            self.atualizar_status("Serial desconectada. Verifique a porta.")
            lbl_erro.text = "Connect to OSL System!"
            popupNomeArquivo.open()
            return False

        try:
            payload = comando.encode("ascii")
            total_written = 0
            while total_written < len(payload):
                written = self.serial_connection.write(payload[total_written:])
                if written is None:
                    written = len(payload) - total_written
                if written <= 0:
                    raise serial.SerialTimeoutException(
                        "A porta serial não aceitou todos os bytes"
                    )
                total_written += written
            flush = getattr(self.serial_connection, "flush", None)
            if callable(flush):
                flush()
            self._registrar_log_serial("TX", comando)
            self.atualizar_status(f"Enviado: {comando}")
            return True
        except (OSError, serial.SerialException) as erro:
            self._registrar_log_serial("ERRO TX", erro)
            self.atualizar_status(f"Erro ao enviar: {erro}")
            if finalizar_em_erro and self.log_arquivo:
                self.fechar_log(status="ERRO", notes=str(erro))
            return False

    def ler_serial(self, dt):
        # A leitura física acontece em _loop_leitor_serial. Este callback só
        # toca a fila e os widgets no thread principal do Kivy.
        self._processar_fila_serial(dt)

    def processar_frame(self, frame):
        received_frame = str(frame).strip()
        if not received_frame:
            return
        complete_frame = received_frame if received_frame.endswith("&") else None
        frame = received_frame[:-1] if complete_frame else received_frame
        display_frame = complete_frame or f"{frame}&"
        self.ids.recebido_label.text = f"Recebido: {display_frame}"
        print(f"RECEBIDO: {display_frame}")

        if complete_frame and is_exact_complete_frame(complete_frame, FRAME_ALTA_DOSE):
            self._tratar_saturacao_alta_dose()
            return
        if frame.endswith("satLeit"):
            # Pacotes incompletos e indicadores V/E/F/L não são aliases.
            return

        data_frame = frame[:5] in ("#L1%A", "#L1%B", "#L1%E", "#L1%T", "#L1%D")
        if self.high_dose_state == ESTADO_ALTA_DOSE_AGUARDANDO_FILTRO:
            return
        if self.high_dose_state == ESTADO_ALTA_DOSE_REINICIANDO:
            if not data_frame:
                return
            self._definir_estado_alta_dose(ESTADO_LEITURA_ALTA_DOSE)
            self.high_dose_restart_locked = False
        # O frame D fecha a amostra (ultima coluna); os demais sao colunas
        # intermediarias. Cada linha comeca pelo Tempo (ver registrar_valor).
        if frame.startswith("#L1%D"):
            valor = int(frame[5:].strip())
            self.valor_light = valor
            self.ids.label_light.text = f"{valor}"
            self.soma_luz += valor
            self.registrar_valor(frame, fim_linha=True)
            self.atualizar_grafico_tempo_real()
            if self.f_luz_ref:
                print("luz_ref")
                self.ids.label_dose.text = self.formatar_dose(self.soma_luz)

        elif frame[:5] in ("#L1%A", "#L1%B", "#L1%E", "#L1%T"):
            if frame[:5] == "#L1%A":
                valor = int(frame[5:].strip())
                self.valor_count = valor
                self.ids.label_count.text = f"{valor}"
                self.soma += valor

            if frame[:5] == "#L1%E":
                valor = int(frame[5:].strip())
                self.valor_current = valor
                self.ids.label_current.text = f"{valor}"

            self.registrar_valor(frame, fim_linha=False)
        elif frame.startswith("#L1%I"):
            if self.ref_light_reading_active or (
                self.log_arquivo and self.acquisition_active
            ):
                if self.serial_sample_received:
                    notes = f"Fim sinalizado pela leitora: {frame}"
                    if self.ref_light_reading_active:
                        self._finalizar_ref_light_leitura(notes=notes)
                    else:
                        self.fechar_log(status="CONCLUIDO", notes=notes)
                else:
                    self._encerrar_por_timeout_serial(
                        f"A leitora encerrou sem enviar amostras: {frame}"
                    )
            # Alguns firmwares respondem ao pacote de parâmetros com
            # #L1%I0000000. Esse frame também pode ser o encerramento da
            # leitura; só responda com os parâmetros quando não há aquisição.
            elif (
                frame == "#L1%I0000000"
                and not self._respondeu_solicitacao_parametros
            ):
                self._respondeu_solicitacao_parametros = True
                self.enviar_serial(COMANDO_PARAMETROS_PADRAO)

    def atualizar_grafico_tempo_real(self):
        """Envia uma amostra completa ao gráfico ao fechar cada linha serial."""
        try:
            self.ids.grafico_tempo_real.adicionar_amostra(
                self.contador,
                self.valor_count,
                self.valor_current,
                self.valor_light,
            )
        except (AttributeError, KeyError):
            # O gráfico pode ainda não estar montado durante a inicialização.
            pass

    def registrar_valor(self, frame, fim_linha):
        valor = int(frame[5:].strip())
        self._marcar_dado_serial_recebido()

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
                    self.ids.label_dose.text = self.formatar_dose(self.soma_luz)
                    self.f_luz_ref = False
                    self.f_fechar_log = False
                    self._finalizar_ref_light_leitura()
                else:
                    self.ids.label_dose.text = self.formatar_dose(self.soma)
                    self.f_fechar_log = False
                    self.fechar_log()

        else:
            self.salvar_log(f"{valor};")

    # Comandos
    def botao_leitura(self):
        if self.log_arquivo or self.ref_light_reading_active:
            self.atualizar_status("Já existe uma leitura em andamento.")
            return
        if self.ref_light_mode_active:
            self._iniciar_ref_light_leitura()
            return
        self.string_log = ""
        self.ids.label_dose.text = "0.000"
        self.ids.label_current.text = "0"
        self.ids.label_light.text = "0"
        self.ids.label_count.text = "0"
        self.f_luz_ref = False
        try:
            context = self._preparar_contexto_teste()
        except (TypeError, ValueError) as error:
            self.atualizar_status(str(error))
            lbl_erro.text = str(error)
            popupNomeArquivo.open()
            if self.test_mode == "DOSIMETER_ID":
                self.agendar_foco_dosimetro()
            return
        if not self.serial_aberta():
            self.atualizar_status("Serial desconectada. Verifique a porta.")
            lbl_erro.text = "Connect to OSL System!"
            popupNomeArquivo.open()
        else:
            self.ids.LabelDose.text = (
                "Dose (mSv)"
                if (
                    context.get("reading_type") != "BACKGROUND"
                    or self.bl_update_mode == "AUTOMATICO"
                )
                else "Contagens"
            )
            self.func_botao_log(context)

    def botao_stop(self):
        self.enviar_comando_sudo("stop")
        if self.ref_light_reading_active:
            self._finalizar_ref_light_leitura(
                status="INTERROMPIDO",
                notes="Leitura interrompida pelo operador",
            )
        elif self.log_arquivo:
            self.fechar_log(
                status="INTERROMPIDO",
                notes="Leitura interrompida pelo operador",
            )

    def botao_ref_light(self):
        if self.log_arquivo or self.acquisition_active:
            self.atualizar_status(
                "Finalize ou interrompa a leitura atual antes de usar o Ref Light."
            )
            return False
        if self.baseline_mode_active or self.test_session_active:
            self.atualizar_status(
                "Finalize o modo BL ou o teste atual antes de usar o Ref Light."
            )
            return False
        if self.ref_light_mode_active:
            return self._finalizar_modo_ref_light()

        self._resetar_estado_ref_light()
        self.ref_light_mode_active = True
        self.ids.label_dose.text = "0.000"
        self.ids.label_current.text = "0"
        self.ids.label_light.text = "0"
        self.ids.label_count.text = "0"
        self.ids.LabelDose.text = "Integral Light"
        self._atualizar_status_ref_light()
        self.atualizar_status(
            "Modo Ref Light ativo. Defina as repetições e pressione Start."
        )
        return True

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

            if not self.salvar_fled_atual():
                lbl_erro.text = "Invalid fLed value!"
                popupNomeArquivo.open()
                return

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
            self._respondeu_solicitacao_parametros = False
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
        if valor.isdigit() and 1 <= len(valor) <= 6:
            return True

        self.atualizar_status(
            f"Campo {nome} deve ser numerico com ate 6 digitos."
        )
        return False


class CelulaTabelaDados(Label):
    """Célula alinhada com fundo próprio para históricos em formato de grade."""

    def __init__(self, *, background_color, **kwargs):
        kwargs.setdefault("halign", "left")
        kwargs.setdefault("valign", "middle")
        kwargs.setdefault("padding", (10, 0))
        super().__init__(**kwargs)
        with self.canvas.before:
            self._background_color = Color(*background_color)
            self._background_rectangle = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._atualizar_fundo, size=self._atualizar_fundo)
        self.bind(size=self._atualizar_area_texto)
        self._atualizar_area_texto()

    def _atualizar_fundo(self, *_args):
        self._background_rectangle.pos = self.pos
        self._background_rectangle.size = self.size

    def _atualizar_area_texto(self, *_args):
        self.text_size = self.size


class LinhaTabelaDados(BoxLayout):
    def __init__(self, *, record=None, selection_callback=None, **kwargs):
        super().__init__(**kwargs)
        self.record = record
        self.selection_callback = selection_callback

    #def on_touch_up(self, touch):
    #    handled = super().on_touch_up(touch)
    #    if handled:
    #        return True
    #    if (
    #        self.selection_callback is not None
    #        and self.collide_point(*touch.pos)
    #    ):
    #        self.selection_callback(self.record)
    #        return True
    #    return False


class TelaParametrosLeitura(Screen):
    pass


class TelaBancoDados(Screen):
    dosimeter_message = StringProperty("")
    dosimeter_count = StringProperty("0 registros")
    reader_message = StringProperty("")
    reader_count = StringProperty("0 registros")
    personal_dose_message = StringProperty("")
    personal_dose_count = StringProperty("0 registros")
    background_message = StringProperty("")
    background_count = StringProperty("0 registros")
    history_message = StringProperty("")
    history_count = StringProperty("0 registros")
    history_details = StringProperty(
        "Selecione uma medição para visualizar os parâmetros aplicados."
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.database = None
        self._editing_dosimeter_id = None
        self._editing_reader_id = None
        self._personal_dose_rows = []
        self._background_rows = []
        self._history_rows = []
        self._loaded_database_tabs = set()
        self._pending_database_tabs = set()
        self._export_popup_fields = None

    def on_kv_post(self, base_widget):
        focus_order = (
            "db_dosimeter_search",
            "db_dosimeter_id",
            "db_dosimeter_ecc_hp10",
            "db_dosimeter_ecc_hp007",
            "db_dosimeter_bl_hp10",
            "db_dosimeter_bl_hp007",
            "db_dosimeter_begin",
            "db_dosimeter_end",
        )
        for current_id, next_id in zip(
            focus_order,
            focus_order[1:] + focus_order[:1],
        ):
            self.ids[current_id].focus_next = self.ids[next_id]

    def obter_database(self):
        if self.database is not None:
            return self.database
        aplicativo = App.get_running_app()
        if aplicativo is None or not hasattr(aplicativo, "database"):
            raise RuntimeError("Banco de dados não inicializado")
        self.database = aplicativo.database
        return self.database

    def on_pre_enter(self, *_args):
        # Do not populate every table when the screen is opened.  Some of the
        # history tables can contain hundreds of rows, and creating one Kivy
        # widget per cell blocks the main event loop.
        self._loaded_database_tabs.clear()
        self._pending_database_tabs.clear()
        Clock.schedule_once(self._carregar_aba_atual, 0)

    def carregar_aba_database(self, tab):
        """Load a database tab only when it becomes visible."""
        if tab is None:
            return
        tab_by_id = {
            self.ids.tab_db_personal: "personal_dose",
            self.ids.tab_db_background: "background",
            self.ids.tab_db_dosimeters: "dosimeters",
            self.ids.tab_db_readers: "readers",
            self.ids.tab_db_history: "history",
        }
        tab_key = tab_by_id.get(tab)
        if tab_key is None:
            return
        if tab_key in self._loaded_database_tabs:
            return
        if tab_key in self._pending_database_tabs:
            return
        self._pending_database_tabs.add(tab_key)
        Clock.schedule_once(
            lambda _dt, key=tab_key: self._carregar_aba_database(key),
            0,
        )

    def _carregar_aba_atual(self, _dt):
        tab = self.ids.database_tabs.current_tab
        if tab is None:
            # With do_default_tab=False, Kivy may not expose a current tab
            # until the first user click.  Keep the first view useful.
            self.pesquisar_doses_pessoais()
            self._loaded_database_tabs.add("personal_dose")
            return
        self.carregar_aba_database(tab)

    def _carregar_aba_database(self, tab_key):
        self._pending_database_tabs.discard(tab_key)
        searches = {
            "personal_dose": self.pesquisar_doses_pessoais,
            "background": self.pesquisar_backgrounds,
            "dosimeters": self.pesquisar_dosimetros,
            "readers": self.pesquisar_leitoras,
            "history": self.pesquisar_historico,
        }
        search = searches.get(tab_key)
        if search is None:
            return
        search()
        self._loaded_database_tabs.add(tab_key)

    def _preparar_novo_dosimetro(self, dosimeter_id=""):
        self._editing_dosimeter_id = None
        today = datetime.now().strftime("%d/%m/%Y")
        defaults = {
            "db_dosimeter_id": str(dosimeter_id).strip(),
            "db_dosimeter_ecc_hp10": "1",
            "db_dosimeter_ecc_hp007": "1",
            "db_dosimeter_bl_hp10": "1",
            "db_dosimeter_bl_hp007": "1",
            "db_dosimeter_begin": today,
            "db_dosimeter_end": "",
        }
        for field_id, value in defaults.items():
            self.ids[field_id].text = value
        self.ids.db_dosimeter_id.disabled = False
        self.ids.db_dosimeter_active.active = True

    def novo_dosimetro(self):
        self._preparar_novo_dosimetro()
        self.dosimeter_message = "Novo cadastro"

    def salvar_dosimetro(self):
        dosimeter_id = self.ids.db_dosimeter_id.text
        values = {
            "ecc_hp10": self.ids.db_dosimeter_ecc_hp10.text.replace(",", "."),
            "ecc_hp007": self.ids.db_dosimeter_ecc_hp007.text.replace(",", "."),
            "bl_hp10": self.ids.db_dosimeter_bl_hp10.text.replace(",", "."),
            "bl_hp007": self.ids.db_dosimeter_bl_hp007.text.replace(",", "."),
            "begin_date": self.ids.db_dosimeter_begin.text,
            "end_date": self.ids.db_dosimeter_end.text or None,
            "active": self.ids.db_dosimeter_active.active,
        }
        saved_id = None
        try:
            if self._editing_dosimeter_id is None:
                self.obter_database().register_dosimeter(
                    dosimeter_id,
                    **values,
                )
                saved_id = dosimeter_id.strip()
                message = "Dosímetro cadastrado com sucesso"
            else:
                if not self.obter_database().update_dosimeter(
                    self._editing_dosimeter_id,
                    new_dosimeter_id=dosimeter_id,
                    **values,
                ):
                    raise ValueError("Dosímetro não encontrado")
                saved_id = dosimeter_id.strip()
                self._editing_dosimeter_id = saved_id
                message = "Dosímetro atualizado com sucesso"
        except sqlite3.IntegrityError:
            message = "Dosímetro já cadastrado"
        except (TypeError, ValueError, sqlite3.Error) as error:
            message = str(error)
        if saved_id:
            self.ids.db_dosimeter_search.text = saved_id
        self.pesquisar_dosimetros()
        self.dosimeter_message = message

    def pesquisar_dosimetros(self):
        try:
            rows = self.obter_database().search_dosimeters(
                text=self.ids.db_dosimeter_search.text
            )
        except (sqlite3.Error, RuntimeError, ValueError) as error:
            self.dosimeter_message = f"Erro na pesquisa: {error}"
            return
        self.dosimeter_count = f"{len(rows)} registros"
        container = self.ids.db_dosimeter_results
        dataframe = self._montar_dataframe_dosimetros(rows)
        self._renderizar_dataframe(
            container,
            dataframe,
            widths=(0.17, 0.11, 0.12, 0.10, 0.11, 0.14, 0.14, 0.11),
            alignments=(
                "left", "right", "right", "right", "right", "center",
                "center", "center",
            ),
            selection_callback=self.selecionar_dosimetro,
        )
        search_text = self.ids.db_dosimeter_search.text.strip()
        if not rows and search_text and len(search_text) == 10 and search_text.isascii() and search_text.isdigit():
            self._preparar_novo_dosimetro(search_text)
            self.dosimeter_message = (
                "Dosímetro não cadastrado; formulário preenchido com valores padrão"
            )
            return
        if (
            len(rows) == 1
            and search_text
            and rows[0]["dosimeter_id"] == search_text
        ):
            self.selecionar_dosimetro(rows[0])

    def exportar_csv_dosimetros(self, *, date_from=None, date_to=None):
        try:
            rows = self.obter_database().search_dosimeters_for_export(
                text=self.ids.db_dosimeter_search.text,
                date_from=date_from,
                date_to=date_to,
            )
            dataframe = self._montar_dataframe_dosimetros(
                rows,
                incluir_ultima_leitura_bl=True,
            )
            output = ASSETS_DIR / "exports" / datetime.now().strftime(
                "dosimetros_%Y-%m-%d_%H-%M-%S_%f.csv"
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            dataframe.to_csv(
                output,
                index=False,
                encoding="utf-8-sig",
            )
            self.dosimeter_message = f"CSV exportado para {output}"
            return output
        except (OSError, sqlite3.Error, RuntimeError, ValueError) as error:
            self.dosimeter_message = f"Erro ao exportar CSV: {error}"
            return None

    def carregar_dosimetro_por_id(self, dosimeter_id=None):
        dosimeter_id = (
            dosimeter_id or self.ids.db_dosimeter_id.text
        ).strip()
        if not dosimeter_id:
            return False
        try:
            record = self.obter_database().get_dosimeter(dosimeter_id)
        except (sqlite3.Error, RuntimeError, ValueError) as error:
            self.dosimeter_message = f"Erro ao carregar dosímetro: {error}"
            return False
        if record is None:
            if len(dosimeter_id) != 10 or not dosimeter_id.isascii() or not dosimeter_id.isdigit():
                return False
            self._preparar_novo_dosimetro(dosimeter_id)
            self.ids.db_dosimeter_search.text = dosimeter_id
            self.dosimeter_message = (
                "Dosímetro não cadastrado; formulário preenchido com valores padrão"
            )
            return True
        self.ids.db_dosimeter_search.text = dosimeter_id
        self.selecionar_dosimetro(record)
        return True

    def selecionar_dosimetro(self, record):
        self._editing_dosimeter_id = record["dosimeter_id"]
        self.ids.db_dosimeter_id.text = record["dosimeter_id"]
        self.ids.db_dosimeter_id.disabled = False
        self.ids.db_dosimeter_ecc_hp10.text = f"{record['ecc_hp10']:.10g}"
        self.ids.db_dosimeter_ecc_hp007.text = f"{record['ecc_hp007']:.10g}"
        self.ids.db_dosimeter_bl_hp10.text = f"{record['bl_hp10']:.10g}"
        self.ids.db_dosimeter_bl_hp007.text = f"{record['bl_hp007']:.10g}"
        self.ids.db_dosimeter_begin.text = self._date_for_display(
            record["begin_date"]
        )
        self.ids.db_dosimeter_end.text = self._date_for_display(
            record["end_date"]
        )
        self.ids.db_dosimeter_active.active = bool(record["active"])
        self.dosimeter_message = "Dosímetro selecionado para edição"

    def excluir_dosimetro(self):
        if self._leitura_em_andamento():
            self.dosimeter_message = (
                "Finalize a leitura atual antes de excluir um dosímetro."
            )
            return
        dosimeter_id = (
            self._editing_dosimeter_id
            or self.ids.db_dosimeter_id.text.strip()
            or self.ids.db_dosimeter_search.text.strip()
        )
        try:
            record = self.obter_database().get_dosimeter(dosimeter_id)
            if record is None:
                raise ValueError("Pesquise e selecione um dosímetro para excluir")
        except (TypeError, ValueError, sqlite3.Error) as error:
            self.dosimeter_message = str(error)
            return

        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        content.add_widget(
            Label(
                text=(
                    f"Excluir o dosímetro {dosimeter_id}?\n\n"
                    "Todas as medições e históricos vinculados também serão "
                    "excluídos permanentemente."
                ),
                text_size=(520, None),
                halign="left",
                valign="middle",
            )
        )
        actions = BoxLayout(size_hint_y=None, height="42dp", spacing=8)
        cancel = Button(text="Cancelar")
        confirm = Button(text="Excluir definitivamente")
        actions.add_widget(cancel)
        actions.add_widget(confirm)
        content.add_widget(actions)
        popup = Popup(
            title="Confirmar exclusão do dosímetro",
            content=content,
            size_hint=(0.70, 0.45),
        )
        cancel.bind(on_release=popup.dismiss)
        confirm.bind(
            on_release=lambda *_args: self._confirmar_exclusao_dosimetro(
                popup,
                dosimeter_id,
            )
        )
        popup.open()

    def _confirmar_exclusao_dosimetro(self, popup, dosimeter_id):
        try:
            deleted = self.obter_database().delete_dosimeter_with_history(
                dosimeter_id
            )
        except (TypeError, ValueError, sqlite3.Error) as error:
            self.dosimeter_message = f"Erro ao excluir: {error}"
            return False
        if popup is not None:
            popup.dismiss()
        self.novo_dosimetro()
        self.ids.db_dosimeter_search.text = ""
        self.pesquisar_dosimetros()
        self.dosimeter_message = (
            f"Dosímetro excluído • {deleted['measurements']} medições removidas"
        )
        return True

    def alternar_dosimetro(self):
        dosimeter_id = self.ids.db_dosimeter_id.text
        try:
            record = self.obter_database().get_dosimeter(dosimeter_id)
            if record is None:
                raise ValueError("Dosímetro não encontrado")
            active = not bool(record["active"])
            self.obter_database().set_dosimeter_active(dosimeter_id, active)
            self.ids.db_dosimeter_active.active = active
            self.dosimeter_message = (
                "Dosímetro ativado" if active else "Dosímetro desativado"
            )
            self.pesquisar_dosimetros()
        except (TypeError, ValueError, sqlite3.Error) as error:
            self.dosimeter_message = str(error)

    def nova_leitora(self):
        self._editing_reader_id = None
        for field_id in (
            "db_reader_id",
            "db_reader_rcf",
            "db_reader_begin",
            "db_reader_end",
        ):
            self.ids[field_id].text = ""
        self.ids.db_reader_id.disabled = False
        self.ids.db_reader_active.active = True
        self.reader_message = "Novo cadastro"

    def salvar_leitora(self):
        reader_id = self.ids.db_reader_id.text
        values = {
            "rcf": self.ids.db_reader_rcf.text.replace(",", "."),
            "begin_date": self.ids.db_reader_begin.text,
            "end_date": self.ids.db_reader_end.text or None,
            "active": self.ids.db_reader_active.active,
        }
        saved_id = None
        try:
            if self._editing_reader_id is None:
                self.obter_database().register_reader(reader_id, **values)
                saved_id = reader_id.strip()
                message = "Leitora cadastrada com sucesso"
            else:
                if not self.obter_database().update_reader(
                    self._editing_reader_id,
                    new_reader_id=reader_id,
                    **values,
                ):
                    raise ValueError("Leitora não encontrada")
                saved_id = reader_id.strip()
                self._editing_reader_id = saved_id
                message = "Leitora atualizada com sucesso"
        except sqlite3.IntegrityError:
            message = "Leitora já cadastrada"
        except (TypeError, ValueError, sqlite3.Error) as error:
            message = str(error)
        if saved_id:
            self.ids.db_reader_search.text = saved_id
        self.pesquisar_leitoras()
        self.reader_message = message
        self._refresh_main_readers()

    def pesquisar_leitoras(self):
        try:
            rows = self.obter_database().search_readers(
                text=self.ids.db_reader_search.text
            )
        except (sqlite3.Error, RuntimeError, ValueError) as error:
            self.reader_message = f"Erro na pesquisa: {error}"
            return
        self.reader_count = f"{len(rows)} registros"
        container = self.ids.db_reader_results
        dataframe = self._montar_dataframe_leitoras(rows)
        self._renderizar_dataframe(
            container,
            dataframe,
            widths=(0.25, 0.12, 0.20, 0.20, 0.23),
            alignments=("left", "right", "center", "center", "center"),
            selection_callback=self.selecionar_leitora,
        )
        search_text = self.ids.db_reader_search.text.strip()
        if (
            len(rows) == 1
            and search_text
            and rows[0]["reader_id"] == search_text
        ):
            self.selecionar_leitora(rows[0])

    def carregar_leitora_por_id(self, reader_id=None):
        reader_id = (reader_id or self.ids.db_reader_id.text).strip()
        if not reader_id:
            return False
        try:
            record = self.obter_database().get_reader(reader_id)
        except (sqlite3.Error, RuntimeError, ValueError) as error:
            self.reader_message = f"Erro ao carregar leitora: {error}"
            return False
        if record is None:
            return False
        self.ids.db_reader_search.text = reader_id
        self.selecionar_leitora(record)
        return True

    def selecionar_leitora(self, record):
        self._editing_reader_id = record["reader_id"]
        self.ids.db_reader_id.text = record["reader_id"]
        self.ids.db_reader_id.disabled = False
        self.ids.db_reader_rcf.text = f"{record['rcf']:.10g}"
        self.ids.db_reader_begin.text = self._date_for_display(
            record["begin_date"]
        )
        self.ids.db_reader_end.text = self._date_for_display(
            record["end_date"]
        )
        self.ids.db_reader_active.active = bool(record["active"])
        self.reader_message = "Leitora selecionada para edição"

    def excluir_leitora(self):
        if self._leitura_em_andamento():
            self.reader_message = (
                "Finalize a leitura atual antes de excluir uma leitora."
            )
            return
        reader_id = (
            self._editing_reader_id
            or self.ids.db_reader_id.text.strip()
            or self.ids.db_reader_search.text.strip()
        )
        try:
            record = self.obter_database().get_reader(reader_id)
            if record is None:
                raise ValueError("Pesquise e selecione uma leitora para excluir")
        except (TypeError, ValueError, sqlite3.Error) as error:
            self.reader_message = str(error)
            return

        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        content.add_widget(
            Label(
                text=(
                    f"Excluir a leitora {reader_id}?\n\n"
                    "Todas as medições e históricos vinculados também serão "
                    "excluídos permanentemente."
                ),
                text_size=(520, None),
                halign="left",
                valign="middle",
            )
        )
        actions = BoxLayout(size_hint_y=None, height="42dp", spacing=8)
        cancel = Button(text="Cancelar")
        confirm = Button(text="Excluir definitivamente")
        actions.add_widget(cancel)
        actions.add_widget(confirm)
        content.add_widget(actions)
        popup = Popup(
            title="Confirmar exclusão da leitora",
            content=content,
            size_hint=(0.70, 0.45),
        )
        cancel.bind(on_release=popup.dismiss)
        confirm.bind(
            on_release=lambda *_args: self._confirmar_exclusao_leitora(
                popup,
                reader_id,
            )
        )
        popup.open()

    def _confirmar_exclusao_leitora(self, popup, reader_id):
        try:
            deleted = self.obter_database().delete_reader_with_measurements(
                reader_id
            )
        except (TypeError, ValueError, sqlite3.Error) as error:
            self.reader_message = f"Erro ao excluir: {error}"
            return False
        if popup is not None:
            popup.dismiss()
        self.nova_leitora()
        self.ids.db_reader_search.text = ""
        self.pesquisar_leitoras()
        self._refresh_main_readers()
        self.reader_message = (
            f"Leitora excluída • {deleted['measurements']} medições removidas"
        )
        return True

    def alternar_leitora(self):
        reader_id = self.ids.db_reader_id.text
        try:
            record = self.obter_database().get_reader(reader_id)
            if record is None:
                raise ValueError("Leitora não encontrada")
            active = not bool(record["active"])
            self.obter_database().set_reader_active(reader_id, active)
            self.ids.db_reader_active.active = active
            self.reader_message = (
                "Leitora ativada" if active else "Leitora desativada"
            )
            self.pesquisar_leitoras()
            self._refresh_main_readers()
        except (TypeError, ValueError, sqlite3.Error) as error:
            self.reader_message = str(error)

    @staticmethod
    def _montar_dataframe_dosimetros(
        rows,
        *,
        incluir_ultima_leitura_bl=False,
    ):
        columns = [
            "Dosímetro", "ECC Hp(10)", "ECC Hp(0,07)",
            "BL Hp(10)", "BL Hp(0,07)",
            "Data inicial", "Data final", "Status",
        ]
        if incluir_ultima_leitura_bl:
            columns.append("\u00daltima leitura BL")
        if not rows:
            return pd.DataFrame(columns=columns)
        frame = pd.DataFrame.from_records(rows).sort_values(
            "dosimeter_id",
            kind="stable",
        )
        records = [rows[index] for index in frame.index]
        frame["Dosímetro"] = frame["dosimeter_id"].astype("string")
        frame["ECC Hp(10)"] = pd.to_numeric(frame["ecc_hp10"]).map(
            lambda value: f"{value:.10g}"
        )
        frame["ECC Hp(0,07)"] = pd.to_numeric(frame["ecc_hp007"]).map(
            lambda value: f"{value:.10g}"
        )
        frame["BL Hp(10)"] = pd.to_numeric(frame["bl_hp10"]).map(
            lambda value: f"{value:.10g}"
        )
        frame["BL Hp(0,07)"] = pd.to_numeric(frame["bl_hp007"]).map(
            lambda value: f"{value:.10g}"
        )
        frame["Data inicial"] = pd.to_datetime(
            frame["begin_date"],
            errors="coerce",
        ).dt.strftime("%d/%m/%Y")
        frame["Data final"] = pd.to_datetime(
            frame["end_date"],
            errors="coerce",
        ).dt.strftime("%d/%m/%Y")
        frame["Status"] = frame["active"].map({1: "Ativo", 0: "Inativo"})
        if incluir_ultima_leitura_bl:
            local_timezone = datetime.now().astimezone().tzinfo
            frame["\u00daltima leitura BL"] = (
                pd.to_datetime(
                    frame["last_bl_read_at"],
                    utc=True,
                    errors="coerce",
                )
                .dt.tz_convert(local_timezone)
                .dt.strftime("%d/%m/%Y %H:%M:%S")
            )
        result = frame.loc[:, columns].fillna("—").reset_index(drop=True)
        result.attrs["records"] = records
        return result

    @staticmethod
    def _montar_dataframe_leitoras(rows):
        columns = ["Leitora", "RCF", "Data inicial", "Data final", "Status"]
        if not rows:
            return pd.DataFrame(columns=columns)
        frame = pd.DataFrame.from_records(rows).sort_values(
            "reader_id",
            kind="stable",
        )
        records = [rows[index] for index in frame.index]
        frame["Leitora"] = frame["reader_id"].astype("string")
        frame["RCF"] = pd.to_numeric(frame["rcf"]).map(
            lambda value: f"{value:.10g}"
        )
        frame["Data inicial"] = pd.to_datetime(
            frame["begin_date"],
            errors="coerce",
        ).dt.strftime("%d/%m/%Y")
        frame["Data final"] = pd.to_datetime(
            frame["end_date"],
            errors="coerce",
        ).dt.strftime("%d/%m/%Y")
        frame["Status"] = frame["active"].map({1: "Ativa", 0: "Inativa"})
        result = frame.loc[:, columns].fillna("—").reset_index(drop=True)
        result.attrs["records"] = records
        return result

    @staticmethod
    def _montar_dataframe_medicoes(rows):
        columns = [
            "Data/hora",
            "Dosímetro",
            "Leitora",
            "Modo",
            "Grandeza",
            "Dose (mSv)",
            "Status",
        ]
        if not rows:
            return pd.DataFrame(columns=columns)
        frame = pd.DataFrame.from_records(rows)
        frame["_timestamp"] = pd.to_datetime(
            frame["measured_at"],
            utc=True,
            errors="coerce",
        )
        frame = frame.sort_values("_timestamp", ascending=False, kind="stable")
        records = [rows[index] for index in frame.index]
        local_timezone = datetime.now().astimezone().tzinfo
        frame["Data/hora"] = frame["_timestamp"].dt.tz_convert(
            local_timezone
        ).dt.strftime("%d/%m/%Y %H:%M:%S")
        frame["Dosímetro"] = frame["dosimeter_id"].fillna("—").astype("string")
        frame["Leitora"] = frame["reader_id"].fillna("—").astype("string")
        frame["Modo"] = frame["test_mode"].astype("string")
        frame["Grandeza"] = frame["dose_channel"].map(
            {"HP10": "Hp(10)", "HP007": "Hp(0,07)"}
        ).fillna("—")
        frame["Dose (mSv)"] = pd.to_numeric(frame["dose_msv"]).map(
            lambda value: f"{value:.3f}"
        )
        frame["Status"] = frame["status"].astype("string")
        result = frame.loc[:, columns].fillna("—").reset_index(drop=True)
        result.attrs["records"] = records
        return result

    @staticmethod
    def _montar_dataframe_historico(
        rows,
        *,
        time_column,
        hp10_column,
        hp007_column,
        status_column,
        unit="mSv",
    ):
        columns = [
            "Data/hora", "Dosímetro", f"Hp(10) {unit}",
            f"Hp(0,07) {unit}", "Status"
        ]
        if not rows:
            return pd.DataFrame(columns=columns)

        frame = pd.DataFrame.from_records(rows)
        timestamps = pd.to_datetime(frame[time_column], utc=True, errors="coerce")
        local_timezone = datetime.now().astimezone().tzinfo
        frame["Data/hora"] = timestamps.dt.tz_convert(local_timezone).dt.strftime(
            "%d/%m/%Y %H:%M:%S"
        )
        frame["Dosímetro"] = frame["dosimeter_id"].astype("string")

        hp10 = pd.to_numeric(frame[hp10_column], errors="coerce")
        hp007 = pd.to_numeric(frame[hp007_column], errors="coerce")
        formatter = (
            (lambda value: f"{value:.10g}")
            if unit == "Contagens"
            else (lambda value: f"{value:.3f}")
        )
        frame[f"Hp(10) {unit}"] = hp10.map(
            lambda value: "—" if pd.isna(value) else formatter(value)
        )
        frame[f"Hp(0,07) {unit}"] = hp007.map(
            lambda value: "—" if pd.isna(value) else formatter(value)
        )
        frame["Status"] = frame[status_column].astype("string")
        frame = frame.sort_values(time_column, ascending=False, kind="stable")
        return frame.loc[:, columns].reset_index(drop=True)

    @staticmethod
    def _historico_para_exportacao(dataframe):
        """Mantém os campos exibidos e deixa Data/hora como última coluna."""
        columns = [column for column in dataframe.columns if column != "Data/hora"]
        columns.append("Data/hora")
        return dataframe.loc[:, columns]

    @staticmethod
    def _renderizar_dataframe(
        container,
        dataframe,
        *,
        widths=None,
        alignments=None,
        selection_callback=None,
    ):
        container.clear_widgets()
        column_count = len(dataframe.columns)
        widths = widths or tuple(1 / column_count for _ in range(column_count))
        alignments = alignments or tuple("left" for _ in range(column_count))
        records = dataframe.attrs.get("records", [])
        for row_index, values in enumerate(
            dataframe.itertuples(index=False, name=None)
        ):
            record = records[row_index] if row_index < len(records) else None
            row = LinhaTabelaDados(
                record=record,
                selection_callback=selection_callback,
                size_hint_y=None,
                height="38dp",
                spacing="1dp",
            )
            background = (
                (0.145, 0.153, 0.169, 1)
                if row_index % 2 == 0
                else (0.115, 0.122, 0.137, 1)
            )
            for value, width, alignment in zip(
                values,
                widths,
                alignments,
            ):
                row.add_widget(
                    CelulaTabelaDados(
                        text=str(value),
                        size_hint_x=width,
                        font_size="13sp",
                        halign=alignment,
                        color=(0.92, 0.94, 0.97, 1),
                        background_color=background,
                    )
                )
            container.add_widget(row)

    def pesquisar_doses_pessoais(self):
        try:
            self._personal_dose_rows = (
                self.obter_database().search_personal_doses(
                    dosimeter_id=self.ids.db_personal_dose_dosimeter.text or None,
                    date_from=self.ids.db_personal_dose_from.text or None,
                    date_to=self.ids.db_personal_dose_to.text or None,
                    limit=DATABASE_PAGE_SIZE,
                )
            )
        except (TypeError, ValueError, sqlite3.Error, RuntimeError) as error:
            self.personal_dose_message = f"Erro na pesquisa: {error}"
            return
        self.personal_dose_count = f"{len(self._personal_dose_rows)} registros"
        container = self.ids.db_personal_dose_results
        dataframe = self._montar_dataframe_historico(
            self._personal_dose_rows,
            time_column="time_dos",
            hp10_column="hp10_dos",
            hp007_column="hp007_dos",
            status_column="status_dos",
        )
        self._renderizar_dataframe(
            container,
            dataframe,
            widths=(0.25, 0.20, 0.17, 0.17, 0.21),
            alignments=("left", "center", "right", "right", "center"),
        )
        self.personal_dose_message = "Pesquisa concluída"

    def pesquisar_backgrounds(self):
        try:
            self._background_rows = self.obter_database().search_backgrounds(
                dosimeter_id=self.ids.db_background_dosimeter.text or None,
                date_from=self.ids.db_background_from.text or None,
                date_to=self.ids.db_background_to.text or None,
                limit=DATABASE_PAGE_SIZE,
            )
        except (TypeError, ValueError, sqlite3.Error, RuntimeError) as error:
            self.background_message = f"Erro na pesquisa: {error}"
            return
        self.background_count = f"{len(self._background_rows)} registros"
        container = self.ids.db_background_results
        dataframe = self._montar_dataframe_historico(
            self._background_rows,
            time_column="time_bg",
            hp10_column="hp10_counts",
            hp007_column="hp007_counts",
            status_column="status_bg",
            unit="Contagens",
        )
        self._renderizar_dataframe(
            container,
            dataframe,
            widths=(0.25, 0.20, 0.17, 0.17, 0.21),
            alignments=("left", "center", "right", "right", "center"),
        )
        self.background_message = "Pesquisa concluída"

    def abrir_popup_exportacao(self, export_type):
        configurations = {
            "personal": {
                "title": "Exportar Integral da Área",
                "from_id": "db_personal_dose_from",
                "to_id": "db_personal_dose_to",
            },
            "background": {
                "title": "Exportar Linha de Base",
                "from_id": "db_background_from",
                "to_id": "db_background_to",
            },
            "measurements": {
                "title": "Exportar medições",
                "from_id": "db_history_from",
                "to_id": "db_history_to",
            },
            "dosimeters": {
                "title": "Exportar Dosímetros",
                "from_id": None,
                "to_id": None,
            },
        }
        try:
            configuration = configurations[export_type]
        except KeyError as error:
            raise ValueError("Tipo de exportação inválido") from error

        initial = EntradaData(
            text=(
                self.ids[configuration["from_id"]].text
                if configuration["from_id"]
                else ""
            ),
            hint_text="dd/mm/aaaa",
            multiline=False,
            size_hint_y=None,
            height="38dp",
        )
        final = EntradaData(
            text=(
                self.ids[configuration["to_id"]].text
                if configuration["to_id"]
                else ""
            ),
            hint_text="dd/mm/aaaa",
            multiline=False,
            size_hint_y=None,
            height="38dp",
        )
        today = CheckBox(
            active=False,
            size_hint=(None, None),
            width="32dp",
            height="32dp",
        )
        error_message = Label(
            text="",
            color=(1, 0.45, 0.45, 1),
            size_hint_y=None,
            height="30dp",
            text_size=(None, None),
            halign="left",
            valign="middle",
        )

        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        content.add_widget(
            Label(
                text="Selecione o período dos dados que será exportado.",
                size_hint_y=None,
                height="32dp",
                halign="left",
                valign="middle",
                text_size=(None, None),
            )
        )
        period = GridLayout(
            cols=2,
            spacing=8,
            size_hint_y=None,
            height="92dp",
        )
        period.add_widget(Label(text="Data inicial", halign="left"))
        period.add_widget(initial)
        period.add_widget(Label(text="Data final", halign="left"))
        period.add_widget(final)
        content.add_widget(period)

        today_option = BoxLayout(
            spacing=8,
            size_hint_y=None,
            height="36dp",
        )
        today_option.add_widget(today)
        today_option.add_widget(
            Label(
                text="Dados de hoje",
                halign="left",
                valign="middle",
                text_size=(None, None),
            )
        )
        content.add_widget(today_option)
        content.add_widget(error_message)

        actions = BoxLayout(size_hint_y=None, height="42dp", spacing=8)
        cancel = Button(text="Cancelar")
        export = Button(text="Exportar CSV")
        actions.add_widget(cancel)
        actions.add_widget(export)
        content.add_widget(actions)

        popup = Popup(
            title=configuration["title"],
            content=content,
            size_hint=(0.62, 0.52),
            auto_dismiss=False,
        )
        original_values = (initial.text, final.text)

        def toggle_today(_checkbox, active):
            if active:
                today_text = datetime.now().strftime("%d/%m/%Y")
                initial.text = today_text
                final.text = today_text
                initial.disabled = True
                final.disabled = True
            else:
                initial.text, final.text = original_values
                initial.disabled = False
                final.disabled = False

        today.bind(active=toggle_today)
        cancel.bind(on_release=popup.dismiss)
        export.bind(
            on_release=lambda *_args: self._confirmar_exportacao(
                popup,
                export_type,
                initial,
                final,
                today,
                error_message,
            )
        )
        self._export_popup_fields = {
            "initial": initial,
            "final": final,
            "today": today,
            "error": error_message,
        }
        popup.open()
        return popup

    def _confirmar_exportacao(
        self,
        popup,
        export_type,
        initial,
        final,
        today,
        error_message,
    ):
        date_from = initial.text.strip()
        date_to = final.text.strip()
        if today.active:
            today_text = datetime.now().strftime("%d/%m/%Y")
            date_from = today_text
            date_to = today_text
        elif not date_from or not date_to:
            error_message.text = (
                "Informe a data inicial e a data final, ou marque "
                "'Dados de hoje'."
            )
            return False
        try:
            initial_date = datetime.strptime(date_from, "%d/%m/%Y")
            final_date = datetime.strptime(date_to, "%d/%m/%Y")
        except ValueError:
            error_message.text = "Use o formato dd/mm/aaaa nas duas datas."
            return False
        if final_date < initial_date:
            error_message.text = (
                "A data final não pode ser anterior à data inicial."
            )
            return False

        export_methods = {
            "personal": self.exportar_csv_doses_pessoais,
            "background": self.exportar_csv_backgrounds,
            "measurements": self.exportar_csv_historico,
            "dosimeters": self.exportar_csv_dosimetros,
        }
        result = export_methods[export_type](
            date_from=date_from,
            date_to=date_to,
        )
        if result is None:
            message_attributes = {
                "personal": "personal_dose_message",
                "background": "background_message",
                "measurements": "history_message",
                "dosimeters": "dosimeter_message",
            }
            error_message.text = getattr(
                self,
                message_attributes[export_type],
            )
            return False
        popup.dismiss()
        self._export_popup_fields = None
        return result

    def exportar_csv_doses_pessoais(self, *, date_from=None, date_to=None):
        try:
            rows = self.obter_database().search_personal_doses(
                dosimeter_id=self.ids.db_personal_dose_dosimeter.text or None,
                date_from=(
                    self.ids.db_personal_dose_from.text or None
                    if date_from is None
                    else date_from
                ),
                date_to=(
                    self.ids.db_personal_dose_to.text or None
                    if date_to is None
                    else date_to
                ),
                limit=10_000,
            )
            output = ASSETS_DIR / "exports" / datetime.now().strftime(
                "personal_dose_%Y-%m-%d_%H-%M-%S_%f.csv"
            )
            dataframe = self._montar_dataframe_historico(
                rows,
                time_column="time_dos",
                hp10_column="hp10_dos",
                hp007_column="hp007_dos",
                status_column="status_dos",
            )
            dataframe = self._historico_para_exportacao(dataframe)
            output.parent.mkdir(parents=True, exist_ok=True)
            dataframe.to_csv(output, index=False, encoding="utf-8-sig")
            self.personal_dose_message = f"CSV exportado para {output}"
            return output
        except (OSError, RuntimeError, sqlite3.Error, ValueError) as error:
            self.personal_dose_message = f"Erro ao exportar CSV: {error}"
            return None

    def exportar_csv_backgrounds(self, *, date_from=None, date_to=None):
        try:
            rows = self.obter_database().search_backgrounds(
                dosimeter_id=self.ids.db_background_dosimeter.text or None,
                date_from=(
                    self.ids.db_background_from.text or None
                    if date_from is None
                    else date_from
                ),
                date_to=(
                    self.ids.db_background_to.text or None
                    if date_to is None
                    else date_to
                ),
                limit=10_000,
            )
            output = ASSETS_DIR / "exports" / datetime.now().strftime(
                "background_%Y-%m-%d_%H-%M-%S_%f.csv"
            )
            dataframe = self._montar_dataframe_historico(
                rows,
                time_column="time_bg",
                hp10_column="hp10_counts",
                hp007_column="hp007_counts",
                status_column="status_bg",
                unit="Contagens",
            )
            dataframe = self._historico_para_exportacao(dataframe)
            output.parent.mkdir(parents=True, exist_ok=True)
            dataframe.to_csv(output, index=False, encoding="utf-8-sig")
            self.background_message = f"CSV exportado para {output}"
            return output
        except (OSError, RuntimeError, sqlite3.Error, ValueError) as error:
            self.background_message = f"Erro ao exportar CSV: {error}"
            return None

    def pesquisar_historico(self):
        mode = self.ids.db_history_mode.text
        try:
            self._history_rows = self.obter_database().search_measurements(
                dosimeter_id=self.ids.db_history_dosimeter.text or None,
                reader_id=self.ids.db_history_reader.text or None,
                test_mode=None if mode == "Todos" else mode,
                date_from=self.ids.db_history_from.text or None,
                date_to=self.ids.db_history_to.text or None,
                limit=DATABASE_PAGE_SIZE,
            )
        except (TypeError, ValueError, sqlite3.Error, RuntimeError) as error:
            self.history_message = f"Erro na pesquisa: {error}"
            return
        self.history_count = f"{len(self._history_rows)} registros"
        container = self.ids.db_history_results
        dataframe = self._montar_dataframe_medicoes(self._history_rows)
        self._renderizar_dataframe(
            container,
            dataframe,
            widths=(0.20, 0.14, 0.12, 0.13, 0.11, 0.12, 0.18),
            alignments=(
                "left",
                "center",
                "center",
                "center",
                "center",
                "right",
                "center",
            ),
            selection_callback=self.mostrar_medicao,
        )
        self.history_message = "Pesquisa concluída"

    def mostrar_medicao(self, record):
        self.history_details = (
            f"ID {record['id']} • {record['file_name'] or 'sem arquivo'}\n"
            f"Grandeza: {self._channel_for_display(record.get('dose_channel'))}"
            f"   Sessão: {record.get('test_session_id') or '—'}\n"
            f"Count: {record['count_01s']}   Current: {record['current_ma']:.10g}"
            f"   Light: {record['light_mv']:.10g}"
            f"   Dose: {record['dose_msv']:.10g}\n"
            f"ECC: {record['ecc_applied']:.10g}   "
            f"RCF: {record['rcf_applied']:.10g}   "
            f"Fang: {record['fang_applied']:.10g}   "
            f"Fenerg: {record['fenerg_applied']:.10g}   "
            f"BL: {record['baseline_applied']:.10g}\n"
            f"Caminho: {record['file_path'] or '—'}\n"
            f"Observação: {record['notes'] or '—'}"
        )

    @staticmethod
    def _channel_for_display(channel):
        return {"HP10": "Hp(10)", "HP007": "Hp(0,07)"}.get(channel, "—")

    def exportar_csv_historico(self, *, date_from=None, date_to=None):
        try:
            mode = self.ids.db_history_mode.text
            rows = self.obter_database().search_measurements(
                dosimeter_id=self.ids.db_history_dosimeter.text or None,
                reader_id=self.ids.db_history_reader.text or None,
                test_mode=None if mode == "Todos" else mode,
                date_from=(
                    self.ids.db_history_from.text or None
                    if date_from is None
                    else date_from
                ),
                date_to=(
                    self.ids.db_history_to.text or None
                    if date_to is None
                    else date_to
                ),
                limit=10_000,
            )
            output = (
                ASSETS_DIR
                / "exports"
                / datetime.now().strftime(
                    "measurements_%Y-%m-%d_%H-%M-%S_%f.csv"
                )
            )
            result = self.obter_database().export_csv(
                output,
                rows,
            )
            self.history_message = f"CSV exportado para {result}"
            return result
        except (OSError, sqlite3.Error, ValueError) as error:
            self.history_message = f"Erro ao exportar CSV: {error}"
            return None

    def abrir_dialogo_backup(self):
        backup_directory = ASSETS_DIR / "backups"
        backup_directory.mkdir(parents=True, exist_ok=True)
        content = BoxLayout(orientation="vertical", spacing=8, padding=8)
        chooser = FileChooserListView(
            path=str(backup_directory),
            dirselect=True,
        )
        file_name = TextInput(
            text=datetime.now().strftime(
                "measurements_backup_%Y-%m-%d_%H-%M-%S.sqlite3"
            ),
            multiline=False,
            size_hint_y=None,
            height="38dp",
        )
        actions = BoxLayout(size_hint_y=None, height="42dp", spacing=8)
        cancel = Button(text="Cancelar")
        save = Button(text="Criar backup")
        actions.add_widget(cancel)
        actions.add_widget(save)
        content.add_widget(chooser)
        content.add_widget(file_name)
        content.add_widget(actions)
        popup = Popup(
            title="Escolha o destino do backup",
            content=content,
            size_hint=(0.85, 0.85),
        )
        cancel.bind(on_release=popup.dismiss)
        save.bind(
            on_release=lambda *_args: self._confirmar_backup(
                popup,
                chooser,
                file_name.text,
            )
        )
        popup.open()

    def _confirmar_backup(self, popup, chooser, file_name):
        selected = Path(chooser.selection[0]) if chooser.selection else None
        directory = (
            selected
            if selected is not None and selected.is_dir()
            else Path(chooser.path)
        )
        try:
            clean_name = str(file_name).strip()
            if (
                not clean_name
                or Path(clean_name).name != clean_name
                or clean_name in (".", "..")
            ):
                raise ValueError("Nome de backup inválido")
            if not clean_name.lower().endswith(".sqlite3"):
                clean_name += ".sqlite3"
            result = self.criar_backup(directory / clean_name)
        except (OSError, sqlite3.Error, ValueError) as error:
            self.history_message = f"Erro ao criar backup: {error}"
            return
        popup.dismiss()
        self.history_message = f"Backup exportado para {result}"

    def criar_backup(self, destination):
        return self.obter_database().backup(destination)

    def abrir_dialogo_importacao(self):
        if self._leitura_em_andamento():
            self.history_message = (
                "Finalize a leitura atual antes de importar outro banco."
            )
            return
        import_directory = ASSETS_DIR / "backups"
        import_directory.mkdir(parents=True, exist_ok=True)
        content = BoxLayout(orientation="vertical", spacing=8, padding=8)
        chooser = FileChooserListView(
            path=str(import_directory),
            filters=["*.sqlite3", "*.sqlite", "*.db"],
            multiselect=False,
            dirselect=False,
        )
        actions = BoxLayout(size_hint_y=None, height="42dp", spacing=8)
        cancel = Button(text="Cancelar")
        select = Button(text="Selecionar banco")
        actions.add_widget(cancel)
        actions.add_widget(select)
        content.add_widget(chooser)
        content.add_widget(actions)
        popup = Popup(
            title="Importar banco de dados SQLite",
            content=content,
            size_hint=(0.85, 0.85),
        )
        cancel.bind(on_release=popup.dismiss)
        select.bind(
            on_release=lambda *_args: self._solicitar_confirmacao_importacao(
                popup,
                chooser,
            )
        )
        popup.open()

    def _solicitar_confirmacao_importacao(self, selection_popup, chooser):
        if not chooser.selection:
            self.history_message = "Selecione um arquivo de banco de dados."
            return
        source = Path(chooser.selection[0]).expanduser().resolve()
        if not source.is_file():
            self.history_message = "O arquivo selecionado não existe."
            return
        selection_popup.dismiss()

        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        message = Label(
            text=(
                "O banco atual será substituído pelos dados de:\n"
                f"{source}\n\n"
                "Um backup automático do banco atual será criado antes "
                "da importação."
            ),
            text_size=(620, None),
            halign="left",
            valign="middle",
        )
        actions = BoxLayout(size_hint_y=None, height="42dp", spacing=8)
        cancel = Button(text="Cancelar")
        confirm = Button(text="Confirmar importação")
        actions.add_widget(cancel)
        actions.add_widget(confirm)
        content.add_widget(message)
        content.add_widget(actions)
        popup = Popup(
            title="Confirmar importação",
            content=content,
            size_hint=(0.75, 0.52),
        )
        cancel.bind(on_release=popup.dismiss)
        confirm.bind(
            on_release=lambda *_args: self._confirmar_importacao(
                popup,
                source,
                message,
            )
        )
        popup.open()

    def _confirmar_importacao(self, popup, source, message):
        if self._leitura_em_andamento():
            message.text = (
                "A importação foi cancelada porque existe uma leitura em curso."
            )
            return
        try:
            result = self.importar_banco(source)
        except (
            OSError,
            sqlite3.Error,
            TypeError,
            ValueError,
            RuntimeError,
        ) as error:
            message.text = f"Não foi possível importar o banco:\n{error}"
            self.history_message = f"Erro ao importar banco: {error}"
            return
        popup.dismiss()
        self.history_message = (
            "Banco importado com sucesso. Backup anterior salvo em "
            f"{result['backup']}"
        )

    def importar_banco(self, source):
        result = self.obter_database().import_database(source)
        self.on_pre_enter()
        self._refresh_main_readers()
        if self.manager and self.manager.has_screen("main"):
            main_screen = self.manager.get_screen("main")
            main_screen._invalidar_dosimetro(
                "Banco importado; valide novamente o dosímetro."
            )
        return result

    def _leitura_em_andamento(self):
        if not self.manager or not self.manager.has_screen("main"):
            return False
        main_screen = self.manager.get_screen("main")
        return bool(
            main_screen.current_measurement_id is not None
            or main_screen.log_arquivo
        )

    def _refresh_main_readers(self):
        if self.manager and self.manager.has_screen("main"):
            self.manager.get_screen("main").atualizar_leitoras_cadastradas()

    @staticmethod
    def _date_for_display(value):
        if not value:
            return ""
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y")

    @staticmethod
    def _display_datetime(value):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone().strftime("%d/%m/%Y %H:%M:%S")
        except (AttributeError, ValueError):
            return str(value)


class TelaGraficos(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.arquivo_selecionado = None
        self.png_grafico = Path(tempfile.gettempdir()) / "grafico_osl.png"
        self.operacao_em_andamento = False

    def on_pre_enter(self, *args):
        self.ids.arvore_arquivos.selecao_callback = self.selecionar_no
        self.ids.arvore_arquivos.duplo_clique_callback = self._plotar_duplo_clique
        self.ids.arvore_arquivos.recarregar(TESTES_DIR)

    def selecionar_no(self, arvore, no):
        caminho = getattr(no, "caminho", None)
        if not caminho or not caminho.is_file():
            return
        self.arquivo_selecionado = caminho
        self.atualizar_status_grafico(
            f"Selecionado: {self.arquivo_selecionado.name}"
        )

    def _plotar_duplo_clique(self, arvore, no):
        self.selecionar_no(arvore, no)
        self.gerar_grafico()

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
    title = "OSLMeter V4.1"
    RAD_INSTRUMENTS_URL = "https://radinstruments.com.br/"

    def build(self):
        ensure_user_data()
        if not hasattr(self, "database") or self.database is None:
            self.database = Database()
        root = Builder.load_file(resource_path("interface_OSL.kv"))
        main_screen = root.get_screen("main")
        main_screen.database = self.database
        root.get_screen("banco_dados").database = self.database
        main_screen.carregar_configuracoes()
        return root

    def on_start(self):
        # Garantia adicional para o executável no Windows: aqui a janela SDL2
        # já foi criada e Window.maximize() pode atuar sobre ela.
        Window.maximize()

    def trocar_para_graficos(self):
        self.root.transition.direction = "up"
        self.root.current = "graficos"

    def abrir_popup_rad(self):
        """Show RADinstruments information and offer a link to its website."""
        content = BoxLayout(
            orientation="vertical",
            spacing="12dp",
            padding="16dp",
        )
        content.add_widget(
            Image(
                source=resource_path("assets/UI/rad_logo.png"),
                size_hint_y=None,
                height="86dp",
                fit_mode="contain",
            )
        )
        content.add_widget(
            Label(
                text="Acesse o site da RADinstruments para conhecer mais.",
                halign="center",
                valign="middle",
            )
        )

        actions = BoxLayout(size_hint_y=None, height="42dp", spacing="8dp")
        close_button = Button(text="Fechar")
        site_button = Button(text="Ir para o site")
        actions.add_widget(close_button)
        actions.add_widget(site_button)
        content.add_widget(actions)

        popup = Popup(
            title="RADinstruments",
            content=content,
            size_hint=(None, None),
            size=("470dp", "260dp"),
        )
        close_button.bind(on_release=popup.dismiss)
        site_button.bind(
            on_release=lambda *_args: self._abrir_site_rad(popup)
        )
        popup.open()
        return popup

    def _abrir_site_rad(self, popup):
        webbrowser.open(self.RAD_INSTRUMENTS_URL)
        popup.dismiss()

    def on_stop(self):
        main = self.root.get_screen("main")
        if main.log_arquivo:
            main.fechar_log(
                status="INTERROMPIDO",
                notes="Aplicação encerrada durante a leitura",
            )

        main.desconectar_serial(atualizar_botao=False)


def main():
    Window.minimum_width = 900
    Window.minimum_height = 650
    AplicativoInterfaceOSL().run()


if __name__ == "__main__":
    main()
