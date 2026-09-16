from __future__ import annotations

import time
import unittest

from simulacao.simulador_osl import SimuladorOSL


class FakeStatus:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value


class FakeSerial:
    is_open = True

    def __init__(self):
        self.writes = []

    def write(self, data):
        self.writes.append(data)
        return len(data)


class FakeRoot:
    def __init__(self):
        self.scheduled = []

    def after(self, delay, callback):
        self.scheduled.append((delay, callback))


class SimuladorOSLTestCase(unittest.TestCase):
    def _simulador(self):
        simulador = SimuladorOSL.__new__(SimuladorOSL)
        simulador.root = FakeRoot()
        simulador.serial_connection = FakeSerial()
        simulador.status = FakeStatus()
        simulador.rodando = False
        simulador.contador = 0
        simulador.potencia = 4
        simulador.tempo_leitura_ms = 3000
        simulador._inicio_leitura = None
        simulador._desenhar_led = lambda _ligado: None
        return simulador

    def test_parameter_command_updates_read_time(self):
        simulador = self._simulador()

        simulador._processar_comando("#S1%M1G4L01000P4Z05000Q4&")

        self.assertEqual(simulador.tempo_leitura_ms, 1000)
        self.assertEqual(simulador.serial_connection.writes, [b"#L1%I0000000&"])

    def test_reading_finishes_and_emits_end_frame_after_timeout(self):
        simulador = self._simulador()
        simulador.tempo_leitura_ms = 1000
        simulador.rodando = True
        simulador._inicio_leitura = time.monotonic() - 1.1

        simulador._enviar_amostra()

        self.assertFalse(simulador.rodando)
        self.assertEqual(
            simulador.serial_connection.writes,
            [b"#L1%I0000101&"],
        )
        self.assertEqual(simulador.status.value, "Leitura concluída")


if __name__ == "__main__":
    unittest.main()
