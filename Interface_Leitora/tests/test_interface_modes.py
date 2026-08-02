from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kivy.clock import Clock

import interface_OSL
from database import Database
from interface_OSL import AplicativoInterfaceOSL


class FakeSerial:
    def __init__(self):
        self.is_open = True
        self.writes = []
        self.in_waiting = 0

    def write(self, data):
        self.writes.append(data)

    def close(self):
        self.is_open = False


class InterfaceModeTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.root_path = Path(cls.temporary_directory.name)
        interface_OSL.TESTES_DIR = cls.root_path / "assets" / "testes"
        interface_OSL.LOG_SERIAL_DIR = cls.root_path / "assets" / "log"
        cls.database = Database(cls.root_path / "measurements.sqlite3")
        cls.database.register_dosimeter(
            "0123456789",
            ecc_hp10=1.25,
            ecc_hp007=1.5,
            bc_hp10=100,
            bc_hp007=200,
            begin_date="2025-01-01",
            end_date="2030-12-31",
        )
        cls.database.register_reader(
            "3001A01",
            rcf=0.000033,
            begin_date="2025-01-01",
        )
        cls.app = AplicativoInterfaceOSL()
        cls.app.database = cls.database
        cls.root = cls.app.build()
        cls.main = cls.root.get_screen("main")
        cls.bank = cls.root.get_screen("banco_dados")
        Clock.tick()
        cls.main.atualizar_leitoras_cadastradas()

    def setUp(self):
        self.database = Database(
            self.root_path / f"{self._testMethodName}.sqlite3"
        )
        self.database.register_dosimeter(
            "0123456789",
            ecc_hp10=1.25,
            ecc_hp007=1.5,
            bc_hp10=100,
            bc_hp007=200,
            begin_date="2025-01-01",
            end_date="2030-12-31",
        )
        self.database.register_reader(
            "3001A01",
            rcf=0.000033,
            begin_date="2025-01-01",
        )
        self.app.database = self.database
        self.main.database = self.database
        self.bank.database = self.database
        interface_OSL.TESTES_DIR = (
            self.root_path / self._testMethodName / "assets" / "testes"
        )
        interface_OSL.LOG_SERIAL_DIR = (
            self.root_path / self._testMethodName / "assets" / "log"
        )
        self.main.serial_connection = None
        self.main.log_arquivo = None
        self.main.current_measurement_id = None
        self.main.applied_parameters = None
        self.main.active_test_session_id = None
        self.main.active_test_dosimeter_id = None
        self.main.active_test_reading_type = None
        self.main.acquisition_active = False
        self.main.test_session_active = False
        self.main.hp10_complete = False
        self.main.hp007_complete = False
        self.main.reading_type = "PERSONAL_DOSE"
        self.main.dose_channel = "HP10"
        self.main.test_mode = "MANUAL"
        self.main.ids.dosimeter_id_input.text = ""
        self.main._invalidar_dosimetro("Aguardando leitura do código de barras")
        self.main.atualizar_leitoras_cadastradas()

    @classmethod
    def tearDownClass(cls):
        if cls.main.serial_aberta():
            cls.main.desconectar_serial(atualizar_botao=False)
        cls.temporary_directory.cleanup()

    def test_01_visual_mode_switch_and_focus(self):
        self.main.selecionar_modo("DOSIMETER_ID")
        Clock.tick()
        self.assertEqual(self.main.test_mode, "DOSIMETER_ID")
        self.assertEqual(self.main.ids.manual_panel.opacity, 0)
        self.assertEqual(self.main.ids.dosimeter_panel.opacity, 1)
        self.assertTrue(self.main.ids.dosimeter_id_input.focus)
        self.assertTrue(self.main.ids.start_button.disabled)

        self.main.selecionar_modo("MANUAL")
        Clock.tick()
        self.assertEqual(self.main.ids.manual_panel.opacity, 1)
        self.assertEqual(self.main.ids.dosimeter_panel.opacity, 0)
        self.assertFalse(self.main.ids.ecc_textInput.disabled)

    def test_02_barcode_enter_validates_without_starting(self):
        self.main.selecionar_modo("DOSIMETER_ID")
        Clock.tick()
        self.main.ids.reader_spinner.text = "3001A01"
        self.main.ids.dosimeter_id_input.text = "\x020123456789\r\n"
        before = len(self.database.search_measurements())
        self.assertTrue(self.main.confirmar_codigo_dosimetro())
        Clock.tick()
        self.assertEqual(
            len(self.database.search_measurements()),
            before,
            "receber Enter não pode iniciar a aquisição",
        )
        self.assertTrue(self.main.start_allowed)
        self.assertFalse(self.main.ids.start_button.disabled)
        self.assertEqual(self.main.loaded_ecc, "1.25")
        self.assertEqual(self.main.loaded_bc, "100")
        self.assertEqual(self.main.loaded_rcf, "3.3e-05")
        self.assertTrue(
            self.main.automatic_file_name.startswith("0123456789_")
        )
        self.assertTrue(self.main.ids.dosimeter_id_input.focus)

        self.main.ids.dosimeter_id_input.text = "9999999999"
        self.assertFalse(self.main.confirmar_codigo_dosimetro())
        self.assertFalse(self.main.start_allowed)
        self.assertTrue(self.main.ids.start_button.disabled)

    def test_03_database_screen_crud_is_functional(self):
        self.bank.novo_dosimetro()
        self.bank.ids.db_dosimeter_id.text = "9876543210"
        self.bank.ids.db_dosimeter_ecc_hp10.text = "1,5"
        self.bank.ids.db_dosimeter_ecc_hp007.text = "1,7"
        self.bank.ids.db_dosimeter_bc_hp10.text = "150"
        self.bank.ids.db_dosimeter_bc_hp007.text = "170"
        self.bank.ids.db_dosimeter_begin.text = "01/01/2025"
        self.bank.ids.db_dosimeter_end.text = "31/12/2030"
        Clock.tick()
        self.bank.salvar_dosimetro()
        self.assertIn("sucesso", self.bank.dosimeter_message)
        self.assertEqual(
            self.database.get_dosimeter("9876543210")["ecc_hp10"],
            1.5,
        )
        self.assertEqual(
            self.database.get_dosimeter("9876543210")["ecc_hp007"], 1.7
        )
        self.assertEqual(
            self.database.get_dosimeter("9876543210")["bc_hp007"], 170
        )
        self.bank.alternar_dosimetro()
        self.assertFalse(
            self.database.get_dosimeter("9876543210")["active"]
        )

        self.bank.nova_leitora()
        self.bank.ids.db_reader_id.text = "READER-2"
        self.bank.ids.db_reader_rcf.text = "0,5"
        self.bank.ids.db_reader_begin.text = "01/01/2025"
        self.bank.ids.db_reader_end.text = ""
        Clock.tick()
        self.bank.salvar_leitora()
        self.assertIn("sucesso", self.bank.reader_message)
        self.assertEqual(self.database.get_reader("READER-2")["rcf"], 0.5)
        dosimeter_row = self.bank.ids.db_dosimeter_results.children[0]
        reader_row = self.bank.ids.db_reader_results.children[0]
        self.assertEqual(len(dosimeter_row.children), 8)
        self.assertEqual(len(reader_row.children), 5)
        self.assertIsNotNone(dosimeter_row.selection_callback)
        self.assertIsNotNone(reader_row.selection_callback)
        self.assertFalse(
            any("|" in cell.text for cell in dosimeter_row.children)
        )
        self.assertFalse(any("|" in cell.text for cell in reader_row.children))

        self.database.add_personal_dose(
            "0123456789",
            dose_dos=2.387,
        )
        self.database.add_background(
            "0123456789",
            dose_bg=1.912,
        )
        self.bank.pesquisar_doses_pessoais()
        self.bank.pesquisar_backgrounds()
        self.assertEqual(self.bank.personal_dose_count, "1 registros")
        self.assertEqual(self.bank.background_count, "1 registros")
        self.assertEqual(len(self.bank.ids.db_personal_dose_results.children), 1)
        self.assertEqual(len(self.bank.ids.db_background_results.children), 1)
        dataframe = self.bank._montar_dataframe_historico(
            self.database.search_personal_doses(),
            time_column="time_dos",
            hp10_column="hp10_dos",
            hp007_column="hp007_dos",
            status_column="status_dos",
        )
        self.assertEqual(
            list(dataframe.columns),
            [
                "Data/hora", "Dosímetro", "Hp(10) mSv",
                "Hp(0,07) mSv", "Status",
            ],
        )
        rendered_row = self.bank.ids.db_personal_dose_results.children[0]
        self.assertEqual(len(rendered_row.children), 5)
        self.assertFalse(
            any("|" in cell.text for cell in rendered_row.children)
        )

    def test_date_fields_do_not_insert_slashes_automatically(self):
        field = self.bank.ids.db_dosimeter_begin
        field.text = "21"
        Clock.tick()
        self.assertEqual(field.text, "21")
        field.text = "21/08/2026"
        Clock.tick()
        self.assertEqual(field.text, "21/08/2026")

    def test_exact_search_populates_edits_and_deletes_dosimeter(self):
        self.bank.ids.db_dosimeter_id.text = "0123456789"
        self.assertTrue(self.bank.carregar_dosimetro_por_id())
        self.assertEqual(self.bank.ids.db_dosimeter_id.text, "0123456789")
        self.assertEqual(self.bank.ids.db_dosimeter_ecc_hp10.text, "1.25")
        self.assertEqual(self.bank.ids.db_dosimeter_ecc_hp007.text, "1.5")
        self.assertEqual(self.bank.ids.db_dosimeter_bc_hp10.text, "100")
        self.assertEqual(self.bank.ids.db_dosimeter_bc_hp007.text, "200")
        self.assertFalse(self.bank.ids.db_dosimeter_id.disabled)

        self.bank.ids.db_dosimeter_id.text = "9876543210"
        self.bank.ids.db_dosimeter_ecc_hp10.text = "1,3"
        self.bank.ids.db_dosimeter_ecc_hp007.text = "1,6"
        self.bank.ids.db_dosimeter_bc_hp10.text = "110"
        self.bank.ids.db_dosimeter_bc_hp007.text = "210"
        self.bank.ids.db_dosimeter_begin.text = "02/02/2025"
        self.bank.ids.db_dosimeter_end.text = "02/02/2031"
        self.bank.salvar_dosimetro()
        self.assertIn("atualizado", self.bank.dosimeter_message)
        self.assertIsNone(self.database.get_dosimeter("0123456789"))
        edited = self.database.get_dosimeter("9876543210")
        self.assertEqual(edited["ecc_hp10"], 1.3)
        self.assertEqual(edited["bc_hp007"], 210)

        self.database.add_personal_dose(
            "9876543210",
            hp10_dos=1.1,
            hp007_dos=1.2,
        )
        self.assertTrue(
            self.bank._confirmar_exclusao_dosimetro(None, "9876543210")
        )
        self.assertIsNone(self.database.get_dosimeter("9876543210"))
        self.assertEqual(self.database.search_personal_doses(), [])

    def test_exact_search_populates_edits_and_deletes_reader(self):
        self.bank.ids.db_reader_id.text = "3001A01"
        self.assertTrue(self.bank.carregar_leitora_por_id())
        self.assertEqual(self.bank.ids.db_reader_id.text, "3001A01")
        self.assertEqual(self.bank.ids.db_reader_rcf.text, "3.3e-05")
        self.assertEqual(self.bank.ids.db_reader_begin.text, "01/01/2025")
        self.assertFalse(self.bank.ids.db_reader_id.disabled)

        self.bank.ids.db_reader_id.text = "READER-RENAMED"
        self.bank.ids.db_reader_rcf.text = "0,000044"
        self.bank.ids.db_reader_begin.text = "02/02/2025"
        self.bank.ids.db_reader_end.text = "02/02/2031"
        self.bank.salvar_leitora()
        self.assertIn("atualizada", self.bank.reader_message)
        self.assertIsNone(self.database.get_reader("3001A01"))
        edited = self.database.get_reader("READER-RENAMED")
        self.assertEqual(edited["rcf"], 0.000044)

        measurement_id = self.database.add_measurement(
            reader_id="READER-RENAMED",
            dosimeter_id="0123456789",
            test_mode="DOSIMETER_ID",
            reading_type="PERSONAL_DOSE",
            dose_channel="HP10",
            test_session_id="reader-delete-test",
            file_name="reader-delete.txt",
            status="CONCLUIDO",
        )
        self.assertTrue(
            self.bank._confirmar_exclusao_leitora(None, "READER-RENAMED")
        )
        self.assertIsNone(self.database.get_reader("READER-RENAMED"))
        self.assertIsNone(self.database.get_measurement(measurement_id))

    def test_filled_fields_validate_without_enter(self):
        self.main.selecionar_modo("DOSIMETER_ID")
        Clock.tick()
        self.main.ids.reader_spinner.text = "3001A01"
        self.main.ids.dosimeter_id_input.text = "0123456789"
        Clock.tick()

        self.assertTrue(self.main.start_allowed)
        self.assertFalse(self.main.ids.start_button.disabled)
        self.assertIn("pressione Start", self.main.dosimeter_status)

    def test_04_manual_acquisition_preserves_serial_and_history(self):
        self.main.selecionar_modo("MANUAL")
        self.main.serial_connection = FakeSerial()
        self.main.ids.ecc_textInput.text = "1"
        self.main.ids.rcf_textInput.text = "0.000033"
        self.main.ids.fcal_textInput.text = "1"
        self.main.ids.fenerg_textInput.text = "1"
        self.main.ids.branco_textInput.text = "0"
        self.main.ids.nome_arquivo_input.text = "manual-integration"

        self.main.botao_leitura()
        self.assertIsNotNone(self.main.current_measurement_id)
        measurement_id = self.main.current_measurement_id
        self.assertIn(interface_OSL.COMANDOS_SUDO["leitura"].encode("ascii"), self.main.serial_connection.writes)

        self.main.processar_frame("#L1%A1733")
        self.main.processar_frame("#L1%E45")
        self.main.f_fechar_log = True
        self.main.processar_frame("#L1%D471")

        record = self.database.get_measurement(measurement_id)
        self.assertEqual(record["test_mode"], "MANUAL")
        self.assertEqual(record["count_01s"], 1733)
        self.assertEqual(record["current_ma"], 45)
        self.assertEqual(record["light_mv"], 471)
        self.assertAlmostEqual(record["dose_msv"], 1733 * 0.000033)
        self.assertEqual(record["status"], "CONCLUIDO")
        self.assertTrue(Path(record["file_path"]).is_file())
        self.assertIsNone(self.main.current_measurement_id)
        self.bank.pesquisar_historico()
        history_row = self.bank.ids.db_history_results.children[0]
        self.assertEqual(len(history_row.children), 7)
        self.assertFalse(any("|" in cell.text for cell in history_row.children))
        history_row.selection_callback(history_row.record)
        self.assertIn(f"ID {measurement_id}", self.bank.history_details)

    def test_05_dosimeter_mode_uses_database_coefficients(self):
        self.main.selecionar_modo("DOSIMETER_ID")
        self.main.serial_connection = FakeSerial()
        self.main.atualizar_leitoras_cadastradas()
        self.main.ids.reader_spinner.text = "3001A01"
        self.main.ids.dosimeter_id_input.text = "0123456789"
        self.assertTrue(self.main.confirmar_codigo_dosimetro())

        self.main.botao_leitura()
        hp10_measurement_id = self.main.current_measurement_id
        self.assertIsNotNone(hp10_measurement_id)
        self.main.processar_frame("#L1%A1733")
        self.main.processar_frame("#L1%E45")
        self.main.f_fechar_log = True
        self.main.processar_frame("#L1%D471")

        hp10 = self.database.get_measurement(hp10_measurement_id)
        self.assertEqual(hp10["test_mode"], "DOSIMETER_ID")
        self.assertEqual(hp10["dosimeter_id"], "0123456789")
        self.assertEqual(hp10["reader_id"], "3001A01")
        self.assertEqual(hp10["reading_type"], "PERSONAL_DOSE")
        self.assertEqual(hp10["dose_channel"], "HP10")
        self.assertEqual(hp10["ecc_applied"], 1.25)
        self.assertEqual(hp10["baseline_applied"], 100)
        self.assertEqual(hp10["rcf_applied"], 0.000033)
        self.assertAlmostEqual(
            hp10["dose_msv"],
            (1733 - 100) * 0.000033 * 1.25,
        )
        self.assertEqual(self.database.search_personal_doses(), [])
        self.assertTrue(self.main.test_session_active)
        self.assertTrue(self.main.hp10_complete)
        self.assertEqual(self.main.dose_channel, "HP007")
        self.assertEqual(self.main.ids.dosimeter_id_input.text, "0123456789")

        self.main.botao_leitura()
        hp007_measurement_id = self.main.current_measurement_id
        self.assertEqual(
            self.main.ids.hp007_button.text,
            "Lendo Hp(0,07)...",
        )
        self.main.processar_frame("#L1%A2000")
        self.main.processar_frame("#L1%E45")
        self.main.f_fechar_log = True
        self.main.processar_frame("#L1%D471")

        hp007 = self.database.get_measurement(hp007_measurement_id)
        self.assertEqual(hp007["dose_channel"], "HP007")
        self.assertEqual(hp007["ecc_applied"], 1.5)
        self.assertEqual(hp007["baseline_applied"], 200)
        self.assertAlmostEqual(
            hp007["dose_msv"],
            (2000 - 200) * 0.000033 * 1.5,
        )
        history = self.database.search_personal_doses()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["hp10_measurement_id"], hp10_measurement_id)
        self.assertEqual(history[0]["hp007_measurement_id"], hp007_measurement_id)
        self.assertFalse(self.main.test_session_active)
        self.assertEqual(self.main.ids.dosimeter_id_input.text, "")
        Clock.tick()
        self.assertTrue(self.main.ids.dosimeter_id_input.focus)

    def test_052_channel_only_switches_after_completed_reading(self):
        self.main.selecionar_modo("DOSIMETER_ID")
        self.main.serial_connection = FakeSerial()
        self.main.ids.reader_spinner.text = "3001A01"
        self.main.ids.dosimeter_id_input.text = "0123456789"
        self.assertTrue(self.main.confirmar_codigo_dosimetro())

        self.main.botao_leitura()
        self.assertTrue(self.main.acquisition_active)
        self.assertEqual(self.main.ids.hp10_button.text, "Lendo Hp(10)...")
        self.assertIn("Lendo Hp(10)", self.main.dosimeter_status)
        self.assertTrue(self.main.ids.hp007_button.disabled)
        self.assertFalse(self.main.selecionar_grandeza("HP007"))
        self.assertEqual(self.main.dose_channel, "HP10")

        self.main.botao_stop()
        self.assertFalse(self.main.acquisition_active)
        self.assertTrue(self.main.ids.hp007_button.disabled)
        self.assertFalse(self.main.selecionar_grandeza("HP007"))
        self.assertEqual(self.main.dose_channel, "HP10")

        self.main.automatic_file_name = "retry-hp10.txt"
        self.main.botao_leitura()
        self.main.processar_frame("#L1%A1733")
        self.main.processar_frame("#L1%E45")
        self.main.f_fechar_log = True
        self.main.processar_frame("#L1%D471")

        self.assertEqual(self.main.dose_channel, "HP007")
        self.assertTrue(self.main.hp10_complete)
        self.assertEqual(self.main.ids.hp10_button.text, "Hp(10) concluído  ✓")
        self.assertFalse(self.main.ids.hp007_button.disabled)

    def test_055_post_erase_reading_is_saved_as_background(self):
        self.main.selecionar_modo("DOSIMETER_ID")
        self.main.serial_connection = FakeSerial()
        self.main.botao_apagar()
        self.main.ids.reader_spinner.text = "3001A01"
        self.main.ids.dosimeter_id_input.text = "0123456789"
        self.assertTrue(self.main.confirmar_codigo_dosimetro())
        self.main.botao_leitura()
        hp10_measurement_id = self.main.current_measurement_id
        self.assertIsNotNone(hp10_measurement_id)
        self.main.processar_frame("#L1%A1733")
        self.main.processar_frame("#L1%E45")
        self.main.f_fechar_log = True
        self.main.processar_frame("#L1%D471")

        hp10 = self.database.get_measurement(hp10_measurement_id)
        self.assertEqual(hp10["reading_type"], "BACKGROUND")
        self.assertEqual(hp10["dose_channel"], "HP10")
        self.assertIsNone(self.database.get_latest_background("0123456789"))

        self.main.botao_leitura()
        hp007_measurement_id = self.main.current_measurement_id
        self.main.processar_frame("#L1%A1811")
        self.main.processar_frame("#L1%E45")
        self.main.f_fechar_log = True
        self.main.processar_frame("#L1%D471")

        hp007 = self.database.get_measurement(hp007_measurement_id)
        self.assertEqual(hp007["reading_type"], "BACKGROUND")
        self.assertEqual(hp007["dose_channel"], "HP007")
        background = self.database.get_latest_background("0123456789")
        self.assertEqual(background["hp10_measurement_id"], hp10_measurement_id)
        self.assertEqual(
            background["hp007_measurement_id"], hp007_measurement_id
        )
        self.assertEqual(background["hp10_bg"], hp10["dose_msv"])
        self.assertEqual(background["hp007_bg"], hp007["dose_msv"])
        self.assertEqual(self.main.reading_type, "PERSONAL_DOSE")

    def test_06_stop_marks_measurement_as_interrupted(self):
        self.main.selecionar_modo("MANUAL")
        self.main.serial_connection = FakeSerial()
        self.main.ids.nome_arquivo_input.text = "manual-interrupted"
        self.main.ids.branco_textInput.text = "0"
        self.main.botao_leitura()
        measurement_id = self.main.current_measurement_id
        self.main.botao_stop()

        record = self.database.get_measurement(measurement_id)
        self.assertEqual(record["status"], "INTERROMPIDO")
        self.assertIn(
            interface_OSL.COMANDOS_SUDO["stop"].encode("ascii"),
            self.main.serial_connection.writes,
        )


if __name__ == "__main__":
    unittest.main()
