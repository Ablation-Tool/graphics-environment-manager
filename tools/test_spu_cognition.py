from __future__ import annotations

import unittest

from gem.spu_cognition import LocalStore, SPUExecutionField, local_store_address


class SPUExecutionCase(unittest.TestCase):
    def test_local_store_addressing_and_quadwords(self):
        self.assertEqual(local_store_address(1, 0x1000), 0x1010)
        self.assertEqual(local_store_address(-2, 0x1000), 0x0FE0)
        self.assertEqual(local_store_address(2, 0x1003), 0x1020)
        store = LocalStore(32)
        store.write_quadword(16, bytes(range(16)))
        self.assertEqual(store.read_quadword(16), bytes(range(16)))
        with self.assertRaisesRegex(ValueError, "outside"):
            store.read_quadword(17)
        with self.assertRaisesRegex(ValueError, "signed 10-bit"):
            local_store_address(512, 0)

    def test_decode_timing_and_execution_path(self):
        field = SPUExecutionField.from_words([
            (0x3050, 0x4206D803),
            (0x3054, 0x34000000),
            (0x3058, 0x24000000),
            (0x305C, 0x00000000),
        ])
        report = field.report()
        self.assertEqual(report["instruction_count"], 4)
        self.assertEqual(report["execution_imagery"]["path"]["path"], [0x3050, 0x3054, 0x3058, 0x305C])
        self.assertAlmostEqual(report["execution_imagery"]["path"]["cost"], 14)
        self.assertAlmostEqual(report["timing"]["known_ratio"], .75)
        self.assertIn("not observed execution", report["provenance"])
        self.assertEqual(report["source"]["kind"], "instruction_words")


if __name__ == "__main__":
    unittest.main()
