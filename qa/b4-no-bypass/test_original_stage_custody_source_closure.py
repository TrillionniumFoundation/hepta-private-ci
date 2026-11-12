"""Protect original stage custody without a data guard crossing async work."""

import re
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import verify_hepta_callers as PROOF


AGENT = "codex-rs/hepta-agentd/src/"
HELPER = AGENT + "cell_q24_stage_custody.rs"
# Frozen from original 57b: path, function, receiver, state, mutability, lexical depth.
EXPECTED = [
    (AGENT + "cell_q24_no_update_stage_execute.rs", "execute_original_stage",
     "self.continuation", "state", True, 1),
    (AGENT + "cell_q24_no_update_stage_owners.rs", "validate_recovery",
     "self.continuation", "state", True, 3),
    (AGENT + "cell_q24_no_update_stage_owners.rs", "receipt_attestation",
     "self.continuation", "state", True, 3),
    (AGENT + "cell_q24_candidate_stage_readback.rs", "read_original_candidate",
     "self.common.continuation", "state", True, 1),
    (AGENT + "cell_q24_candidate_stage_readback.rs", "read_original_candidate",
     "self.candidate", "lane", True, 1),
    (AGENT + "cell_q24_candidate_stage_evaluation.rs", "original_evaluation",
     "self.evaluation", "lane", True, 1),
    (AGENT + "cell_q24_candidate_stage_evaluation.rs", "original_evaluation",
     "self.common.continuation", "common", True, 2),
    (AGENT + "cell_q24_candidate_stage_evaluation.rs", "original_evaluation",
     "self.common.continuation", "common", True, 1),
    (AGENT + "cell_q24_candidate_stage_model.rs", "original_model",
     "self.model", "lane", True, 2),
    (AGENT + "cell_q24_candidate_stage_model.rs", "original_model",
     "self.model", "lane", True, 2),
    (AGENT + "cell_q24_candidate_stage_model.rs", "original_model",
     "self.model", "lane", False, 2),
    (AGENT + "cell_q24_candidate_stage_model.rs", "original_model",
     "self.common.continuation", "common", False, 1),
    (AGENT + "cell_q24_candidate_stage_model.rs", "original_model",
     "self.model", "lane", True, 1),
    (AGENT + "cell_q24_candidate_stage_model.rs", "model_predecessors",
     "self.common.continuation", "common", True, 1),
    (AGENT + "cell_q24_candidate_stage_retention.rs", "evaluated_predecessors",
     "self.common.continuation", "common", False, 1),
    (AGENT + "cell_q24_candidate_stage_retention_attestations.rs", "read_original_evaluated_attestations",
     "self.common.continuation", "common", False, 5),
    (AGENT + "cell_q24_candidate_stage_retention_attestations.rs", "read_original_evaluated_attestations",
     "self.retention", "lane", False, 4),
    (AGENT + "cell_q24_candidate_stage_retention_attestations.rs", "read_original_evaluated_attestations",
     "self.retention", "lane", False, 4),
    (AGENT + "cell_q24_candidate_stage_retention_attestations.rs", "evaluated_predecessor_signatures",
     "self.common.continuation", "common", False, 1),
    (AGENT + "cell_q24_candidate_stage_retention_binding.rs", "ensure_version",
     "owners.common.continuation", "common", True, 2),
    (AGENT + "cell_q24_candidate_stage_retention_next_use.rs", "original_evaluated_next_use",
     "self.retention", "lane", True, 1),
    (AGENT + "cell_q24_candidate_stage_retention_selection.rs", "original_evaluated_selection",
     "self.retention", "lane", True, 1),
]
PAIR = re.compile(
    r"let (?P<mut>mut )?(?P<held>(?:state|common|lane)_lease) = "
    r"(?P<receiver>(?:self|owners)(?:\.\w+)+)\.try_lease\(\)\?;"
    r"\s*let (?P<value>state|common|lane) = (?P=held)\."
    r"(?P<getter>value_mut|value)\(\)\?;"
)


def code(source):
    return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))


def lease_scopes(path, source):
    masked = code(source)
    result = []
    pairs = list(PAIR.finditer(masked))
    if len(pairs) != len(re.findall(r"\.try_lease\s*\(", masked)):
        raise AssertionError("every original slot access needs an adjacent owned borrow")
    for held in ("state_lease", "common_lease", "lane_lease"):
        uses = len(re.findall(r"\b" + held + r"\b", masked))
        if uses != 2 * sum(pair["held"] == held for pair in pairs):
            raise AssertionError("original leases release only at their lexical scope end")
    for pair in pairs:
        functions = list(re.finditer(r"\bfn\s+(\w+)(?:<[^>]*>)?\s*\(", masked[:pair.start()]))
        if not functions:
            raise AssertionError("lease must belong to its original function")
        function = functions[-1]
        opening = masked.index("{", function.start())
        prefix = masked[opening:pair.start()]
        depth = prefix.count("{") - prefix.count("}")
        mutable = pair["mut"] is not None
        if pair["getter"] != ("value_mut" if mutable else "value"):
            raise AssertionError("lease mutability and original state borrow differ")
        if pair["held"] != pair["value"] + "_lease":
            raise AssertionError("original state must borrow this exact lease")
        result.append(
            (path, function[1], pair["receiver"], pair["value"], mutable, depth)
        )
    return result


def require_original_scopes(sources):
    actual = []
    for path in dict.fromkeys(row[0] for row in EXPECTED):
        actual.extend(lease_scopes(path, sources[path]))
    if actual != EXPECTED:
        raise AssertionError(("original custody scopes changed", actual, EXPECTED))


def require_private_helper(source):
    masked = code(source)
    functions = re.findall(r"\bfn\s+(\w+)\s*[<(]", masked)
    if functions != ["new", "try_lease", "value", "value_mut", "drop"]:
        raise AssertionError("no new slot accessor or alternate restoration method")
    start = masked.index("fn new(")
    end = PROOF._rust_item_end(masked, start)
    if masked.count("Box::new(") != 1 or masked[start:end + 1].count("Box::new(") != 1:
        raise AssertionError("only initial construction allocates the original box")
    expected = {
        "OriginalStageSlot": [
            ("admission", "Semaphore"),
            ("value", "Mutex<Option<Box<T>>>"),
        ],
        "OriginalStageLease": [
            ("slot", "&'a OriginalStageSlot<T>"),
            ("value", "Option<Box<T>>"),
            ("_admission", "SemaphorePermit<'a>"),
        ],
    }
    for name, fields in expected.items():
        start = masked.index("struct " + name)
        opening = masked.index("{", start)
        end = PROOF._rust_item_end(masked, start)
        if end is None:
            raise AssertionError("private custody fields must be explicit")
        actual = [
            (field, field_type.strip())
            for field, field_type in re.findall(
                r"^\s*(\w+):\s*([^,\n]+),", masked[opening + 1:end], re.MULTILINE
            )
        ]
        if actual != fields:
            raise AssertionError(("private boxed state and final admission required", actual))
    for function, lock in [
        ("fn try_lease(", "self.value.try_lock()"),
        ("fn drop(", "self.slot.value.try_lock()"),
    ]:
        start = masked.index(function)
        end = PROOF._rust_item_end(masked, start)
        body = masked[start:end + 1]
        if body.count(lock) != 1 or body.count(".try_lock()") != 1:
            raise AssertionError("only one short slot contact in each transfer")


class OriginalStageCustodySourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.sources = {
            path: (ROOT / path).read_text()
            for path in dict.fromkeys(row[0] for row in EXPECTED)
        }
        cls.helper = (ROOT / HELPER).read_text()

    def verifies(self, path, source):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertEqual(len(rows), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})

    def rejects_helper(self, marker, replacement):
        self.assertIn(marker, self.helper)
        self.verifies(HELPER, self.helper)
        changed = self.helper.replace(marker, replacement, 1)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(HELPER, changed)

    def test_original_twenty_two_accesses_keep_their_scopes_and_admission_order(self):
        self.assertEqual(len(EXPECTED), 22)
        require_original_scopes(self.sources)
        for path, source in self.sources.items():
            self.verifies(path, source)

    def test_helper_owns_one_box_and_keeps_admission_until_restoration(self):
        require_private_helper(self.helper)
        self.verifies(HELPER, self.helper)

    def test_no_box_is_inlined_copied_or_reconstructed_during_transfer(self):
        for marker, replacement in [
            ("value: Mutex<Option<Box<T>>>", "value: Mutex<Option<T>>"),
            ("value: Option<Box<T>>", "value: Option<T>"),
            ("slot.take().ok_or(Error::CommitUncertain)?", "slot.as_ref().ok_or(Error::CommitUncertain)?"),
            ("value: Some(value)", "value: Some(value.clone())"),
            ("*slot = Some(value)", "*slot = None"),
        ]:
            with self.subTest(marker=marker):
                self.rejects_helper(marker, replacement)
        changed = self.helper.replace(
            "        Ok(OriginalStageLease {",
            "        let value = Box::new(*value);\n        Ok(OriginalStageLease {",
            1,
        )
        with self.assertRaises(AssertionError):
            require_private_helper(changed)

    def test_slot_admission_cannot_be_queued_expanded_or_exempted(self):
        for marker, replacement in [
            (".try_acquire()", ".acquire().await"),
            ("let admission =", "self.admission.add_permits(1);\n        let admission ="),
            ("pub(super) fn try_lease", "#[allow(clippy::await_holding_invalid_type)]\n    pub(super) fn try_lease"),
            ("pub(super) fn try_lease", "#[expect(clippy::await_holding_invalid_type)]\n    pub(super) fn try_lease"),
        ]:
            with self.subTest(replacement=replacement):
                self.rejects_helper(marker, replacement)

    def test_helper_does_not_gain_an_unadmitted_accessor_or_exposed_slot(self):
        changed = self.helper.replace(
            "    admission: Semaphore,", "    pub(super) admission: Semaphore,", 1
        )
        with self.assertRaises(AssertionError):
            require_private_helper(changed)
        changed = self.helper + "\nfn unadmitted_slot() {}\n"
        with self.assertRaises(AssertionError):
            require_private_helper(changed)

    def test_model_dispatch_custody_cannot_expand_over_predecessor_io(self):
        path = AGENT + "cell_q24_candidate_stage_model.rs"
        original = self.sources[path]
        old = (
            "        let actual = {\n"
            "            let mut lane_lease = self.model.try_lease()?;\n"
            "            let lane = lane_lease.value_mut()?;\n"
        )
        new = (
            "        let mut lane_lease = self.model.try_lease()?;\n"
            "        let lane = lane_lease.value_mut()?;\n"
            "        let actual = {\n"
        )
        self.assertIn(old, original)
        changed = dict(self.sources)
        changed[path] = original.replace(old, new, 1)
        with self.assertRaises(AssertionError):
            require_original_scopes(changed)

        # The final common state must remain owned through the Model update.
        marker = "        self.verify_original_evaluation(snapshot, &training_cut, &after.1, &after.2, fresh)?;"
        self.assertEqual(original.count(marker), 1)
        changed = dict(self.sources)
        changed[path] = original.replace(marker, "        drop(common_lease);\n" + marker, 1)
        with self.assertRaises(AssertionError):
            require_original_scopes(changed)

    def test_candidate_common_then_candidate_order_cannot_be_reversed(self):
        path = AGENT + "cell_q24_candidate_stage_readback.rs"
        original = self.sources[path]
        common = (
            "        let mut state_lease = self.common.continuation.try_lease()?;\n"
            "        let state = state_lease.value_mut()?;\n"
        )
        candidate = (
            "        let mut lane_lease = self.candidate.try_lease()?;\n"
            "        let lane = lane_lease.value_mut()?;\n"
        )
        self.assertIn(common + candidate, original)
        changed = dict(self.sources)
        changed[path] = original.replace(common + candidate, candidate + common, 1)
        with self.assertRaises(AssertionError):
            require_original_scopes(changed)


    def test_original_common_borrow_cannot_be_replaced_by_a_different_lease(self):
        path = AGENT + "cell_q24_candidate_stage_evaluation.rs"
        original = self.sources[path]
        changed = dict(self.sources)
        changed[path] = original.replace(
            "let common = common_lease.value_mut()?;",
            "let common = lane_lease.value_mut()?;",
            1,
        )
        with self.assertRaises(AssertionError):
            require_original_scopes(changed)

    def test_fixture_initialization_uses_the_same_private_admission(self):
        path = ROOT / AGENT / "cell_q24_no_update_stage_support_tests.rs"
        source = path.read_text()
        self.assertNotIn(".get_mut()", source)
        self.assertIn(
            "let mut state = owners.continuation.try_lease()?;\n"
            "        state.value_mut()?.trainer = Some(trainer);",
            source,
        )


if __name__ == "__main__":
    unittest.main()
