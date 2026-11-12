"""The daemon exposes historical DATA only through its actual Root holder."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "q24_completed_history_control_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
CONFIG = AGENT + "config_q24_completed_history.rs"
STATE = AGENT + "state_q24_completed_history.rs"
CLIENT = AGENT + "client_q24_completed_history.rs"
DATA = "codex-rs/hepta-agent-protocol/src/q24_completed_history.rs"


class OriginalCompletedHistoryControlSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def rejects(self, path, function, marker, occurrence=0):
        source = (ROOT / path).read_text()
        start = source.index(function)
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        self.assertIsNotNone(end)
        assert end is not None
        body = source[start:end + 1]
        offset = -len(marker)
        for _ in range(occurrence + 1):
            offset = body.index(marker, offset + len(marker))
        offset += start
        rows = [r for r in self.manifest["protected_file"] if r["path"] == path]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(source[:offset] + source[offset + len(marker):])
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_all_current_slot_and_runtime_protections_are_live(self):
        rows = [
            row for row in self.manifest["protected_file"]
            if row["path"] in (CONFIG, STATE, CLIENT, DATA)
            or any("original_q24_completed_history" in marker
                   for marker in row["required"])
        ]
        self.assertTrue({CONFIG, STATE, CLIENT, DATA, AGENT + "config.rs",
                         AGENT + "state.rs", AGENT + "runtime.rs",
                         AGENT + "state_control.rs"}.issubset({r["path"] for r in rows}))
        PROOF._verify_protected_files(ROOT, {"protected_file": rows})

    def test_only_actual_runtime_and_control_callers_are_registered(self):
        rows = {r.identifier: r for r in PROOF._boundary_rows(self.manifest)}
        expected = {
            "q24_completed_history_config_install": (AGENT + "production_post_a_q24.rs",),
            "q24_completed_history_config_take": (AGENT + "runtime.rs",),
            "q24_completed_history_state_attach": (AGENT + "runtime.rs",),
            "q24_completed_history_state_read": (AGENT + "state_control.rs",),
            "q24_completed_history_client": (),
        }
        paths = {CONFIG, STATE, CLIENT, AGENT + "runtime.rs", AGENT + "state_control.rs",
                 AGENT + "production_post_a_q24.rs"}
        index = {
            p: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / p).read_text()))
            for p in paths
        }
        for identifier, callers in expected.items():
            with self.subTest(identifier=identifier):
                row = rows[identifier]
                self.assertEqual(row.product_callers, callers)
                PROOF._verify_boundary(ROOT, row, index, ())
                if callers:
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=()), index, ())
                unexpected = dict(index)
                unexpected[AGENT + "unregistered_completed_history.rs"] = (
                    "fn bypass() { " + row.symbol + "(); }"
                )
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_boundary(ROOT, row, unexpected, ())

    def test_config_requires_opaque_holder_and_both_actual_root_checks(self):
        function = "fn with_original_q24_completed_history("
        for marker in (
            "completed: Arc<OriginalCompletedLearningHistoryV1>",
            "self.original_q24_completed_history.is_some()",
            ".validate_data()",
            "result?;",
            "self.original_q24_completed_history = Some(completed);",
        ):
            with self.subTest(marker=marker):
                self.rejects(CONFIG, function, marker)
        for occurrence in (0, 1):
            self.rejects(CONFIG, function,
                         "OriginalCompletedLearningHistoryV1::require_original_current(", occurrence)

    def test_config_take_consumes_only_the_original_arc(self):
        self.rejects(CONFIG, "fn take_original_q24_completed_history(",
                     "self.original_q24_completed_history.take()")

    def test_state_attach_cannot_accept_raw_data_or_skip_root_postcheck(self):
        function = "fn attach_original_q24_completed_history("
        for marker in ("completed: Arc<OriginalCompletedLearningHistoryV1>",
                       ".validate_data()", "result?;", ".set(completed)"):
            with self.subTest(marker=marker):
                self.rejects(STATE, function, marker)
        for occurrence in (0, 1):
            self.rejects(STATE, function,
                         "OriginalCompletedLearningHistoryV1::require_original_current(", occurrence)

    def test_query_missing_does_not_become_completed(self):
        for marker in (
            "let Some(completed) = self.original_q24_completed_history.get() else {",
            "return Ok(None);",
        ):
            self.rejects(STATE, "fn read_original_q24_completed_history(", marker)

    def test_query_current_root_and_generation_wrap_even_failed_data_validation(self):
        function = "fn read_original_q24_completed_history("
        for marker in (
            "let data = OriginalCompletedLearningHistoryV1::data(completed).clone();",
            "let result = data.validate_data().map_err(AgentdError::Protocol);",
            "let root_after =",
            "let generation_after = self.require_original_completed_history_current();",
            "root_after?;", "generation_after?;", "result?;",
        ):
            with self.subTest(marker=marker):
                self.rejects(STATE, function, marker)
        for occurrence in (0, 1):
            self.rejects(STATE, function,
                         "OriginalCompletedLearningHistoryV1::require_original_current(", occurrence)

    def test_query_keeps_all_local_current_admission_checks(self):
        for marker in (
            "self.refresh_generation()?;",
            "self.identity.spawn_generation.checked_add(1)",
            "Some(runtime.current_generation) != running_generation",
            "runtime.lifecycle != AgentLifecycle::Running",
            "!runtime.app_server_ready", "!runtime.critical_stores_ready",
            "!runtime.revocation_ready", "!runtime.required_ports_ready",
            "!runtime.admission_open", "runtime.drain_requested", "runtime.fenced",
        ):
            with self.subTest(marker=marker):
                self.rejects(STATE, "fn require_original_completed_history_current(", marker)

    def test_client_has_no_business_parameters_and_rejects_foreign_response(self):
        for marker in (
            "spawn_generation: self.spawn_generation",
            "method: crate::AgentdMethod::OriginalQ24CompletedHistory {}",
            "AgentdPayload::OriginalQ24CompletedHistory { data }",
            "data.validate_data().map_err(AgentdError::Protocol)?;",
            "payload => unexpected(payload)",
        ):
            with self.subTest(marker=marker):
                self.rejects(CLIENT, "fn original_q24_completed_history(", marker)

    def test_digest_shape_cannot_allow_missing_zero_or_noncanonical_history(self):
        for marker in ("self.schema != 1", "value.len() != 64", "byte.is_ascii_digit()",
                       "(b'a'..=b'f').contains(&byte)", "value.bytes().all(|byte| byte == b'0')"):
            with self.subTest(marker=marker):
                self.rejects(DATA, "fn validate_data(", marker)


if __name__ == "__main__":
    unittest.main()
