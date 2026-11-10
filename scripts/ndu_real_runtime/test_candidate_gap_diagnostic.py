from copy import deepcopy
import inspect
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from . import candidate_coverage as coverage
from . import candidate_coverage_legacy as legacy
from . import candidate_gap_diagnostic as gap
from . import test_candidate_coverage_legacy as fixtures

CANONICAL = r"""
def canonical(text, field):
    value = unicodedata.normalize("NFKC", text).strip().upper()
    if field == "total":
        value = re.sub(r"\s", "", value).removeprefix("RM").replace(",", "")
        try:
            result = Decimal(value)
            return str(result.normalize()) if result.is_finite() else None
        except InvalidOperation:
            return None
    if field == "date":
        match = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})", value)
        if not match:
            return None
        day, month, year = map(int, match.groups())
        try:
            return date(year + 2000 if year < 100 else year, month, day).isoformat()
        except ValueError:
            return None
    return " ".join(value.split())
"""


def row(text, *, field="total", expected="12.30", source="train", state=0):
    return dict(
        source_group=source,
        candidate_features=[[state] + [0] * 125],
        reference_field=field,
        expected_text=expected,
        candidate_metadata=[dict(text=text, bbox=[0, 0, 2, 2], origin="pixel_ocr")],
    )


class CandidateGapTests(unittest.TestCase):
    def setUp(self):
        self.canonical = legacy.normalizer(CANONICAL.encode())

    def diagnose(self, rows, fit=None):
        return gap.diagnose(
            rows,
            set(fit or [r["source_group"] for r in rows]),
            self.canonical,
            coverage,
        )

    def fixture(self):
        fixture = fixtures.LegacyCoverageTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        normalizer = Path(fixture.pins[0]["path"])
        normalizer.write_text(
            "raise AssertionError('no whole evaluator execution')\n" + CANONICAL
        )
        fixture.pins[0] = fixture.pin(normalizer)
        fixture.plan["normalizer_sha256"] = fixture.pins[0]["sha256"]
        ocr = Path(fixture.config["scripts_root"]) / "ndu_real_runtime/ocr.py"
        ocr.parent.mkdir()
        ocr.write_text(
            f"import re\nDATE = re.compile({gap.DATE!r})\nMONEY = re.compile({gap.MONEY!r}, re.I)\n"
        )
        fixture.pins[1] = fixture.pin(ocr)
        fixture.plan["source_inventory_sha256"] = legacy.sha(
            json.dumps(fixture.pins, sort_keys=True).encode()
        )
        for value in fixture.rows:
            field = (
                "date" if fixture.sources.index(value["source_group"]) < 20 else "total"
            )
            state = int(value["candidate_features"][0][0])
            expected = "02/01/2025" if field == "date" else "12.30"
            text = (
                expected
                if state == 0
                else ("Date: 2025-01-02" if field == "date" else "Pay MYR 12.3")
                if state == 1
                else "UNRESOLVED_PRIVATE_TEXT"
            )
            value.update(reference_field=field, expected_text=expected)
            value["public_metadata"][:4] = [float(f == field) for f in legacy.FIELDS]
            value["candidate_metadata"][0]["text"] = text
        fixture.refresh()
        return fixture

    def execute(self, fixture):
        return gap.execute(
            fixture.request,
            legacy.sha(fixture.request.read_bytes()),
            coverage.__file__,
            legacy.sha(Path(coverage.__file__).read_bytes()),
            legacy.__file__,
            legacy.sha(Path(legacy.__file__).read_bytes()),
            gap.LOADED_SHA256,
            fixture.root / "gap-output",
        )

    def test_proposals_are_target_free_and_ambiguous_formats_are_not_repaired(self):
        original = row("Pay MYR 12.3")
        first = gap.propose(original["candidate_metadata"], "total")
        original["expected_text"] = "999"
        self.assertEqual(first, gap.propose(original["candidate_metadata"], "total"))
        self.assertEqual(
            list(inspect.signature(gap.propose).parameters), ["candidates", "field"]
        )
        with self.assertRaises(TypeError):
            gap.propose(original["candidate_metadata"], "total", expected_text="12.30")
        with self.assertRaises(ValueError):
            gap.propose(
                [{**original["candidate_metadata"][0], "expected_text": "12.30"}],
                "total",
            )
        for value in (
            row("Total 12,30"),
            row("01/02/2025", field="date", expected="02/01/2025"),
        ):
            result = self.diagnose([value])["overall"]
            self.assertEqual(result["categories"]["D_evidence_insufficient"], 1)
            self.assertIsNone(result["unavailable_observation_states"])

    def test_fixed_lexical_numeric_rules_and_priority(self):
        rows = [
            row("Subtotal RM 12.30", source="a"),
            row(
                "Date: ２０２５ - ０１ - ０２",
                field="date",
                expected="02/01/2025",
                source="b",
            ),
            row("Pay MYR 12.3", source="c"),
            row("Total RM 12", expected="12.00", source="d"),
            row("Total RM 12.300", source="e"),
            row("RM 12.30 | MYR 12.3", source="f"),
        ]
        result = self.diagnose(rows)["overall"]
        self.assertEqual(result["categories"]["A_frozen_regex"], 2)
        self.assertEqual(result["categories"]["B_numeric_format"], 4)
        self.assertEqual(result["source_equal_probe_candidate_availability"], 1.0)
        self.assertGreaterEqual(result["A_and_B_retained_match_states"], 1)

    def test_cross_state_evidence_is_same_source_same_field_and_not_gain(self):
        rows = [
            row("no numeric text", source="a"),
            row("12.30", source="a", state=1),
            row("no numeric text", source="b"),
            row("not a date", field="date", expected="01/01/2025", source="c"),
        ]
        result = self.diagnose(rows)["overall"]
        self.assertEqual(result["categories"]["C_other_recorded_state"], 1)
        self.assertEqual(result["categories"]["D_evidence_insufficient"], 2)
        self.assertEqual(
            result["source_equal_probe_candidate_availability"],
            result["source_equal_original_coverage"],
        )
        self.assertIsNone(result["selected_accuracy"])

    def test_duplicates_unknown_reference_and_missing_field_denominators(self):
        original = row("12.30")
        result = self.diagnose([original, deepcopy(original)], {"train", "missing"})
        self.assertEqual(result["overall"]["unique_states"], 1)
        self.assertEqual(result["by_reference_field"]["date"]["missing_sources"], 2)
        self.assertIsNone(result["overall"]["source_equal_original_coverage"])
        bad = deepcopy(original)
        bad["expected_text"] = "999"
        with self.assertRaisesRegex(ValueError, "GAP_DUPLICATE_STATE_CONFLICT"):
            self.diagnose([original, bad])
        bad["candidate_features"][0][0] = 1
        with self.assertRaisesRegex(ValueError, "GAP_SOURCE_FIELD_REFERENCE_CONFLICT"):
            self.diagnose([original, bad])
        unknown = self.diagnose([row("2025-01-02", field="date", expected="invalid")])[
            "overall"
        ]
        self.assertEqual(unknown["categories"]["unknown_reference"], 1)
        self.assertIsNone(unknown["source_equal_probe_candidate_availability"])

    def test_caps_and_scan_censoring_do_not_claim_unavailability(self):
        value = row("TOTAL MYR 12.3")
        value["candidate_metadata"] += [
            dict(text=f"unrelated {i}", bbox=[0, 0, 2, 2], origin="pixel_ocr")
            for i in range(127)
        ]
        kept, counts = gap.propose(value["candidate_metadata"], "total")
        self.assertEqual(kept, [])
        self.assertGreater(counts["known_dropped_by_candidate_cap"], 0)
        result = self.diagnose([value])["overall"]
        self.assertEqual(result["D_with_budget_censoring"], 1)
        self.assertIsNone(result["unavailable_observation_states"])
        many = row(" ".join(str(i) for i in range(200)))
        kept, counts = gap.propose(many["candidate_metadata"], "total")
        self.assertEqual(len(kept), 64)
        self.assertEqual(counts["known_dropped_by_proposal_limit"], 136)
        candidates = [
            dict(
                text=" ".join("1.00" for _ in range(1000)),
                bbox=[0, i, 2, i + 1],
                origin="pixel_ocr",
            )
            for i in range(5)
        ]
        _, counts = gap.propose(candidates, "total")
        self.assertEqual(counts["scanned_matches"], 4096)
        self.assertEqual(counts["scan_censored"], 1)

    def test_pinned_cli_keeps_text_private_and_dataset_unchanged(self):
        fixture = self.fixture()
        original = fixture.data.read_bytes()
        command = [sys.executable, gap.__file__]
        for key, value in dict(
            request=fixture.request,
            request_sha256=legacy.sha(fixture.request.read_bytes()),
            coverage_source=coverage.__file__,
            coverage_source_sha256=legacy.sha(Path(coverage.__file__).read_bytes()),
            legacy_source=legacy.__file__,
            legacy_source_sha256=legacy.sha(Path(legacy.__file__).read_bytes()),
            diagnostic_sha256=gap.LOADED_SHA256,
            output=fixture.root / "gap-output",
        ).items():
            command.extend(["--" + key.replace("_", "-"), str(value)])
        completed = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        result = json.loads((fixture.root / "gap-output/RESULT.json").read_text())
        self.assertEqual(result["unique_states"], 160)
        self.assertEqual(result["overall"]["categories"]["B_numeric_format"], 40)
        self.assertEqual(result["overall"]["categories"]["C_other_recorded_state"], 80)
        self.assertFalse(result["historical_producer_identity_authenticated"])
        self.assertEqual(result["execution"]["legacy_validation_rounds"], 2)
        for path in (fixture.root / "gap-output").rglob("*.json"):
            raw = path.read_bytes()
            for private in (
                b"private-source",
                b"UNRESOLVED_PRIVATE_TEXT",
                b"Date:",
                str(fixture.root).encode(),
            ):
                self.assertNotIn(private, raw)
        self.assertEqual(fixture.data.read_bytes(), original)
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)

    def test_after_probe_source_drift_blocks_final_report(self):
        fixture = self.fixture()
        original_diagnose = gap.diagnose

        def drift(*args):
            result = original_diagnose(*args)
            Path(fixture.pins[-1]["path"]).write_text("changed after probes")
            return result

        with patch.object(gap, "diagnose", side_effect=drift):
            with self.assertRaisesRegex(ValueError, "LEGACY_INPUT_PIN_MISMATCH"):
                self.execute(fixture)
        self.assertFalse((fixture.root / "gap-output/RESULT.json").exists())

    def test_frozen_lexer_and_execution_source_pins_are_required(self):
        raw = f"DATE = re.compile({gap.DATE!r})\nMONEY = re.compile({gap.MONEY!r}, re.I)\n".encode()
        gap.verify_lexers(raw)
        with self.assertRaisesRegex(ValueError, "GAP_FROZEN_LEXER_MISMATCH"):
            gap.verify_lexers(raw.replace(b"MONEY =", b"OTHER ="))
        fixture = self.fixture()
        with self.assertRaisesRegex(ValueError, "GAP_FRESH_WORKER_REQUIRED"):
            gap.execute(
                fixture.request,
                "0" * 64,
                coverage.__file__,
                "0" * 64,
                legacy.__file__,
                "0" * 64,
                "0" * 64,
                fixture.root / "never",
            )
        self.assertFalse((fixture.root / "never").exists())


if __name__ == "__main__":
    unittest.main()
