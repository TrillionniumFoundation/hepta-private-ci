"""Protect the audited original Model host and its five direct dependencies.

Fresh Execute remains an original effect; deployment recovery remains explicit.
The source checks do not mint opaque evidence or stand in for Rust execution.
Six generic functions use the original file-order fallback, whose uniqueness
and nested-definition guarantees are weaker than function-scoped verification.
Three masked, safety-relevant literals are checked at their actual raw spans.
"""
import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_model_host_source_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
HOST = AGENT + "cell_q24_model_command_host.rs"
CONTEXT = AGENT + "cell_q24_model_command_context.rs"
EFFECT = AGENT + "cell_q24_model_command_effect.rs"
LANE = AGENT + "cell_q24_model_command_lane.rs"
ADMISSION = AGENT + "cell_q24_model_current_admission.rs"
OWNER = AGENT + "cell_q24_model_current_owner.rs"
PATHS = (HOST, CONTEXT, EFFECT, LANE, ADMISSION, OWNER)
DOMAIN = r'b"hepta.agentd.original-q24-model-command.v1\0"'


class OriginalModelHostSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.rows = {}
        for path in PATHS:
            rows = [row for row in manifest["protected_file"] if row["path"] == path]
            if len(rows) != 1:
                raise AssertionError((path, "one audited Model protected row required"))
            cls.rows[path] = rows
        PROOF._verify_protected_files(
            ROOT, {"protected_file": [cls.rows[path][0] for path in PATHS]}
        )

    def assert_rejected(self, path, changed):
        self.assertNotEqual(changed, (ROOT / path).read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": self.rows[path]})

    def function(self, path, function):
        original = (ROOT / path).read_text()
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(original))
        self.assertEqual(code.count(function), 1, (path, function))
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        return original, start, end + 1

    def mutate(self, path, function, marker, replacement=""):
        original, start, end = self.function(path, function)
        body = original[start:end]
        self.assertEqual(body.count(marker), 1, (path, function, marker))
        changed = body.replace(marker, replacement, 1)
        self.assert_rejected(path, original[:start] + changed + original[end:])

    def test_host_preserves_fresh_recovered_origins_and_shared_once(self):
        self.mutate(
            HOST, "fn from_original_bootstrap(",
            "if !matches!(bootstrap.origin, BootstrapOrigin::Fresh)",
            "if matches!(bootstrap.origin, BootstrapOrigin::Fresh)",
        )
        self.mutate(HOST, "fn recover_original_bootstrap(", "Origin::Recovered", "Origin::Fresh")
        for marker, replacement in (
            ("/*new*/ true", "/*new*/ false"),
            ("execution_requested: matches!(origin, Origin::Recovered)", "execution_requested: false"),
            ("config.initial.request.evaluation_profile != registration.evaluation_profile()", "false"),
        ):
            with self.subTest(marker=marker):
                self.mutate(HOST, "fn bind(", marker, replacement)
        for marker in ("model_host_bound.store(false, Ordering::Release)", "state.fenced = false"):
            with self.subTest(reset=marker):
                self.assert_rejected(HOST, (ROOT / HOST).read_text() + "\nfn reset() { " + marker + "; }\n")

    def test_host_reads_actual_dataset_training_and_current_evaluator_before_retaining(self):
        for marker, replacement in (
            ("&self.bootstrap.dataset", "&other_dataset"),
            ("OriginalCellQ24TrainingCommandOwnerV1::read_original_model_training", "OriginalCellQ24TrainingCommandOwnerV1::read_other_training"),
            ("retained.binding()? != context.binding()?", "retained.binding()? == context.binding()?"),
            ("let fresh = context.authenticate(started)?;", "let fresh = started;"),
            ("material.authenticate_current(fresh)?;", ""),
        ):
            with self.subTest(marker=marker):
                self.mutate(HOST, "fn original_inputs(", marker, replacement)
        self.mutate(HOST, "fn recover_deployment(", "context.require_qualified()?;")
        self.mutate(
            HOST, "fn recover_deployment(",
            "OriginalCellQ24TrainingCommandOwnerV1::recover_original_model",
            "OriginalCellQ24TrainingCommandOwnerV1::create_original_model",
        )

    def test_context_preserves_actual_training_extension_and_complete_original_signatures(self):
        self.mutate(CONTEXT, "fn from_original(", "dataset.snapshot().receipts.len() != 2", "false")
        self.mutate(CONTEXT, "fn from_original(", "original.authenticate(started)?;")
        for marker, replacement in (
            ("binding != self.initial_binding", "false"),
            ("self.evaluation.training_attestation() != self.training.attestation()", "false"),
            ("LearningEvidenceRoleV1::Generator,", "LearningEvidenceRoleV1::Evaluator,"),
            ("verify_signed_actor_separation(&generator, &evaluator, current)?;", ""),
            ("require_clock(dataset_at, current)?;", ""),
            ("coordinator.snapshot() != self.evaluation.snapshot()", "false"),
        ):
            with self.subTest(marker=marker):
                self.mutate(CONTEXT, "fn authenticate(", marker, replacement)
        self.mutate(
            CONTEXT, "fn require_qualified(",
            "LearningEvaluationDispositionV1::Qualified", "LearningEvaluationDispositionV1::NoUpdate",
        )
        for marker in (
            "self.material.verifier.trust_digest(),",
            "self.material.verifier.scope_digest(),",
            "self.material.verifier.objective_digest(),",
        ):
            with self.subTest(binding=marker):
                self.mutate(CONTEXT, "fn binding(", marker)

    def test_effect_preserves_incomplete_outcomes_once_and_readback_without_commit(self):
        self.mutate(EFFECT, "fn observe(", "Ok(Observed::Pending)", "Ok(Observed::Missing)")
        for marker, replacement in (
            ("if state.fenced {", "if !state.fenced {"),
            ("request.action == wire::Action::Execute && state.execution_requested", "false"),
            ("request.action == wire::Action::Readback && state.model.is_none()", "false"),
            ("state.execution_requested = true;", "state.execution_requested = false;"),
            ("if self.bootstrap.cancellation.load(Ordering::Acquire)", "if !self.bootstrap.cancellation.load(Ordering::Acquire)"),
            ("context.require_qualified()?;", ""),
            ("if observed != after", "if observed == after"),
            ("state.fenced = true;", "state.fenced = false;"),
            ("Observed::Missing => Ok(wire::Outcome::Missing)", "Observed::Missing => Ok(wire::Outcome::Pending)"),
        ):
            with self.subTest(marker=marker):
                self.mutate(EFFECT, "fn original_response(", marker, replacement)
        self.mutate(
            EFFECT, "fn original_response(",
            "observe(OriginalCellQ24TrainingCommandOwnerV1::read_original_model(",
            "observe(OriginalCellQ24TrainingCommandOwnerV1::commit_original_model(",
        )

    def test_after_read_reenters_only_original_lane_then_authenticates_both_materials(self):
        for marker, replacement in (
            ("after.binding() != before.binding()", "false"),
            ("after.original_evaluation() != before.original_evaluation()", "false"),
            ("after.original_evaluation() != &context.evaluation", "false"),
            ("before.authenticate_current(fresh)?;", ""),
            ("after.authenticate_current(fresh)?;", ""),
            ("require_clock(started, fresh)?;", ""),
            ("OriginalCellQ24TrainingCommandOwnerV1::read_original_model(", "OriginalCellQ24TrainingCommandOwnerV1::commit_original_model("),
        ):
            with self.subTest(marker=marker):
                self.mutate(EFFECT, "fn current_after(", marker, replacement)

    def test_original_lane_keeps_actual_context_and_purpose(self):
        self.mutate(
            LANE, "fn read_original_model_training(",
            "dataset.snapshot() != &self.context.dataset", "false",
        )
        for function in (
            "fn create_original_model(", "fn recover_original_model(",
            "fn commit_original_model(", "fn read_original_model(",
        ):
            with self.subTest(function=function):
                self.mutate(LANE, function, "self.require_model_context(context)?;")
        self.mutate(
            LANE, "fn read_original_model(",
            "SourceBoundCellQ24TrainingStageV1::read_model_from_current_evaluation(",
            "SourceBoundCellQ24TrainingStageV1::commit_model_from_current_evaluation(",
        )
        self.mutate(
            LANE, "fn require_model_context(",
            "self.context.verifier.objective_digest()\n                != context.material.verifier.objective_digest()",
            "false",
        )
        for path in (LANE, ADMISSION, OWNER):
            with self.subTest(callback=path):
                self.assert_rejected(path, (ROOT / path).read_text() + "\nfn callback() { material.read_current(); }\n")

    def test_admission_requires_the_actual_candidate_qualified_material_and_current_time(self):
        for marker, replacement in (
            ("training_cut.request != dataset_cut.request", "false"),
            ("original_binding(dataset_cut, &original) != owner_binding", "false"),
            ("if current < now", "if current > now"),
            (".require_original_model_input(training_cut, training_attestation, current)", ".require_original_model_input(training_cut, training_attestation, now)"),
            ("input.candidate() != candidate", "false"),
            ("LearningEvaluationDispositionV1::Qualified", "LearningEvaluationDispositionV1::NoUpdate"),
        ):
            with self.subTest(marker=marker):
                self.mutate(ADMISSION, "fn validate_current_material<", marker, replacement)

    def test_model_creation_and_explicit_recovery_preserve_original_witness_and_fresh_auth(self):
        self.mutate(OWNER, "fn create_from_current_material<", "witness.current()?.is_some()", "witness.current()?.is_none()")
        self.mutate(OWNER, "fn create_from_current_material<", "require_material(material, started, fresh)?;")
        self.mutate(
            OWNER, "fn create_from_current_material<",
            "fresh >= dataset.request.envelope.expiry_unix_seconds",
            "fresh > dataset.request.envelope.expiry_unix_seconds",
        )
        self.mutate(OWNER, "fn recover_from_current_material<", "require_material(material, started, current_time()?)?;")
        self.mutate(OWNER, "fn recover_from_current_material<", "Self::recover_existing_original", "Self::create_empty_original")

    def test_model_commit_readback_and_revalidation_cannot_silently_reset_uncertainty(self):
        for marker, replacement in (
            ("self.require_current()?;", ""),
            ("require_material(material, started, fresh)?;", ""),
            ("self.fenced = true;", "self.fenced = false;"),
            ("return Err(Error::CommitUncertain);", "return Ok(receipt);"),
        ):
            with self.subTest(marker=marker):
                self.mutate(OWNER, "fn commit_current_material_or_readback<", marker, replacement)
        self.mutate(
            OWNER, "fn read_current_material<", "require_material(material, started, self.now()?)?;"
        )
        self.mutate(
            OWNER, "fn admit_current_material<", "require_material(material, started, self.now()?)?;"
        )
        self.mutate(OWNER, "fn current_time(", "SystemTime::now()", "UNIX_EPOCH")
        self.mutate(OWNER, "fn require_material(", "if fresh < started", "if fresh > started")
        self.mutate(OWNER, "fn require_material(", ".authenticate_current(fresh)", ".authenticate_current(started)")

    def assert_actual_binding_domain(self, source):
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        marker = "fn binding("
        self.assertEqual(code.count(marker), 1)
        start = code.index(marker)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        matches = list(re.finditer(r"\blet\s+mut\s+bytes\s*=\s*", code[start:end + 1]))
        self.assertEqual(len(matches), 1, "one actual binding initializer")
        expression_start = start + matches[0].end()
        expression_end = code.index(";", expression_start, end)
        actual = source[expression_start:expression_end].strip()
        self.assertEqual(actual, DOMAIN + ".to_vec()", "actual original Model binding domain")

    def assert_actual_module_paths(self, source):
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        for name, expected in (
            ("effect", '"cell_q24_model_command_effect.rs"'),
            ("service", '"cell_q24_model_command_service.rs"'),
        ):
            pattern = r"#\[\s*path\s*=\s*\]\s*mod\s+" + name + r"\s*;"
            matches = list(re.finditer(pattern, code))
            self.assertEqual(len(matches), 1, (name, "one actual original module"))
            match = matches[0]
            prefix = code[:match.start()]
            self.assertEqual(prefix.count("{") - prefix.count("}"), 0)
            raw = source[match.start():match.end()]
            literal = re.fullmatch(
                r'#\[\s*path\s*=\s*("(?:[^"\\]|\\.)*")\s*\]\s*mod\s+' + name + r"\s*;",
                raw,
            )
            self.assertIsNotNone(literal, "actual original Model module path")
            self.assertEqual(literal.group(1), expected, "actual original Model module path")

    def assert_original_verifier_accepts_masked_literal_decoy(self, path, source):
        # This records the unchanged verifier's exact limitation. The following
        # actual-span QA, not a new verifier capability, rejects the decoy.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": self.rows[path]})

    def test_actual_binding_domain_rejects_same_length_mutation_with_old_text_decoys(self):
        original = (ROOT / CONTEXT).read_text()
        self.assert_actual_binding_domain(original)
        replacement = DOMAIN.replace(".v1", ".v2")
        self.assertEqual(len(DOMAIN), len(replacement))
        self.assertEqual(original.count(DOMAIN), 1)
        changed = original.replace(DOMAIN, replacement, 1)
        for suffix in (
            "\n// " + DOMAIN + "\n",
            "\nconst UNUSED_MODEL_DOMAIN: &[u8] = " + DOMAIN + ";\n",
            "\nfn unused_domain() { let mut bytes = " + DOMAIN + ".to_vec(); }\n",
        ):
            with self.subTest(suffix=suffix):
                candidate = changed + suffix
                self.assert_original_verifier_accepts_masked_literal_decoy(CONTEXT, candidate)
                with self.assertRaisesRegex(AssertionError, "actual original Model binding domain"):
                    self.assert_actual_binding_domain(candidate)

    def test_actual_module_paths_reject_same_length_mutations_and_old_text_decoys(self):
        original = (ROOT / HOST).read_text()
        self.assert_actual_module_paths(original)
        for old, new in (
            ('"cell_q24_model_command_effect.rs"', '"cell_q24_model_command_effecx.rs"'),
            ('"cell_q24_model_command_service.rs"', '"cell_q24_model_command_servicx.rs"'),
        ):
            self.assertEqual(len(old), len(new))
            self.assertEqual(original.count(old), 1)
            changed = original.replace(old, new, 1)
            for suffix in ("", "\n// #[path = " + old + "]\n", "\nconst UNUSED_MODULE_PATH: &str = " + old + ";\n"):
                with self.subTest(path=old, suffix=suffix):
                    candidate = changed + suffix
                    self.assert_original_verifier_accepts_masked_literal_decoy(HOST, candidate)
                    with self.assertRaisesRegex(AssertionError, "actual original Model module path"):
                        self.assert_actual_module_paths(candidate)


if __name__ == "__main__":
    unittest.main()

