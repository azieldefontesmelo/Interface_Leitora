import tempfile
import traceback
from collections import deque
from datetime import datetime
from math import hypot
from pathlib import Path
from threading import Thread

import serial
import serial.tools.list_ports
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.properties import BooleanProperty, NumericProperty
from kivy.uix.button import Button
from kivy.uix.screenmanager import Screen
from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.graphics import Color, Line, Rectangle
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
LOG_SERIAL_DIR = Path(__file__).resolve().parent / "assets" / "log"

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
        self._texto_anterior = self.text
        self._excluindo = False
        self.bind(text=self._agendar_formatacao)

    def _agendar_formatacao(self, *args):
        if self._formatacao_agendada:
            return
        self._excluindo = len(self.text) < len(self._texto_anterior)
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
        # Ao apagar a barra com Backspace, não a recria imediatamente.
        # Caso contrário o cursor fica preso depois de "20/07/".
        if len(digitos) in (2, 4) and not self._excluindo:
            formatado += "/"

        if self.text != formatado:
            self.text = formatado
        self._texto_anterior = self.text
        self._excluindo = False
        self.cursor = (len(self.text), 0)


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

    def on_touch_down(self, touch):
        if (
            self.pasta
            and not touch.is_mouse_scrolling
            and self.collide_point(*touch.pos)
        ):
            # Permite abrir/fechar a pasta clicando na linha inteira,
            # inclusive no ícone ou no nome, e não somente na seta.
            if isinstance(self.parent, TreeView):
                self.parent.toggle_node(self)
            return True

        if (
            touch.is_double_tap
            and self.caminho
            and self.caminho.is_file()
            and self.duplo_clique_callback
        ):
            self.duplo_clique_callback(self)
        return super().on_touch_down(touch)


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
        self.valor_count = 0
        self.valor_current = 0
        self.valor_light = 0
        self.log_arquivo = None
        self.log_serial_arquivo = None
        self.caminho_log_serial = None
        self.leitura_evento = None
        self.nova_linha = True
        Clock.schedule_once(self.atualizar_portas_serial, 0)
        # O tamanho do conteúdo do ScrollView só fica definitivo após o
        # primeiro ciclo de layout. Reposiciona no topo para não esconder os
        # controles de conexão em resoluções menores.
        Clock.schedule_once(self._mostrar_topo, 0)

    def _mostrar_topo(self, _dt):
        try:
            self.ids.rolagem_principal.scroll_y = 1
        except KeyError:
            pass

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
            self.ids.grafico_tempo_real.limpar()
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
        linhas[3] = f"Dose: {self.formatar_dose(self.calcular_dose())}\n"

        linhas_string[2] = f"Soma: {self.soma}"
        linhas_string[3] = f"Dose: {self.formatar_dose(self.calcular_dose())}"

        self.ids.label_dose.text = self.formatar_dose(self.calcular_dose())

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

    @staticmethod
    def formatar_dose(valor):
        """Usa tres casas para valores menores que 1 e duas nos demais."""
        valor = float(valor)
        return f"{valor:.3f}" if abs(valor) < 1 else f"{valor:.3f}"

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
        texto = str(dados).replace("\r", "\\r").replace("\n", "\\n")
        horario = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
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
                porta, BAUD_RATE, timeout=0.05
            )
            self._iniciar_log_serial(porta)
            self.leitura_evento = Clock.schedule_interval(self.ler_serial, 0.1)
            Clock.schedule_once(
                lambda dt: self.enviar_serial(COMANDO_INICIAL), 0.2
            )

            self.ids.botao_conexao_serial.text = "Disconnect"
            self.atualizar_status(f"Conectado em {porta} @ {BAUD_RATE}")

        except (OSError, serial.SerialException) as erro:
            self.desconectar_serial(atualizar_botao=False)
            self.atualizar_status(f"Erro ao conectar: {erro}")

    def desconectar_serial(self, atualizar_botao=True):
        if self.leitura_evento:
            self.leitura_evento.cancel()
            self.leitura_evento = None

        if self.serial_aberta():
            self.serial_connection.close()

        self.serial_connection = None
        self._fechar_log_serial()

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
            self._registrar_log_serial("TX", comando)
            self.atualizar_status(f"Enviado: {comando}")
        except serial.SerialException as erro:
            self._registrar_log_serial("ERRO TX", erro)
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
            self._registrar_log_serial("RX", texto)
            self.buffer_serial += texto

            while "&" in self.buffer_serial:
                frame, self.buffer_serial = self.buffer_serial.split("&", 1)
                if frame:
                    self.processar_frame(frame)

        except serial.SerialException as erro:
            self._registrar_log_serial("ERRO RX", erro)
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
            self.valor_light = valor
            self.ids.label_light.text = f"{valor}"
            self.soma_luz += valor
            self.atualizar_grafico_tempo_real()
            if self.f_luz_ref:
                print("luz_ref")
                self.ids.label_dose.text = self.formatar_dose(self.soma_luz)

        elif frame[:5] in ("#L1%A", "#L1%B", "#L1%E", "#L1%T"):
            if frame[:5] == "#L1%A":
                valor = int(frame[5:])
                self.valor_count = valor
                self.ids.label_count.text = f"{valor}"
                self.soma += valor

            if frame[:5] == "#L1%E":
                valor = int(frame[5:])
                self.valor_current = valor
                self.ids.label_current.text = f"{valor}"

            self.registrar_valor(frame, fim_linha=False)
        elif frame == "#L1%I0000000":
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
                    self.ids.label_dose.text = self.formatar_dose(self.soma_luz)
                else:
                    self.ids.label_dose.text = self.formatar_dose(self.soma)


                self.f_luz_ref = False

                self.f_fechar_log = False
                self.fechar_log()

        else:
            self.salvar_log(f"{valor};")

    # Comandos
    def botao_leitura(self):
        self.string_log = ""
        self.ids.label_dose.text = "0.000"
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
        self.ids.label_dose.text = "0.000"
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
