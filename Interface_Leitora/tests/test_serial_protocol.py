from __future__ import annotations

import unittest

from serial_protocol import SerialFrameDecoder


class SerialFrameDecoderTestCase(unittest.TestCase):
    def test_preserves_fragmented_frame(self):
        decoder = SerialFrameDecoder()

        self.assertEqual(decoder.feed(b"#L1%A17"), [])
        self.assertEqual(
            decoder.feed(b"33&#L1%E45&"),
            [b"#L1%A1733", b"#L1%E45"],
        )
        self.assertEqual(decoder.pending_size, 0)

    def test_returns_all_frames_from_one_usb_read(self):
        decoder = SerialFrameDecoder()

        self.assertEqual(
            decoder.feed(b"#L1%A1733&#L1%E45&#L1%T1&#L1%D471&"),
            [b"#L1%A1733", b"#L1%E45", b"#L1%T1", b"#L1%D471"],
        )

    def test_ignores_empty_frames_and_keeps_pending_bytes(self):
        decoder = SerialFrameDecoder()

        self.assertEqual(decoder.feed(b"&&#L1%A1"), [])
        self.assertEqual(decoder.pending_size, len(b"#L1%A1"))
        self.assertEqual(decoder.feed(b"&"), [b"#L1%A1"])

    def test_limits_unterminated_noise(self):
        decoder = SerialFrameDecoder(max_buffer_size=8)

        self.assertEqual(decoder.feed(b"noise-no-terminator"), [])
        self.assertLessEqual(decoder.pending_size, 8)
        self.assertGreater(decoder.discarded_bytes, 0)


if __name__ == "__main__":
    unittest.main()
