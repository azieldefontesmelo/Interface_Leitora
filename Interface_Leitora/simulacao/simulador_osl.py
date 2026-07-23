"""Simulador da leitora OSL usando a porta virtual COM6."""

import random
import threading
import tkinter as tk
from tkinter import messagebox

import serial


PORTA_SERIAL = "COM6"
BAUD_RATE = 115200


class SimuladorOSL:
    def __init__(self, root):
        self.root = root
        self.root.title("Simulador OSL")
        self.root.geometry("430x360")
        self.root.resizable(False, False)
        self.serial_connection = None
        self.rodando = False
        self.contador = 0
        self.potencia = 4
        self._montar_tela()
        self._conectar_serial()

    def _montar_tela(self):
        tk.Label(self.root, text="Simulador da Máquina OSL", font=("Arial", 16, "bold")).pack(pady=10)
        self.status = tk.StringVar(value=f"Conectando em {PORTA_SERIAL}...")
        tk.Label(self.root, textvariable=self.status, fg="#205493").pack()
        self.canvas = tk.Canvas(self.root, width=130, height=130, bg="#202020", highlightthickness=0)
        self.canvas.pack(pady=10)
        self.led = self.canvas.create_oval(25, 25, 105, 105, fill="#303030", outline="#888", width=3)
        tk.Label(self.root, text="LED de estimulação").pack()

        botoes = tk.Frame(self.root)
        botoes.pack(pady=12)
        tk.Button(botoes, text="Iniciar leitura", width=16, command=self.iniciar_leitura).grid(row=0, column=0, padx=4, pady=4)
        tk.Button(botoes, text="Parar", width=16, command=self.parar_leitura).grid(row=0, column=1, padx=4, pady=4)
        tk.Button(botoes, text="Zerar", width=16, command=self.zerar).grid(row=1, column=0, padx=4, pady=4)
        tk.Button(botoes, text="Ligar LED", width=16, command=self.ligar_led).grid(row=1, column=1, padx=4, pady=4)

    def _conectar_serial(self):
        try:
            self.serial_connection = serial.Serial(PORTA_SERIAL, BAUD_RATE, timeout=0.1)
            self.status.set(f"Conectado em {PORTA_SERIAL}; use a outra porta na interface.")
            threading.Thread(target=self._ler_serial, daemon=True).start()
        except (serial.SerialException, OSError) as erro:
            self.status.set(f"Erro ao abrir {PORTA_SERIAL}")
            messagebox.showerror("Simulador OSL", f"Não foi possível abrir {PORTA_SERIAL}:\n{erro}")

    def _ler_serial(self):
        buffer = ""
        while self.serial_connection and self.serial_connection.is_open:
            try:
                dados = self.serial_connection.read(self.serial_connection.in_waiting or 1)
                if not dados:
                    continue
                buffer += dados.decode("ascii", errors="ignore")
                while "&" in buffer:
                    comando, buffer = buffer.split("&", 1)
                    self._processar_comando(comando + "&")
            except (serial.SerialException, OSError):
                break

    def _processar_comando(self, comando):
        if "SC1001" in comando:
            self.iniciar_leitura()
        elif "SC1010" in comando:
            self.parar_leitura()
        elif "SC1011" in comando:
            self.zerar()
        elif "SC1100" in comando:
            self.ligar_led()
        elif comando.startswith("#S1%M"):
            try:
                self.potencia = int(comando.split("P", 1)[1][0])
            except (IndexError, ValueError):
                pass
            self._enviar("#L1%I0000000&")

    def _enviar(self, texto):
        if self.serial_connection and self.serial_connection.is_open:
            try:
                self.serial_connection.write(texto.encode("ascii"))
            except (serial.SerialException, OSError):
                self.status.set("Erro ao enviar dados pela serial")

    def iniciar_leitura(self):
        if not self.serial_connection or not self.serial_connection.is_open:
            self.status.set(f"{PORTA_SERIAL} não está conectada")
            return
        if not self.rodando:
            self.rodando = True
            self.status.set("Leitura em andamento")
            self._enviar_amostra()

    def _enviar_amostra(self):
        if not self.rodando:
            self._desenhar_led(False)
            return
        self.contador += 1
        leitura = random.randint(900, 1800)
        corrente = random.randint(15, 45)
        luz = int(100 + self.potencia * 90 + random.randint(-20, 20))
        self._desenhar_led(True)
        self._enviar(f"#L1%A{leitura}&#L1%E{corrente}&#L1%T{self.contador}&#L1%D{luz}&")
        self.root.after(100, self._enviar_amostra)

    def parar_leitura(self):
        self.rodando = False
        self._desenhar_led(False)
        self.status.set("Leitura parada")

    def zerar(self):
        self.contador = 0
        self.rodando = False
        self._desenhar_led(False)
        self.status.set("Contador zerado")

    def ligar_led(self):
        self._desenhar_led(True)

    def _desenhar_led(self, ligado):
        self.canvas.itemconfigure(self.led, fill="#ff3b30" if ligado else "#303030")

    def fechar(self):
        self.rodando = False
        if self.serial_connection and self.serial_connection.is_open:
            self.serial_connection.close()
        self.root.destroy()


if __name__ == "__main__":
    janela = tk.Tk()
    app = SimuladorOSL(janela)
    janela.protocol("WM_DELETE_WINDOW", app.fechar)
    janela.mainloop()
