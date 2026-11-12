"""Consumption-time origin equality precedes any Root runtime admission.

These mutations protect the real private-origin comparison; source tests do
not claim execution of the separately selected protected Root native case.
"""
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "resident_origin_proof", ROOT / "scripts/verify_hepta_callers.py")
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
COMMON = AGENT + "cell_q24_no_update_stage_owners.rs"
CANDIDATE = AGENT + "cell_q24_candidate_stage_owners.rs"
STAGES = AGENT + "authority_host_learning_resident_stages.rs"
RUNTIME = AGENT + "authority_host_learning_resident_runtime.rs"
FILES = (COMMON, CANDIDATE, STAGES, RUNTIME)
GETTER = "fn original_resident_readback_only("
EXPECTED = {
    "root_resident_no_update_private_origin": (STAGES, CANDIDATE),
    "root_resident_candidate_private_origin": (STAGES,),
    "root_resident_stage_private_origin": (RUNTIME,),
}


class ResidentOriginSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def code(self, source):
        return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))

    def rows(self, path):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertEqual(len(rows), 1)
        return rows

    def verify(self, path, text):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(text)
            PROOF._verify_protected_files(root, {"protected_file": self.rows(path)})

    def item(self, path, function):
        source = (ROOT / path).read_text()
        code = self.code(source)
        self.assertEqual(code.count(function), 1)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        return source, start, end + 1

    def rejects(self, path, function, marker, replacement=""):
        source, start, end = self.item(path, function)
        self.verify(path, source)
        offset = source.index(marker, start, end)
        changed = source[:offset] + replacement + source[offset + len(marker):]
        self.assertNotEqual(changed, source)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verify(path, changed)

    def test_only_original_typed_getter_callers_are_registered(self):
        sources = {path: self.code((ROOT / path).read_text()) for path in FILES}
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, expected)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, sources, ())
                extra = dict(sources)
                extra[AGENT + "unregistered_origin.rs"] = (
                    f"fn bypass(owner: &{row.receiver_type}) {{ "
                    "let _ = owner.original_resident_readback_only(); }")
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())

    def test_real_private_origins_cannot_be_replaced_or_inverted(self):
        for replacement in ("", "self.origin == Origin::Fresh", "true", "false"):
            with self.subTest(common=replacement):
                self.rejects(COMMON, GETTER, "self.origin == Origin::Recovered", replacement)
        for path, marker in (
            (CANDIDATE, "OriginalCellQ24NoUpdateStageOwnersV1::original_resident_readback_only(&self.common)"),
            (STAGES, "OriginalCellQ24NoUpdateStageOwnersV1::original_resident_readback_only(stages)"),
            (STAGES, "OriginalCellQ24CandidateStageOwnersV1::original_resident_readback_only(stages)"),
        ):
            for replacement in ("", "false", "true", "!" + marker):
                with self.subTest(path=path, marker=marker, replacement=replacement):
                    self.rejects(path, GETTER, marker, replacement)

    def test_getters_and_origin_storage_cannot_gain_caller_authority(self):
        for path, field in ((COMMON, "origin: Origin"), (CANDIDATE, "common: OriginalCellQ24NoUpdateStageOwnersV1")):
            source = (ROOT / path).read_text()
            code = self.code(source)
            self.assertEqual(code.count(field), 1)
            offset = code.index(field)
            for visibility in ("pub", "pub(crate)", "pub(super)"):
                with self.subTest(path=path, visibility=visibility):
                    self.verify(path, source)
                    changed = source[:offset] + visibility + " " + source[offset:]
                    with self.assertRaises(PROOF.VerificationFailure):
                        self.verify(path, changed)
        for path in (COMMON, CANDIDATE, STAGES):
            source = (ROOT / path).read_text()
            visibility = "pub(super)" if path == STAGES else "pub(crate)"
            marker = visibility + " " + GETTER
            self.assertEqual(source.count(marker), 1)
            with self.assertRaises(PROOF.VerificationFailure):
                self.verify(path, source.replace(marker, "pub " + GETTER))
            self.rejects(path, GETTER, "&self", "&self, caller_origin: bool")

    def test_consuming_check_precedes_queue_and_cannot_use_a_constant(self):
        check = "ResidentOriginalStageOwnersV3::original_resident_readback_only(&stages) != readonly"
        self.rejects(RUNTIME, "fn compose(", check, check.replace("!=", "=="))
        self.rejects(RUNTIME, "fn compose(", "let readonly = owner.authority.readonly()", "let readonly = true")
        self.rejects(RUNTIME, "fn compose(", "let readonly = owner.authority.readonly()", "let readonly = false")
        source, start, end = self.item(RUNTIME, "fn compose(")
        code = self.code(source)
        block_start = code.index("if " + check, start, end)
        block_end = PROOF._rust_item_end(code, block_start) + 1
        block = source[block_start:block_end]
        self.rejects(RUNTIME, "fn compose(", block)
        queue = "    let (sender, receiver) = mpsc::channel(capacity);"
        moved = source[:block_start] + source[block_end:]
        self.assertEqual(moved.count(queue), 1)
        moved = moved.replace(queue, queue + "\n    " + block)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verify(RUNTIME, moved)

    def test_uncalled_closures_cannot_satisfy_origin_checks(self):
        source, start, end = self.item(RUNTIME, "fn compose(")
        code = self.code(source)
        block_start = code.index("if ResidentOriginalStageOwnersV3::original_resident_readback_only", start, end)
        block_end = PROOF._rust_item_end(code, block_start) + 1
        block = source[block_start:block_end]
        for replacement in (
            "let never_called = || { " + block + " };",
            block.replace("return Err(AgentdError::Invalid(", "let never_called = || { return Err(AgentdError::Invalid(")
                 .replace("));\n    }", ")); };\n    }"),
        ):
            with self.subTest(replacement=replacement):
                self.rejects(RUNTIME, "fn compose(", block, replacement)
        for path in (COMMON, CANDIDATE, STAGES):
            source, start, end = self.item(path, GETTER)
            open_at = source.index("{", start, end)
            body = source[open_at + 1:end - 1]
            changed = source[:open_at+1] + " let never_called = || {" + body + "}; false " + source[end-1:]
            with self.subTest(path=path):
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verify(path, changed)

    def test_later_fresh_gate_refusal_is_still_independent(self):
        self.rejects(COMMON, "fn install_fresh_resident_gate(", "self.origin != Origin::Fresh || self.root.is_some()")
        self.rejects(COMMON, "fn install_fresh_resident_gate(", "self.origin != Origin::Fresh", "self.origin == Origin::Fresh")
        self.rejects(CANDIDATE, "fn install_fresh_resident_gate(", "OriginalCellQ24NoUpdateStageOwnersV1::install_fresh_resident_gate(&mut self.common, gate)")
        self.rejects(RUNTIME, "fn admit(", "ResidentOriginalStageOwnersV3::install_fresh_resident_gate(")


if __name__ == "__main__":
    unittest.main()
