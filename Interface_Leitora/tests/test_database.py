from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from database import (
    BACKGROUND_COLUMNS,
    BACKGROUND_STATUS,
    Database,
    MEASUREMENT_COLUMNS,
    PERSONAL_DOSE_COLUMNS,
    PERSONAL_DOSE_STATUS,
    SCHEMA_VERSION,
)


class DatabaseTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.db_path = self.root / "nested" / "measurements.sqlite3"
        self.database = Database(self.db_path)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def register_valid_records(self) -> None:
        self.database.register_dosimeter(
            "0123456789",
            ecc=1.25,
            begin_date="2025-01-01",
            end_date="2030-12-31",
        )
        self.database.register_reader(
            "3001A01",
            rcf=0.000033,
            begin_date="2025-01-01",
            end_date=None,
        )

    def add_valid_measurement(self, **changes):
        values = {
            "reader_id": "3001A01",
            "dosimeter_id": "0123456789",
            "test_mode": "DOSIMETER_ID",
            "file_name": "0123456789_2026-07-30_12-00-00.txt",
            "file_path": "assets/testes/2026/07/30/example.txt",
            "count_01s": 1733,
            "current_ma": 45,
            "light_mv": 471,
            "dose_msv": 474246,
            "ecc_applied": 1.25,
            "rcf_applied": 0.000033,
            "fang_applied": 1,
            "fenerg_applied": 1,
            "baseline_applied": 0,
            "measured_at": "2026-07-30T12:00:00Z",
            "status": "CONCLUIDO",
        }
        values.update(changes)
        return self.database.add_measurement(**values)

    def test_creates_database_and_idempotent_versioned_schema(self):
        self.assertTrue(self.db_path.is_file())
        Database(self.db_path)
        with self.database.connect() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(measurements)")
            }
            dose_history_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(historico_dose)"
                )
            }
            background_history_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(historico_branco)"
                )
            }
        self.assertTrue(
            {
                "dosimeters",
                "readers",
                "measurements",
                "historico_dose",
                "historico_branco",
            }
            <= tables
        )
        self.assertEqual(version, SCHEMA_VERSION)
        self.assertEqual(foreign_keys, 1)
        self.assertEqual(journal_mode.lower(), "wal")
        self.assertFalse(any(column.lower().startswith("hp") for column in columns))
        self.assertNotIn("dose_channel", columns)
        self.assertIn("dose_dos", dose_history_columns)
        self.assertIn("dose_bg", background_history_columns)
        self.assertFalse(
            any(column.lower().startswith("hp") for column in dose_history_columns)
        )
        self.assertFalse(
            any(
                column.lower().startswith("hp")
                for column in background_history_columns
            )
        )

    def test_dosimeter_crud_preserves_leading_zero(self):
        self.database.register_dosimeter(
            "0123456789",
            ecc=1.2,
            begin_date="01/01/2025",
            end_date="31/12/2030",
        )
        record = self.database.get_dosimeter("0123456789")
        self.assertEqual(record["dosimeter_id"], "0123456789")
        self.assertEqual(record["ecc"], 1.2)
        self.assertTrue(
            self.database.update_dosimeter(
                "0123456789",
                ecc=1.4,
                begin_date="2025-01-01",
                end_date="2030-12-31",
                active=True,
            )
        )
        self.assertEqual(
            self.database.get_valid_dosimeter_for_test(
                "0123456789",
                at_date="2026-07-30",
            )["ecc"],
            1.4,
        )
        self.database.set_dosimeter_active("0123456789", False)
        with self.assertRaisesRegex(ValueError, "inativo"):
            self.database.get_valid_dosimeter_for_test(
                "0123456789",
                at_date="2026-07-30",
            )

    def test_invalid_or_duplicate_dosimeter_is_rejected(self):
        for invalid_id in ("123", "12345678901", "12345A7890", "１２３４５６７８９０"):
            with self.subTest(invalid_id=invalid_id):
                with self.assertRaises(ValueError):
                    self.database.register_dosimeter(
                        invalid_id,
                        ecc=1,
                        begin_date="2025-01-01",
                        end_date="2030-12-31",
                    )
        self.database.register_dosimeter(
            "1234567890",
            ecc=1,
            begin_date="2025-01-01",
            end_date="2030-12-31",
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.database.register_dosimeter(
                "1234567890",
                ecc=1,
                begin_date="2025-01-01",
                end_date="2030-12-31",
            )
        with self.assertRaisesRegex(ValueError, "ECC"):
            self.database.register_dosimeter(
                "9876543210",
                ecc=0,
                begin_date="2025-01-01",
                end_date="2030-12-31",
            )

    def test_dates_and_reader_validation(self):
        with self.assertRaisesRegex(ValueError, "data"):
            self.database.register_reader(
                "R1",
                rcf=1,
                begin_date="not-a-date",
            )
        with self.assertRaisesRegex(ValueError, "anterior"):
            self.database.register_reader(
                "R1",
                rcf=1,
                begin_date="2026-02-01",
                end_date="2026-01-01",
            )
        with self.assertRaisesRegex(ValueError, "RCF"):
            self.database.register_reader(
                "R1",
                rcf=-1,
                begin_date="2025-01-01",
            )
        self.database.register_reader(
            "R1",
            rcf=2,
            begin_date="2026-01-01",
            end_date="2026-01-31",
        )
        with self.assertRaisesRegex(ValueError, "validade"):
            self.database.get_valid_reader_for_test(
                "R1",
                at_date="2026-02-01",
            )
        self.database.set_reader_active("R1", False)
        with self.assertRaisesRegex(ValueError, "inativa"):
            self.database.get_valid_reader_for_test(
                "R1",
                at_date="2026-01-15",
            )

    def test_connection_rolls_back_and_data_persists_when_reopened(self):
        try:
            with self.database.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO readers (
                        reader_id, rcf, begin_date, end_date, active,
                        created_at, updated_at
                    )
                    VALUES ('ROLLBACK', 1, '2025-01-01', NULL, 1, 'x', 'x')
                    """
                )
                raise RuntimeError("force rollback")
        except RuntimeError:
            pass
        self.assertIsNone(self.database.get_reader("ROLLBACK"))

        self.register_valid_records()
        reopened = Database(self.db_path)
        self.assertEqual(reopened.get_reader("3001A01")["rcf"], 0.000033)
        self.assertEqual(
            reopened.get_dosimeter("0123456789")["dosimeter_id"],
            "0123456789",
        )

    def test_measurement_exact_values_and_immutable_parameter_snapshot(self):
        self.register_valid_records()
        measurement_id = self.add_valid_measurement()
        measurement = self.database.get_measurement(measurement_id)
        self.assertEqual(measurement["count_01s"], 1733)
        self.assertEqual(measurement["current_ma"], 45)
        self.assertEqual(measurement["light_mv"], 471)
        self.assertEqual(measurement["dose_msv"], 474246)
        self.assertEqual(measurement["ecc_applied"], 1.25)
        self.assertEqual(measurement["rcf_applied"], 0.000033)

        self.database.update_dosimeter(
            "0123456789",
            ecc=9,
            begin_date="2025-01-01",
            end_date="2030-12-31",
            active=True,
        )
        self.database.update_reader(
            "3001A01",
            rcf=8,
            begin_date="2025-01-01",
            end_date=None,
            active=True,
        )
        unchanged = self.database.get_measurement(measurement_id)
        self.assertEqual(unchanged["ecc_applied"], 1.25)
        self.assertEqual(unchanged["rcf_applied"], 0.000033)

    def test_in_progress_measurement_can_be_completed(self):
        measurement_id = self.database.add_measurement(
            test_mode="MANUAL",
            file_name="manual.txt",
            ecc_applied=1,
            rcf_applied=0.1,
            fang_applied=1,
            fenerg_applied=1,
            baseline_applied=0,
        )
        self.assertTrue(
            self.database.update_measurement(
                measurement_id,
                count_01s=1733,
                current_ma=45,
                light_mv=471,
                dose_msv=474246,
                status="CONCLUIDO",
            )
        )
        self.assertEqual(
            self.database.get_measurement(measurement_id)["status"],
            "CONCLUIDO",
        )

    def test_history_filters_csv_and_backup(self):
        self.register_valid_records()
        wanted_id = self.add_valid_measurement()
        self.database.add_measurement(
            test_mode="MANUAL",
            file_name="manual.txt",
            count_01s=1,
            current_ma=2,
            light_mv=3,
            dose_msv=4,
            ecc_applied=1,
            rcf_applied=1,
            fang_applied=1,
            fenerg_applied=1,
            baseline_applied=0,
            measured_at="2026-08-01T12:00:00Z",
            status="CONCLUIDO",
        )

        rows = self.database.search_measurements(
            dosimeter_id="0123456789",
            reader_id="3001A01",
            test_mode="DOSIMETER_ID",
            date_from="30/07/2026",
            date_to="30/07/2026",
        )
        self.assertEqual([row["id"] for row in rows], [wanted_id])

        csv_path = self.database.export_csv(self.root / "exports" / "history.csv", rows)
        with csv_path.open(encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            self.assertEqual(tuple(reader.fieldnames), MEASUREMENT_COLUMNS)
            exported = list(reader)
        self.assertEqual(exported[0]["count_01s"], "1733")

        backup_path = self.database.backup(
            self.root / "backups" / "measurements.sqlite3"
        )
        self.assertTrue(backup_path.is_file())
        backup_database = Database(backup_path)
        self.assertEqual(
            len(backup_database.search_measurements(limit=100)),
            2,
        )

    def test_import_database_validates_replaces_and_backs_up_current_data(self):
        self.register_valid_records()
        self.add_valid_measurement()

        imported_path = self.root / "imports" / "incoming.sqlite3"
        imported = Database(imported_path)
        imported.register_dosimeter(
            "9999999999",
            ecc=1.1,
            begin_date="2025-01-01",
            end_date="2030-12-31",
        )
        imported.register_reader(
            "IMPORTED",
            rcf=0.00004,
            begin_date="2025-01-01",
        )
        imported_measurement = imported.add_measurement(
            reader_id="IMPORTED",
            dosimeter_id="9999999999",
            test_mode="DOSIMETER_ID",
            reading_type="PERSONAL_DOSE",
            file_name="imported.txt",
            count_01s=100,
            dose_msv=0.0044,
            ecc_applied=1.1,
            rcf_applied=0.00004,
            fang_applied=1,
            fenerg_applied=1,
            baseline_applied=0,
            status="CONCLUIDO",
        )
        imported.sync_measurement_history(imported_measurement)

        result = self.database.import_database(imported_path)

        self.assertEqual(result["source"], imported_path.resolve())
        self.assertEqual(result["schema_version"], SCHEMA_VERSION)
        self.assertTrue(result["backup"].is_file())
        self.assertIsNone(self.database.get_dosimeter("0123456789"))
        self.assertIsNotNone(self.database.get_dosimeter("9999999999"))
        self.assertEqual(
            self.database.search_personal_doses()[0]["dose_dos"],
            0.0044,
        )

        previous_database = Database(result["backup"])
        self.assertIsNotNone(previous_database.get_dosimeter("0123456789"))
        self.assertIsNone(previous_database.get_dosimeter("9999999999"))

    def test_import_database_rejects_incompatible_file_without_data_loss(self):
        self.register_valid_records()
        invalid_path = self.root / "imports" / "invalid.sqlite3"
        invalid_path.parent.mkdir(parents=True, exist_ok=True)
        invalid = sqlite3.connect(invalid_path)
        try:
            invalid.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
            invalid.commit()
        finally:
            invalid.close()

        with self.assertRaisesRegex(ValueError, "tabelas ausentes"):
            self.database.import_database(invalid_path)

        self.assertIsNotNone(self.database.get_dosimeter("0123456789"))

    def test_personal_dose_and_background_are_separate_histories(self):
        self.register_valid_records()
        personal_id = self.database.add_personal_dose(
            "0123456789",
            dose_dos=2.387,
            time_dos="2026-07-29T10:00:00Z",
        )
        older_background_id = self.database.add_background(
            "0123456789",
            dose_bg=1.912,
            time_bg="2026-07-28T10:00:00Z",
        )
        latest_background_id = self.database.add_background(
            "0123456789",
            dose_bg=2.001,
            time_bg="2026-07-30T10:00:00Z",
        )

        personal = self.database.get_personal_dose(personal_id)
        self.assertEqual(personal["status_dos"], PERSONAL_DOSE_STATUS)
        self.assertEqual(personal["dose_dos"], 2.387)
        self.assertEqual(
            [row["id"] for row in self.database.search_personal_doses()],
            [personal_id],
        )

        latest = self.database.get_latest_background("0123456789")
        self.assertEqual(latest["id"], latest_background_id)
        self.assertEqual(latest["status_bg"], BACKGROUND_STATUS)
        historical = self.database.get_latest_background(
            "0123456789",
            at_time="2026-07-29T00:00:00Z",
        )
        self.assertEqual(historical["id"], older_background_id)
        self.assertEqual(
            self.database.get_background_value("0123456789"),
            2.001,
        )
        calculated = self.database.calculate_net_personal_dose(
            "0123456789",
            "3001A01",
            dose_reading=2.387,
            measured_at="2026-07-31T10:00:00Z",
        )
        self.assertAlmostEqual(
            calculated["dose_msv"],
            2.387 - 2.001,
        )
        self.assertEqual(calculated["background_msv"], 2.001)

        with self.database.connect() as connection:
            dose_count = connection.execute(
                "SELECT count(*) FROM historico_dose"
            ).fetchone()[0]
            background_count = connection.execute(
                "SELECT count(*) FROM historico_branco"
            ).fetchone()[0]
        self.assertEqual(dose_count, 1)
        self.assertEqual(background_count, 2)

    def test_completed_acquisitions_sync_to_the_selected_history(self):
        self.register_valid_records()
        personal_measurement_id = self.add_valid_measurement(
            raw_signal=42000,
            reading_type="PERSONAL_DOSE",
        )
        first_sync = self.database.sync_measurement_history(
            personal_measurement_id
        )
        second_sync = self.database.sync_measurement_history(
            personal_measurement_id
        )
        self.assertEqual(first_sync["id"], second_sync["id"])
        self.assertEqual(first_sync["measurement_id"], personal_measurement_id)
        self.assertEqual(first_sync["dose_dos"], 474246)

        background_measurement_id = self.add_valid_measurement(
            file_name="background.txt",
            measured_at="2026-07-30T13:00:00Z",
            raw_signal=1811,
            reading_type="BACKGROUND",
        )
        background = self.database.sync_measurement_history(
            background_measurement_id
        )
        self.assertEqual(background["measurement_id"], background_measurement_id)
        self.assertEqual(background["dose_bg"], 474246)
        self.assertEqual(len(self.database.search_personal_doses()), 1)
        self.assertEqual(len(self.database.search_backgrounds()), 1)

    def test_background_default_validation_and_specific_csv_exports(self):
        self.register_valid_records()
        self.assertEqual(
            self.database.get_background_value("0123456789"),
            0.0,
        )
        with self.assertRaisesRegex(ValueError, "status_dos"):
            self.database.add_personal_dose(
                "0123456789",
                dose_dos=1,
                status_dos="Ready to Use",
            )
        with self.assertRaisesRegex(ValueError, "não pode ser negativo"):
            self.database.add_background(
                "0123456789",
                dose_bg=-1,
            )

        self.database.add_personal_dose(
            "0123456789",
            dose_dos=10,
            time_dos="2026-07-29T10:00:00Z",
        )
        self.database.add_background(
            "0123456789",
            dose_bg=3,
            time_bg="2026-07-29T11:00:00Z",
        )
        dose_csv = self.database.export_personal_doses_csv(
            self.root / "exports" / "personal.csv"
        )
        background_csv = self.database.export_backgrounds_csv(
            self.root / "exports" / "background.csv"
        )
        with dose_csv.open(encoding="utf-8-sig", newline="") as file:
            self.assertEqual(tuple(csv.DictReader(file).fieldnames), PERSONAL_DOSE_COLUMNS)
        with background_csv.open(encoding="utf-8-sig", newline="") as file:
            self.assertEqual(tuple(csv.DictReader(file).fieldnames), BACKGROUND_COLUMNS)

    def test_version_one_database_is_upgraded_without_losing_measurements(self):
        self.register_valid_records()
        measurement_id = self.add_valid_measurement()
        with self.database.connect() as connection:
            connection.execute("DROP TABLE historico_dose")
            connection.execute("DROP TABLE historico_branco")
            connection.execute(
                "ALTER TABLE measurements ADD COLUMN dose_channel TEXT"
            )
            connection.execute(
                "UPDATE measurements SET dose_channel = 'legacy'"
            )
            connection.execute("DELETE FROM schema_versions WHERE version > 1")
            connection.execute("PRAGMA user_version = 1")

        upgraded = Database(self.db_path)
        self.assertIsNotNone(upgraded.get_measurement(measurement_id))
        self.assertEqual(
            upgraded.get_measurement(measurement_id)["reading_type"],
            "PERSONAL_DOSE",
        )
        self.assertEqual(len(upgraded.search_personal_doses()), 1)
        with upgraded.connect() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            measurement_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(measurements)")
            }
        self.assertIn("historico_dose", tables)
        self.assertIn("historico_branco", tables)
        self.assertEqual(version, SCHEMA_VERSION)
        self.assertNotIn("dose_channel", measurement_columns)

    def test_foreign_keys_prevent_history_loss(self):
        self.register_valid_records()
        self.add_valid_measurement()
        with self.assertRaises(sqlite3.IntegrityError):
            self.database.delete_dosimeter("0123456789")
        with self.assertRaises(sqlite3.IntegrityError):
            self.database.delete_reader("3001A01")


if __name__ == "__main__":
    unittest.main()
