"""Fixed Root first acceptance and early completed-only ordinary startup."""

from dataclasses import replace
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_historical_task_read_source_closure as route


ROOT = Path(__file__).resolve().parents[2]
A = "codex-rs/hepta-agentd/src/"
PROOF = route.PROOF
NEW = (
    "root_completed_deployment_register", "root_completed_deployment_check",
    "root_completed_deployment_fresh", "root_completed_fresh_plan",
    "root_completed_fresh_freeze_files", "root_completed_observe_all",
    "root_completed_serve_operation", "root_completed_delivery_accept",
)
UNIONS = (
    "root_learning_live_profile_action", "root_initial_run_start_fixed_files",
    "root_original_complete_task_context", "root_original_complete_task_target",
    "root_original_complete_task_observation", "root_original_complete_task_digest",
    "root_original_complete_task_ledger_data", "root_historical_task_read_cold_source",
    "root_historical_task_read_profile", "root_post_a_derive_profile",
    "root_publication_original_initial_data", "root_completed_learning_context",
    "root_completed_learning_same_service",
)


def require_metadata_inside_terminal_attempt(source):
    code, _ = route.function(source, "fn completed_learning_operation(")
    spans = []
    for call, closure in (("CompletedLearningRecord::accept(", "|| {"),
                          ("CompletedLearningRecord::read(", "|fact| {")):
        if code.count(call) != 1:
            raise PROOF.VerificationFailure("one original terminal attempt required")
        begin = code.index(closure, code.index(call))
        end = PROOF._rust_item_end(code, begin)
        if end is None:
            raise PROOF.VerificationFailure("original terminal callback body required")
        spans.append((begin, end))
    for marker in ("fixed.require_original()?", "self.metadata.require_metadata_unchanged()?"):
        calls = list(re.finditer(re.escape(marker), code))
        if len(calls) != 4 or any(
            not any(begin < call.start() < end for begin, end in spans) for call in calls
        ) or any(sum(begin < call.start() < end for call in calls) != 2 for begin, end in spans):
            raise PROOF.VerificationFailure("physical metadata must remain inside both terminal attempts")


def require_ack_install_is_last(source):
    code, _ = route.function(source, "fn accept_original_terminal(")
    marker = "AgentdState::attach_original_q24_terminal_acceptance(state, accepted)?;"
    if code.count(marker) != 1:
        raise PROOF.VerificationFailure("one actual original acknowledgement install required")
    tail = code[code.index(marker) + len(marker):]
    if re.sub(r"\s+", "", tail) != "Ok(())}":
        raise PROOF.VerificationFailure("no fallible operation may follow acknowledgement publication")


class CompletedLearningRouteSourceClosure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def reject(self, file, before, after=""):
        path = A + file + ".rs"
        source = (ROOT / path).read_text()
        self.assertIn(before, source)
        rules = {"protected_file": [r for r in self.manifest["protected_file"] if r["path"] == path]}
        self.assertTrue(rules["protected_file"])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, rules)
            target.write_text(source.replace(before, after, 1))
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, rules)

    def test_root_registers_original_empty_pairs_before_work_and_in_real_context(self):
        for marker in (
            "data.initial != initial.head_digest.to_string()",
            "data.target != target.to_string()",
            "!initial.receipts.is_empty()",
            "data.mode == CompletedMode::Accept",
            "RootCompletedLearningRefusalV1::retain_fresh(",
            "service.with_learning_profile(",
            "historical.phase.load(Ordering::Acquire) != PREPARED",
            "historical.profile.require_original_context(",
            "CompletedFiles::require_empty(&files)?;",
        ):
            with self.subTest(marker=marker):
                self.reject("authority_host_completed_deployment", marker)

    def test_fresh_and_cold_cannot_change_root_fixed_mode_or_repeat_uncertain_attempt(self):
        for marker in (
            "HistoricalReadOperationV1::AcceptCompletedLearning if fixed.is_fresh()",
            "fixed.data.mode == CompletedMode::CaptureRetired",
            "fixed.data.mode == CompletedMode::ReadFinalized",
            "fixed.completion_phase.load(Ordering::Acquire) == 2",
            "compare_exchange(0, 1, Ordering::AcqRel, Ordering::Acquire)",
            "CompletedLearningRecord::accept(",
            "CompletedLearningRecord::read(",
            "fact.deployment != fixed.binding.to_string()",
            "compare_exchange(1, 2, Ordering::AcqRel, Ordering::Acquire)",
            "checked.publication.successor.is_some()",
            "reply.is_empty() || reply.len() > WIRE_BOUND",
        ):
            with self.subTest(marker=marker):
                self.reject("authority_host_completed_provider", marker)

    def test_one_complete_original_task_and_full_context_surround_all_cut_checks(self):
        for marker in (
            "with_original_checkpoint(&config.state_dir,",
            "RootRetainedHistoricalCompleteTaskV1::with_original_historical_task(",
            "fact.checkpoint != checkpoint_digest.to_string()",
            "post_a::PostALearningRuntime::require_completed_plan(",
            "post_a::PostALearningRuntime::with_original_derived_profile(",
            "with_original_completed_b(", "with_original_completed_publication(",
            "CompletedFiles::with_original_records(files, end,",
            "self.with_original_completed_context(",
            "OriginalCompletedBReadV1::observe(b, context)?",
            "OriginalCompletedPublicationReadV1::observe(publication, context)?",
            "verify_original_completions(context, journals, &b, accepted)?",
            "accepted.is_none() && verified.verified_at >= initial.request.envelope.expiry_unix_seconds",
            "accepted.is_some_and(|expected| expected != &fact)",
        ):
            with self.subTest(marker=marker):
                self.reject("authority_host_completed_observation", marker)

    def test_cold_root_cannot_reopen_legacy_learning_or_b_owners(self):
        self.reject("authority_host_historical_read_session",
                    "!super::completed_deployment::CompletedLearningRuntime::is_fresh(completed)", "false")
        self.reject("authority_host_completed_deployment",
                    "self.data.mode == CompletedMode::Accept && self.original.is_some()", "true")
        self.reject("authority_host_post_a_learning",
                    "!self.register || self.metadata.digest().to_string() != deployment", "false")
        self.reject("authority_host_post_a_freeze", "completed.require_same_files(")

    def test_cold_daemon_only_accepts_actual_capsule_before_opening_original_files(self):
        for marker in (
            "if let Some(mode) = data.completed_history",
            "self.post_a_handoffs.is_some()",
            "RootHistoricalTaskReadClientV1::read_original_completed_history(",
            "AgentdConfig::with_original_q24_completed_history(config, Arc::new(original))?",
            "return Ok((self, config));",
            "if self.post_a_handoffs.is_none()",
        ):
            with self.subTest(marker=marker):
                self.reject("production_post_a_q24", marker)
        self.reject("production_post_a_q24", "if let Some(mode) = data.completed_history {",
                    "if let Some(mode) = data.completed_history { let old = OriginalFiles::new()?;")
        self.reject("production_post_a_q24_cli", "historical_learning_model_publication_b[0].is_none()", "false")
        self.reject("production_post_a_q24_cli", "!matches!(owners, 0 | 4)", "false")
        self.reject("production_post_a_q24_handoff", "if count != 4", "if false")

    def test_only_owned_acceptance_enters_the_joined_blocking_job(self):
        self.reject("learning_iteration_historical_source",
                    "RootHistoricalTaskReadClientV1::retain_original_completed_acceptance(")
        for marker in (
            "require_complete(self, snapshot)?;", "require_ready(state).map_err(refused)?;",
            "state.identity() != &self.identity || Instant::now() >= self.end",
            "try_lock()", "take()", "OriginalCompletedLearningAcceptanceV1::accept(",
            "OriginalCompletedLearningAcknowledgementV1::data(&accepted)",
            "data.initial != self.prepared.initial().head_digest.to_string()",
            "data.frozen_scope != self.prepared.scope().binding().to_string()",
            "data.terminal_head != snapshot.head_digest.to_string()",
            "AgentdState::attach_original_q24_terminal_acceptance(state, accepted)?;",
        ):
            with self.subTest(marker=marker):
                self.reject("learning_iteration_terminal_acceptance", marker)
        self.reject("learning_iteration_historical_source", ".accept_original_terminal(&snapshot, &state)")
        self.reject("learning_iteration_terminal_acceptance", "use super::*;",
                    "use super::*; fn detach(read: &OriginalPreparedReadV1<'_>) {}")

    def test_ready_postcheck_and_private_derived_scope_are_preserved(self):
        self.reject("learning_iteration_terminal_acceptance",
                    ".map_err(refused)??;\n        require_ready(state).map_err(refused)?;",
                    ".map_err(refused)??;")
        self.reject("authority_host_post_a_derive",
                    "pub(in super::super) fn with_original_derived_profile<T>(",
                    "pub(crate) fn with_original_derived_profile<T>(")

    def test_no_physical_metadata_observation_escapes_terminal_armed_scope(self):
        source = (ROOT / A / "authority_host_completed_provider.rs").read_text()
        require_metadata_inside_terminal_attempt(source)
        for marker in ("fixed.require_original()?;", "self.metadata.require_metadata_unchanged()?;"):
            for position in ("let initial = self.deployment.initial.original_initial_data()?;",
                             "let reply = if mode == OriginalCompletedPublicationModeV1::AcceptedPublication {"):
                with self.subTest(marker=marker, position=position):
                    self.assertEqual(source.count(position), 1)
                    # Move a real check out of the attempt, preserving its count.
                    mutant = source.replace(marker, "", 1).replace(position, marker + position, 1)
                    with self.assertRaises(PROOF.VerificationFailure):
                        require_metadata_inside_terminal_attempt(mutant)

    def test_actual_ack_install_is_the_final_fallible_step(self):
        source = (ROOT / A / "learning_iteration_terminal_acceptance.rs").read_text()
        require_ack_install_is_last(source)
        marker = "AgentdState::attach_original_q24_terminal_acceptance(state, accepted)?;"
        with self.assertRaises(PROOF.VerificationFailure):
            require_ack_install_is_last(source.replace(marker, marker + "\nrequire_ready(state).map_err(refused)?;", 1))

    def test_actual_new_and_old_closed_calls_are_in_inventory(self):
        selected = [r for r in PROOF._boundary_rows(self.manifest) if r.identifier in NEW + UNIONS]
        self.assertEqual(len(selected), len(NEW + UNIONS))
        paths = {r.definition_path for r in selected} | {p for r in selected for p in r.product_callers}
        index = {p: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / p).read_text())) for p in paths}
        for row in selected:
            with self.subTest(boundary=row.identifier):
                self.assertIn(row.identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, index, ())
                for caller in row.product_callers:
                    if "completed_" not in caller and row.identifier not in NEW:
                        continue
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=tuple(p for p in row.product_callers if p != caller)), index, ())


if __name__ == "__main__":
    unittest.main()
