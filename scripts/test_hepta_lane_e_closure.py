#!/usr/bin/env python3
"""Adversarial regressions for Lane E's source and product-write checks."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "lane_e_closure_regression", SCRIPTS / "hepta-lane-e-closure.py"
)
assert SPEC and SPEC.loader
LANE_E = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LANE_E
SPEC.loader.exec_module(LANE_E)


class LaneEClosedWorldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.matrix = json.loads(LANE_E.MATRIX_PATH.read_text())
        self.trace = json.loads(LANE_E.TRACE_PATH.read_text())

    def verify(self, matrix=None, trace=None):
        findings = LANE_E.Findings()
        modules = LANE_E.verify_matrix(matrix or self.matrix, findings)
        LANE_E.verify_traceability(trace or self.trace, modules, findings)
        return {finding.code for finding in findings.items}

    def test_registered_signed_dataset_operations_and_cases_are_current(self):
        self.assertEqual(self.verify(), set())
        self.assertIn(
            "fit_transition_model_verified_v2",
            LANE_E.EXPECTED_OPERATIONS["learning.operator"],
        )
        self.assertIn("OP-06", LANE_E.EXPECTED_CASES)

    def test_missing_unknown_and_duplicate_operations_remain_rejected(self):
        for mutation in ("missing", "unknown", "duplicate"):
            matrix = copy.deepcopy(self.matrix)
            operations = matrix["modules"][0]["operations"]
            if mutation == "missing":
                operations.pop()
            else:
                operation = copy.deepcopy(operations[0])
                if mutation == "unknown":
                    operation["operation"] = "unregistered_operation"
                operations.append(operation)
            with self.subTest(mutation=mutation):
                expected = (
                    "duplicate_operation"
                    if mutation == "duplicate"
                    else "operation_closed_world"
                )
                self.assertIn(expected, self.verify(matrix))

    def test_missing_unknown_and_duplicate_cases_remain_rejected(self):
        for mutation in ("missing", "unknown", "duplicate"):
            trace = copy.deepcopy(self.trace)
            if mutation == "missing":
                trace["cases"].pop()
            else:
                case = copy.deepcopy(trace["cases"][0])
                if mutation == "unknown":
                    case["id"] = "OP-UNKNOWN"
                trace["cases"].append(case)
            with self.subTest(mutation=mutation):
                expected = (
                    "duplicate_case" if mutation == "duplicate" else "case_closed_world"
                )
                self.assertIn(expected, self.verify(trace=trace))

    def test_foreign_and_ambiguous_source_owners_remain_rejected(self):
        matrix = copy.deepcopy(self.matrix)
        matrix["modules"][0]["operations"][0]["source"] = (
            "codex-rs/hepta-agentd/src/lib.rs"
        )
        self.assertIn("canonical_operation_owner", self.verify(matrix))
        rows = LANE_E.load_module_registry(LANE_E.ROOT / "docs/modules/MODULES.json")
        rows = copy.deepcopy(rows)
        rows.append(
            {
                "id": "unknown.second-owner",
                "rootBindings": [{"path": "codex-rs/hepta-learning-ledger"}],
            }
        )
        with mock.patch.object(LANE_E, "load_module_registry", return_value=rows):
            self.assertIn("canonical_operation_owner", self.verify())

    def test_authority_and_external_qualification_boundaries_remain_required(self):
        matrix = copy.deepcopy(self.matrix)
        matrix["authorityDelta"] = "grant"
        matrix["externalGates"][0]["repositoryMaySelfCertify"] = True
        self.assertIn("authority_delta", self.verify(matrix))
        self.assertIn("external_gate_self_certified", self.verify(matrix))


class LaneEWriterTests(unittest.TestCase):
    FEATURE = "qualification-legacy-learning-write"

    def uses(self, source, **options):
        return LANE_E.legacy_writer_uses(source, **options)

    def test_existing_record_identity_reads_are_not_writes(self):
        source = """fn event_record_id(event: &LedgerEvent) -> &StableId {
            match event {
                LedgerEvent::Decision(value) => &value.record_id,
                LedgerEvent::Outcome(value) => &value.record_id,
                LedgerEvent::Credit(value) => &value.record_id,
                LedgerEvent::Revocation(value) => &value.record_id,
            }
        }"""
        self.assertEqual(self.uses(source), [])

    def test_raw_constructors_and_forwarded_qualification_appends_fail(self):
        for variant in ("Decision", "Outcome", "Credit", "Revocation"):
            with self.subTest(variant=variant):
                self.assertTrue(
                    self.uses(
                        f"let event = LedgerEvent :: {variant}(value); journal.append(event);"
                    )
                )
        self.assertTrue(self.uses("journal.append_qualification(previous, event);"))
        self.assertTrue(
            self.uses(
                "match event { LedgerEvent::Decision(v) => &v.record_id, }; journal.append_qualification(p, event);"
            )
        )

    def test_mutable_or_unresolved_read_arms_and_aliases_fail(self):
        for source in (
            "match event { LedgerEvent::Decision(v) => &mut v.record_id, }",
            "match event { LedgerEvent::Decision(v) => consume(v), }",
            "use LedgerEvent as Event; let event = Event::Decision(value);",
            "use LedgerEvent::*; let event = Decision(value);",
            "type Event = codex_hepta_learning_ledger::LedgerEvent;",
        ):
            with self.subTest(source=source):
                self.assertTrue(self.uses(source))

    def test_sealed_read_trait_import_is_narrow_and_not_a_write_exemption(self):
        imported = "use codex_hepta_learning_ledger::DurableLearningJournal;\n"
        self.assertEqual(
            self.uses(
                imported + "let anchor = ledger.anchor()?;", read_only_journal=True
            ),
            [],
        )
        self.assertTrue(
            self.uses(
                imported + "ledger.append_decision(previous, value);",
                read_only_journal=True,
            )
        )
        self.assertTrue(self.uses(imported))
        self.assertTrue(
            self.uses(
                "fn write<J: DurableLearningJournal>(journal: &mut J) {}",
                read_only_journal=True,
            )
        )

    def test_exact_nondefault_qualification_item_is_explicit(self):
        source = f'#[cfg(feature = "{self.FEATURE}")]\npub fn fixture() {{ let event = LedgerEvent::Decision(value); journal.append_qualification(p, event); }}'
        self.assertEqual(self.uses(source, qualification_feature=self.FEATURE), [])
        self.assertTrue(self.uses(source))
        self.assertTrue(
            self.uses(
                source.replace("cfg(feature =", "cfg(any(feature =").replace(
                    '")]', '", test))]'
                ),
                qualification_feature=self.FEATURE,
            )
        )
        self.assertTrue(
            self.uses(
                source.replace(self.FEATURE, "unknown-profile"),
                qualification_feature=self.FEATURE,
            )
        )

    def test_qualification_item_cannot_hide_following_product_write(self):
        source = f'''#[cfg(feature = "{self.FEATURE}")]
        fn fixture() {{ let literal = r#"}}; #[cfg(feature = "{self.FEATURE}")]"#;
            /* nested {{ /* }} */ }} */ let event = LedgerEvent::Decision(value); }}
        fn product() {{ let event = LedgerEvent::Outcome(value); }}'''
        self.assertTrue(self.uses(source, qualification_feature=self.FEATURE))
        self.assertTrue(
            self.uses(
                f'// #[cfg(feature = "{self.FEATURE}")]\nfn product() {{ let event = LedgerEvent::Decision(v); }}',
                qualification_feature=self.FEATURE,
            )
        )

    def test_feature_enabled_by_default_or_transitively_is_not_explicit(self):
        self.assertTrue(
            LANE_E.feature_is_explicit(
                {"features": {"default": [], "qualification": []}}, "qualification"
            )
        )
        for default in ("qualification", "product"):
            manifest = {
                "features": {
                    "default": [default],
                    "product": ["qualification"],
                    "qualification": [],
                }
            }
            self.assertFalse(LANE_E.feature_is_explicit(manifest, "qualification"))
        self.assertFalse(
            LANE_E.feature_is_explicit({"features": {"default": []}}, "unknown")
        )

    def test_comments_literals_and_lifetimes_cannot_forge_uses_or_gates(self):
        source = """fn read<'a>(value: &'a str) { let text = r##"LedgerEvent::Decision(value)"##;
            /* DurableLearningJournal /* nested */ */ // LedgerEvent::Outcome(value)
        }"""
        self.assertEqual(self.uses(source), [])
        self.assertTrue(self.uses(source + "let event = LedgerEvent::Credit(value);"))


if __name__ == "__main__":
    unittest.main()
