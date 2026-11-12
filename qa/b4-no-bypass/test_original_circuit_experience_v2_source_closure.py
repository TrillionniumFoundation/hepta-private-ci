"""Protect the explicit independent-measurement intake and unchanged V1.

Mutation checks cover source joins, signed custody and the two append fences.
They confer no ordinary execution or daemon/Root recovery qualification.
"""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_experience_v2_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
PATH = "codex-rs/hepta-agentd/src/circuit_experience_intake.rs"
SHARED = "fn append_profile_with_clock("
BOUNDARY = "learning_original_circuit_experience_v2_intake"


class OriginalExperienceV2ClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def verifies(self, source):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == PATH]
        self.assertEqual(len(rows), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / PATH
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})

    def rejects(self, marker, replacement="", function=SHARED, occurrence=0):
        source = (ROOT / PATH).read_text()
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        offset = start
        for _ in range(occurrence + 1):
            chosen = source.index(marker, offset, end + 1)
            offset = chosen + len(marker)
        self.verifies(source)
        changed = source[:chosen] + replacement + source[chosen + len(marker):]
        with self.assertRaises(PROOF.VerificationFailure, msg=f"{function}: {marker}"):
            self.verifies(changed)

    def test_new_intake_has_no_ordinary_caller_or_authority_expansion(self):
        row = self.boundaries[BOUNDARY]
        self.assertEqual(row.product_callers, ())
        self.assertIn(BOUNDARY, self.manifest["privileged_inventory"]["required_boundary_ids"])
        sources = {PATH: PROOF._strip_cfg_test_items(
            PROOF._strip_rust_non_code((ROOT / PATH).read_text())
        )}
        PROOF._verify_boundary(ROOT, row, sources, ())
        extra = dict(sources)
        extra["codex-rs/hepta-agentd/src/unregistered_experience_v2.rs"] = (
            "fn unexpected() { append_original_circuit_experience_v2(); }"
        )
        with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
            PROOF._verify_boundary(ROOT, row, extra, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))
        lib = (ROOT / "codex-rs/hepta-agentd/src/lib.rs").read_text()
        self.assertIn(
            '#[cfg(target_os = "linux")]\npub use '
            'circuit_experience_intake::append_original_circuit_experience_v2;', lib
        )

    def test_v1_and_v2_semantics_remain_explicit_and_cannot_be_interchanged(self):
        self.rejects("OutcomeSupportProfile::SourcePublicationV1,",
                     "OutcomeSupportProfile::IndependentMeasurementV2,",
                     function="fn append_with_clock(")
        self.rejects("OutcomeSupportProfile::IndependentMeasurementV2,",
                     "OutcomeSupportProfile::SourcePublicationV1,",
                     function="fn append_original_circuit_experience_v2(")
        self.rejects("outcome.support_digest != publication.publication_digest()",
                     "outcome.support_digest == publication.publication_digest()")
        self.rejects("outcome.support_digest.is_zero()", "!outcome.support_digest.is_zero()")
        self.rejects("append_with_clock(source, identity, ledger, request, now)",
                     function="fn append_original_circuit_experience_v1<")
        for marker in (
            "OutcomeSupportProfile::SourcePublicationV1 =>",
            "OutcomeSupportProfile::IndependentMeasurementV2 =>",
        ):
            self.rejects(marker)

    def test_actual_source_policy_and_terminal_measurement_joins_are_mandatory(self):
        for marker in (
            ".div_ceil(1_000_000)", "candidates.sort()",
            "circuit_learning_run_id_v1(ledger, &identity.agent_id, &decision.episode_id)",
            "decision.record_id != input.scope.run_id",
            "decision.objective_digest != input.objective_digest",
            "decision.objective_digest != ledger.verifier().objective_digest()",
            "decision.run_snapshot_digest != input.ndu_snapshot_digest",
            "decision.policy_digest != Digest32::of_bytes(publication.output())",
            "decision.support_digest != publication.publication_digest()",
            "decision.candidate_ids != candidates",
            "decision.selected_candidate_id != *policy.selected()",
            "decision.selected_propensity != ProbabilityQ32::ONE",
            "outcome.episode_id != decision.episode_id",
            "outcome.watermark.terminality != OutcomeTerminalityV1::Terminal",
            "outcome.watermark.correction_predecessor.is_some()",
            "outcome.watermark.censoring_reason.is_some()",
            "outcome.observed_at.is_none()", "outcome.watermark.finalized_at.is_none()",
            "outcome.value.is_none()", "admitted_at == 0",
            "outcome.observed_at.is_some_and(|at| at < admitted_at)",
            ".is_some_and(|at| at < outcome.watermark.latest_observable_at)",
        ):
            with self.subTest(marker=marker):
                self.rejects(marker)

    def test_signed_custody_and_actual_owner_fences_cover_both_appends(self):
        for marker in (
            "&decision_signing_payload_v2(decision)?",
            "&outcome_signing_payload_v2(outcome)",
            "verify_signed_independent_roles_v1(&generator, &observer, observed_at)?",
            "generator.principal().principal_id != decision.completeness.generator_id",
            "observer.principal() != &outcome.observer",
            "validate_authenticated_outcome(generator.principal(), outcome, observed_at)",
            "let before = ledger.read_current_durable_snapshot()?",
            "value.record_id != request.outcome.record_id",
            "source.read_run_publication(identity, &decision.record_id)? != publication",
            "if before_decision < observed_at", "let decision = ledger.append_decision(",
            "if before_outcome < before_decision", "let outcome = ledger.append_outcome(",
            "let after = ledger.read_current_durable_snapshot()?",
            "!active.active_records().iter().any(",
            "value.record_id == request.outcome.record_id",
            "value.outcome_id == request.outcome.outcome_id",
            "if fresh_now < before_outcome",
            "&decision_signing_payload_v2(&request.decision)?",
            "&outcome_signing_payload_v2(&request.outcome)",
            "verify_signed_independent_roles_v1(&generator, &observer, fresh_now)?",
        ):
            with self.subTest(marker=marker):
                self.rejects(marker)
        for occurrence in range(2):
            self.rejects(
                "source.read_run_publication(identity, &request.decision.record_id)? != publication",
                occurrence=occurrence,
            )
            self.rejects("ledger.verify_active_decision_binding(", occurrence=occurrence)


    def test_original_rejections_cannot_be_hidden_in_uninvoked_closures(self):
        source = (ROOT / PATH).read_text()
        self.verifies(source)
        for label, first, following, occurrence in (
            ("source and measured outcome", "    if decision.record_id\n", "    // Authenticate BOTH messages", 0),
            ("signed actors", "    if generator.principal().principal_id", "    validate_authenticated_outcome(", 0),
            ("superseded terminal outcome", "    if before.records().iter().any(", "    if source.read_run_publication(identity, &decision.record_id)", 0),
            ("CURRENT before Decision", "    if source.read_run_publication(identity, &decision.record_id)", "    let before_decision = clock()?;", 0),
            ("Decision clock", "    if before_decision < observed_at", "    let decision = ledger.append_decision(", 0),
            ("CURRENT after Decision", "    if source.read_run_publication(identity, &request.decision.record_id)", "    ledger.verify_active_decision_binding(", 0),
            ("Outcome clock", "    if before_outcome < before_decision", "    let outcome = ledger.append_outcome(", 0),
            ("active terminal outcome", "    if !active.active_records().iter().any(", "    if source.read_run_publication(identity, &request.decision.record_id)", 0),
            ("CURRENT after Outcome", "    if source.read_run_publication(identity, &request.decision.record_id)", "    let fresh_now = clock()?;", 1),
            ("final clock", "    if fresh_now < before_outcome", "    let generator = ledger.verifier().verify(", 0),
        ):
            with self.subTest(check=label):
                start = source.index(SHARED)
                for _ in range(occurrence + 1):
                    chosen = source.index(first, start)
                    start = chosen + len(first)
                end = source.index(following, start)
                original = source[chosen:end].rstrip("\n")
                changed = (source[:chosen]
                           + "    let _ = || -> Result<(), Error> {\n"
                           + "\n".join("    " + line for line in original.splitlines())
                           + "\n        Ok(())\n    };\n"
                           + source[end:])
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(changed)


if __name__ == "__main__":
    unittest.main()
