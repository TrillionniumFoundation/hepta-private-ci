"""Mutation controls for the same-owner Cell qualification bridge.

These checks establish source closure, not native execution or real B custody.
"""

from dataclasses import replace
import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_cell_qualification_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
BRIDGE = AGENT + "neuron_cell_qualification_owner.rs"
OWNER = AGENT + "product_qualification_owner.rs"
CELL = AGENT + "neuron_cell_evaluation.rs"
CALLERS = {
    "original_product_qualification_publish": (BRIDGE,),
    "original_product_qualification_readback": (BRIDGE,),
    "cell_original_qualification_publish": (),
    "cell_original_qualification_readback": (),
}
FUNCTIONS = (
    "fn publish_original_qualification(",
    "fn readback_original_qualification(",
)


def span(source, function):
    code = PROOF._strip_rust_non_code(source)
    start = code.index(function)
    end = PROOF._rust_item_end(code, start)
    if end is None:
        raise PROOF.VerificationFailure("missing original Cell function")
    return start, end + 1


def verify_barriers(source):
    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    for function in FUNCTIONS:
        start, end = span(code, function)
        body = code[start:end]
        barriers = list(re.finditer(re.escape("source.require_original()?;"), body))
        if len(barriers) != 2:
            raise PROOF.VerificationFailure("two original Cell barriers required")
        for barrier in barriers:
            prefix = body[: barrier.start()]
            if prefix.count("{") - prefix.count("}") != 1:
                raise PROOF.VerificationFailure("Cell barrier must be unconditional")


class OriginalCellQualificationSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}
        cls.rows = [row for row in cls.manifest["protected_file"] if row["path"] == BRIDGE]
        cls.source = (ROOT / BRIDGE).read_text()
        cls.sources = {
            path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / path).read_text()))
            for path in (BRIDGE, OWNER, CELL)
        }

    def verify(self, source):
        self.assertEqual(len(self.rows), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / BRIDGE
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": self.rows})
        verify_barriers(source)

    def rejects(self, function, marker, replacement="", occurrence=0):
        self.verify(self.source)
        start, end = span(self.source, function)
        matches = list(re.finditer(re.escape(marker), self.source[start:end]))
        self.assertGreater(len(matches), occurrence)
        offset = start + matches[occurrence].start()
        changed = self.source[:offset] + replacement + self.source[offset + len(marker) :]
        with self.assertRaises(PROOF.VerificationFailure):
            self.verify(changed)

    def test_only_concrete_cell_bridge_consumes_original_publication(self):
        inventory = self.manifest["privileged_inventory"]["required_boundary_ids"]
        for identifier, callers in CALLERS.items():
            with self.subTest(boundary=identifier):
                self.assertIn(identifier, inventory)
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, callers)
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                if callers:
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=()), self.sources, ())
                changed = dict(self.sources)
                method = row.symbol.rsplit("::", 1)[-1]
                changed[AGENT + "unregistered_cell_qualification.rs"] = (
                    f"fn bypass(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, changed, ())
        self.assertEqual(self.boundaries["root_learning_original_stage_assembly"].product_callers, ())
        self.assertTrue(all(flag is False for flag in self.manifest["authority"].values()))

    def test_complete_plan_and_both_original_journals_are_required(self):
        for marker in (
            "if self.product.plan != self.plan.product_plan()",
            "self.plan.require_journals(CellEvaluationJournalsV1",
            "candidate: self.journals.candidate",
            "fixed_expert: self.journals.fixed_expert",
        ):
            with self.subTest(marker=marker):
                self.rejects("fn require_original(", marker)

    def test_each_pre_and_post_barrier_rejects_removal(self):
        for function in FUNCTIONS:
            for occurrence in (0, 1):
                with self.subTest(function=function, occurrence=occurrence):
                    self.rejects(function, "source.require_original()?;", occurrence=occurrence)

    def test_barriers_cannot_hide_in_dead_code(self):
        for function in FUNCTIONS:
            for occurrence in (0, 1):
                with self.subTest(function=function, occurrence=occurrence):
                    self.rejects(function, "source.require_original()?;", "if false { source.require_original()?; }", occurrence)

    def test_final_owner_readback_and_full_receipt_equality_are_required(self):
        for function in FUNCTIONS:
            for marker in (
                "let retained = OriginalProductQualificationOwnerV1::readback(",
                "if retained != publication",
                "return Err(OriginalCellQualificationErrorV1::CommitUncertain)",
                "comparison: source.plan.record.clone()",
                "product: retained",
            ):
                with self.subTest(function=function, marker=marker):
                    self.rejects(function, marker)

    def test_same_runner_and_original_execution_store_are_required(self):
        for function in FUNCTIONS:
            for occurrence in (0, 1):
                with self.subTest(function=function, occurrence=occurrence):
                    self.rejects(function, "&mut self.product", "&mut replacement", occurrence)

    def test_bridge_cannot_provision_replacement_custody_or_sign(self):
        for forbidden in ("ProductEvaluationRunnerV1::new", "SigningKey", "File::open", ".sign(", "NoUpdate"):
            with self.subTest(forbidden=forbidden):
                self.rejects(FUNCTIONS[0], "source.require_original()?;", forbidden + "; source.require_original()?;")

    def test_original_product_guards_are_still_registered(self):
        paths = {
            OWNER,
            AGENT + "product_qualification_owner_codec.rs",
            "codex-rs/hepta-intelligence-eval/src/product_qualification_material.rs",
        }
        rows = [row for row in self.manifest["protected_file"] if row["path"] in paths]
        self.assertEqual({row["path"] for row in rows}, paths)
        PROOF._verify_protected_files(ROOT, {"protected_file": rows})


if __name__ == "__main__":
    unittest.main()
