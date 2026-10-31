"""Boundary tests; no models, training or experiment outcomes are read."""

import importlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

fixture = importlib.import_module(f"{__package__}.terminal_fixture" if __package__ else "terminal_fixture")


class TerminalFixtureTests(unittest.TestCase):
    def test_q32_binary64_half_grid_and_neighbors(self):
        # Decimal(str(binary64)) rounds the first value to 1 rather than 2.
        # The producer and native consumer must agree on original binary64.
        cases = [(3 * 2**-33, 2), (-3 * 2**-33, -2),
                 (5 * 2**-33, 2), (-5 * 2**-33, -2),
                 (1., 2**32), (-1., -2**32), (0., 0)]
        for value, expected in cases:
            with self.subTest(value=value):
                parsed = json.loads(json.dumps(value))
                self.assertEqual(fixture.utility_q32(parsed), expected)
        middle = 3 * 2**-33
        self.assertEqual(fixture.utility_q32(math.nextafter(middle, 0)), 1)
        self.assertEqual(fixture.utility_q32(math.nextafter(middle, 1)), 2)
        for value in [math.nan, math.inf, -math.inf, 1.01, True]:
            with self.assertRaises(ValueError):
                fixture.utility_q32(value)

    def test_unfinished_status_rejects_before_outcome_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "status.json").write_text('{"state":"running","rows":0}')
            with patch.object(fixture, "checked_read", wraps=fixture.checked_read) as reads:
                with self.assertRaisesRegex(ValueError, "not completed"):
                    fixture.export_fixture(source, root / "export.json")
                self.assertEqual([call.args[1] for call in reads.call_args_list], ["status.json"])
            self.assertFalse((root / "export.json").exists())

    def test_completed_summary_cannot_authenticate_replaced_protocol_or_census(self):
        for changed_protocol, changed_census in [(True, False), (False, True)]:
            with self.subTest(protocol=changed_protocol, census=changed_census):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    source = root / "source"
                    source.mkdir()
                    protocol = {"registered": "original"}
                    summary = {"protocol_sha256": fixture.sha(fixture.canonical(protocol).encode()),
                               "rows": 2 if changed_census else 1}
                    status = {"state": "completed", "rows": 1,
                              "summary_sha256": fixture.sha(fixture.canonical(summary).encode())}
                    if changed_protocol:
                        protocol["registered"] = "replaced"
                    for name, value in [("status", status), ("summary", summary), ("protocol", protocol)]:
                        (source / f"{name}.json").write_text(fixture.canonical(value))
                    # The rows cannot be parsed; identity must reject first.
                    (source / "rows.jsonl").write_text("not valid JSON")
                    with self.assertRaisesRegex(ValueError, "protocol/summary/census"):
                        fixture.export_fixture(source, root / "export.json")
                    self.assertFalse((root / "export.json").exists())


if __name__ == "__main__":
    unittest.main()
