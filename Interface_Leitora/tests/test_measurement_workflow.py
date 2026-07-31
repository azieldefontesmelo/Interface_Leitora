from __future__ import annotations

import unittest
from datetime import datetime

from measurement_workflow import (
    calculate_dose,
    dosimeter_filename,
    safe_test_filename,
    scanner_text,
)


class MeasurementWorkflowTestCase(unittest.TestCase):
    def test_scanner_control_characters_are_removed_without_changing_digits(self):
        self.assertEqual(scanner_text("\x020123456789\r\n"), "0123456789")
        self.assertEqual(scanner_text("01234 56789\t"), "0123456789")

    def test_safe_filename(self):
        self.assertEqual(safe_test_filename(" leitura 01 "), "leitura 01.txt")
        for value in ("../escape.txt", r"C:\escape.txt", "bad?.txt", "CON.txt"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    safe_test_filename(value)

    def test_dosimeter_filename(self):
        self.assertEqual(
            dosimeter_filename(
                "0123456789",
                datetime(2026, 7, 30, 12, 34, 56),
            ),
            "0123456789_2026-07-30_12-34-56.txt",
        )

    def test_preserves_dose_formula(self):
        self.assertEqual(
            calculate_dose(
                20,
                baseline=2,
                rcf=3,
                ecc=4,
                fang=5,
                fenerg=6,
            ),
            (20 - 2) * 3 * 4 * 5 * 6,
        )


if __name__ == "__main__":
    unittest.main()
