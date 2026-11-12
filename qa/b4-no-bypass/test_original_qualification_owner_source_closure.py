"""Original Qualification persistence has one effect path and read-only recovery."""

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
    "original_qualification_owner_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
OWNER = AGENT + "neuron_cell_evaluation_qualification_owner.rs"
BINDING = AGENT + "neuron_cell_evaluation_qualification_binding.rs"
SOURCES = AGENT + "neuron_cell_evaluation_qualification_sources.rs"
PERSIST = AGENT + "neuron_cell_evaluation_qualification_persist.rs"
READBACK = AGENT + "neuron_cell_evaluation_qualification_readback.rs"
FUNCTIONS = {
    OWNER: {
        "fn create(", "fn recover(", "fn qualify_or_readback(",
        "fn publish_once(", "fn state(", "fn completed_bytes(",
    },
    BINDING: {
        "fn validate_config(", "fn authenticate_fixed(", "fn authenticate(",
        "fn decision_bytes(", "fn clock_time(", "fn new_work_time(", "fn now(",
    },
    SOURCES: {
        "fn read_original(", "fn read_trainer(", "fn prepare(", "fn prepare_with_training(", "fn verify_current(",
    },
    PERSIST: {"fn persist_original(", "fn persist("},
    READBACK: {
        "fn readback(", "fn read_completed(", "fn finish_readback(", "fn finish_readback_with_training(",
        "fn read_original(", "fn persist(",
    },
}
EFFECT = re.compile(
    r"(?:\.|::)\s*(?:claim|complete|compare_and_swap|create|release_after_consumption)\s*\("
)


def function_body(source, marker):
    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    start = code.index(marker)
    end = PROOF._rust_item_end(code, start)
    assert end is not None
    return code[start:end + 1]


def reject_effects(source, marker):
    if EFFECT.search(function_body(source, marker)):
        raise PROOF.VerificationFailure("read-only Qualification path contains an effect")


class OriginalQualificationOwnerSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def rows(self, path):
        return [row for row in self.manifest["protected_file"] if row["path"] == path]

    def rejects_change(self, path, change):
        source = (ROOT / path).read_text()
        rows = self.rows(path)
        self.assertEqual(len(rows), 1)
        changed = change(source)
        self.assertNotEqual(source, changed)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_each_original_custody_effect_and_fresh_clock_guard_is_effective(self):
        for path, expected in FUNCTIONS.items():
            rules = self.rows(path)[0]["required_function_order"]
            self.assertEqual({row["function"] for row in rules}, expected)
            for rule in rules:
                for index, marker in enumerate(rule["sequence"]):
                    with self.subTest(path=path, function=rule["function"], marker=marker, index=index):
                        def remove(source, rule=rule, index=index):
                            start = source.index(rule["function"])
                            end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
                            self.assertIsNotNone(end)
                            cursor = start
                            for token in rule["sequence"][:index + 1]:
                                at = source.index(token, cursor, end + 1)
                                cursor = at + len(token)
                            return source[:at] + source[cursor:]
                        self.rejects_change(path, remove)

    def test_public_owner_routes_are_closed_and_actual_original_edges_are_exact(self):
        expected = {
            "learning_original_qualification_owner_create": (),
            "learning_original_qualification_owner_recover": (),
            "learning_original_qualification_owner_publish": (),
            "learning_original_qualification_owner_readback": (),
            "cell_original_qualification_publication": (OWNER, READBACK),
            "learning_original_execution_store_create": (OWNER,),
            "learning_original_execution_store_recover": (OWNER,),
            "learning_original_execution_store_readback_only": (
                AGENT + "circuit_model_selection_receipt_sources.rs", SOURCES,
            ),
            "cell_original_completed_evaluation_evidence_readback": (
                AGENT + "circuit_model_selection_receipt_sources.rs", SOURCES,
            ),
            "product_original_execution_evidence_revalidate": (
                AGENT + "circuit_model_selection_receipt_binding.rs", BINDING,
            ),
        }
        paths = {path for identifier in expected for path in (
            self.boundaries[identifier].definition_path,
            *self.boundaries[identifier].product_callers,
        )}
        sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / path).read_text())) for path in paths}
        for identifier, callers in expected.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                self.assertEqual(row.product_callers, callers)
                PROOF._verify_boundary(ROOT, row, sources, ())
                if callers:
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=()), sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                changed = dict(sources)
                changed[AGENT + "unregistered_qualification_owner.rs"] = (
                    f"fn unexpected(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, changed, ())
        self.assertEqual(self.boundaries["root_learning_original_stage_assembly"].product_callers, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_recovery_and_readback_cannot_acquire_or_repeat_effects(self):
        for path, functions in (
            (OWNER, ("fn recover(", "fn state(", "fn completed_bytes(")),
            (SOURCES, tuple(FUNCTIONS[SOURCES])),
            (READBACK, tuple(FUNCTIONS[READBACK])),
        ):
            source = (ROOT / path).read_text()
            for marker in functions:
                reject_effects(source, marker)
                start = source.index(marker)
                body = source.index("{", start) + 1
                for call in (
                    "owner.claim(key);", "owner.complete(key, bytes);",
                    "witness.compare_and_swap(old, new);", "Owner::create(file, witness);",
                    "provider.release_after_consumption(receipt);",
                ):
                    with self.subTest(path=path, function=marker, call=call):
                        changed = source[:body] + call + source[body:]
                        with self.assertRaises(PROOF.VerificationFailure):
                            reject_effects(changed, marker)
        self.rejects_change(OWNER, lambda source: source.replace(
            "fresh_dispatch: false", "fresh_dispatch: true",
        ))
        self.rejects_change(PERSIST, lambda source: source.replace(
            "self.used = true", "self.used = false",
        ))

    def test_complete_original_signatures_context_and_decision_remain_bound(self):
        for marker in (
            "&config.training_evidence", "&config.product_evidence.generator_plan",
            "&config.product_evidence.evaluator_bundle", "config.execution_evidence.attestation()",
            "original.signing_bytes()", "bytes.extend_from_slice(&original.signature)",
            "config.context.retention_receipt_digests", "config.context.unlearning_receipt_digest",
            "config.qualification_namespace", "config.execution_evidence.record_digest()",
            "&decision.decision.baseline_id", "decision.decision.failed_metrics",
        ):
            with self.subTest(marker=marker):
                self.rejects_change(BINDING, lambda source, marker=marker: source.replace(marker, "substituted"))
        for path in FUNCTIONS:
            for code in (
                "SigningKey::from_bytes(bytes);", "LearningEvidenceVerifierV1::new(trust);",
                "File::open(path);", "owner.try_clone();", "owner.into_inner();",
                "pub journal: Raw", "pub witness: Witness", "impl Deserialize for Seal {}",
            ):
                with self.subTest(path=path, code=code):
                    self.rejects_change(path, lambda source, code=code: source + "\n" + code + "\n")

    def test_only_concrete_original_sources_and_internal_time_can_satisfy_readback(self):
        for old, new in (
            ("CellEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1>", "CellEvaluationRunnerV1<ArbitraryStore>"),
            ("OriginalCellEvaluationExecutionStoreV1<X>", "GenericMutableStore"),
            ("if original != config.training_evidence", "if false"),
            ("if before != after", "if false"),
            ("if execution != config.execution_evidence || evaluation.plan() != &config.plan", "if false"),
        ):
            with self.subTest(old=old):
                self.rejects_change(SOURCES, lambda source, old=old, new=new: source.replace(old, new))
        self.rejects_change(READBACK, lambda source: source.replace(
            "let current = binding::now()?;", "let current = started_at;",
        ))
        self.rejects_change(BINDING, lambda source: source.replace(
            "current >= config.training.request.envelope.expiry_unix_seconds", "false",
        ))
        for path in (OWNER, READBACK, SOURCES):
            source = (ROOT / path).read_text()
            self.assertNotIn("pub now:", source)
            self.assertNotIn("pub clock:", source)
            self.assertNotIn("pub sink:", source)

    def test_actual_fixture_uses_original_owner_and_native_inventory_preserves_limits(self):
        support = (ROOT / AGENT / "circuit_model_selection_evaluation_support_tests.rs").read_text()
        self.assertIn("OriginalCellEvaluationQualificationOwnerV1::create(", support)
        self.assertIn(".qualify_or_readback(OriginalCellEvaluationQualificationSourcesV1", support)
        self.assertNotIn("FileSink", support)
        self.assertIn("retention_receipt_digests: Vec::new()", support)
        self.assertIn("cohorts, product declarations and role custody remain test fixtures", support)
        tests = (ROOT / AGENT / "circuit_model_qualification_owner_tests.rs").read_text()
        names = re.findall(r"async fn (original_qualification_\w+)\(", tests)
        self.assertEqual(len(names), 6)
        coverage = (ROOT / "scripts/hepta_c_observer_coverage.py").read_text()
        for name in names:
            self.assertIn(name, coverage)
        self.assertIn('("original_qualification_owner", PACKAGE, QUALIFICATION_OWNER_CASES)', coverage)
        parent = (ROOT / AGENT / "circuit_model_selection_owner_published_tests.rs").read_text()
        self.assertIn('#[path = "circuit_model_qualification_owner_tests.rs"]', parent)
        self.assertIn("mod qualification_owner;", parent)
        self.assertIn("LostAck::BeforeWrite", tests)
        self.assertIn("LostAck::AfterWrite", tests)
        self.assertIn("OriginalCellEvaluationExecutionStoreErrorV1::CommitUncertain", tests)
        self.assertIn("Err(Error::Pending)", tests)
        self.assertIn("qualification_overwrite", tests)
        self.assertNotIn("CellEvaluationQualificationV1 {", tests)


if __name__ == "__main__":
    unittest.main()
