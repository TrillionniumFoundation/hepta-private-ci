"""Source-only counterexamples for ACK observation; not a native Root/C proof."""

from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import verify_hepta_callers as PROOF

SOURCE = "codex-rs/hepta-agentd/src/circuit_feature_learning_source.rs"
CURRENT = "codex-rs/hepta-agentd/src/root_generation_current_client.rs"


def function_span(text, function):
    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(text))
    marker = "fn " + function + "("
    if code.count(marker) != 1:
        raise PROOF.VerificationFailure("one real function required")
    start = code.index(marker)
    end = PROOF._rust_item_end(code, start)
    if end is None:
        raise PROOF.VerificationFailure("real function body required")
    return start, end + 1, code[start:end + 1]


def require_observation_structure(text):
    _, _, body = function_span(text, "observe_original_after_ack")
    if re.search(r"\b(?:objective_start_once(?:_until)?|send_once|submit)\s*\(", body):
        raise PROOF.VerificationFailure("ACK observation cannot redispatch ingress")
    match = re.search(r"Ok\s*\(\s*_\s*\)\s*=>\s*\{", body)
    if match is None:
        raise PROOF.VerificationFailure("completed publication branch required")
    if re.search(r"\brequire_current\s*\(", body[:match.start()]):
        raise PROOF.VerificationFailure("unfinished source cannot read Root CURRENT")


class FeatureAckObservationSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def reject(self, path, function, change):
        source = (ROOT / path).read_text()
        start, end, _ = function_span(source, function)
        changed_body = change(source[start:end])
        self.assertNotEqual(changed_body, source[start:end])
        changed = source[:start] + changed_body + source[end:]
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)

            def verify(text):
                target.write_text(text)
                PROOF._verify_protected_files(root, {"protected_file": rows})
                if path == SOURCE:
                    require_observation_structure(text)

            verify(source)
            with self.assertRaises(PROOF.VerificationFailure):
                verify(changed)

    def test_current_read_never_precedes_completed_source(self):
        def move_before_source(body):
            start = body.index("cell.task.require_current()")
            end = body.index("})?;", start) + len("})?;")
            check = body[start:end]
            body = body[:start] + body[end:]
            marker = "match source.read_run_publication("
            self.assertIn(marker, body)
            return body.replace(marker, check + "\n" + marker, 1)

        self.reject(SOURCE, "observe_original_after_ack", move_before_source)

    def test_completed_branch_keeps_current_capture_and_exact_admission(self):
        for marker in (
            "cell.task.require_current()",
            "OriginalCircuitFeatureLearningSourcesV1::capture",
            ".require_original_admission(&expected)",
        ):
            with self.subTest(marker=marker):
                self.reject(SOURCE, "observe_original_after_ack",
                            lambda body, marker=marker: body.replace(marker, "removed_check", 1))

    def test_only_reconciliation_waits_and_other_errors_propagate(self):
        self.reject(SOURCE, "observe_original_after_ack", lambda body: body.replace(
            "Err(crate::CircuitTaskErrorV1::ReconciliationRequired)",
            "Err(crate::CircuitTaskErrorV1::ReconciliationRequired | crate::CircuitTaskErrorV1::Unavailable)", 1))
        self.reject(SOURCE, "observe_original_after_ack", lambda body: body.replace(
            "Err(invalid(error))", "Ok(None)", 1))

    def test_observation_cannot_redispatch_or_remove_original_deadline(self):
        self.reject(SOURCE, "observe_original_after_ack", lambda body: body.replace(
            "loop {", "loop { self.client.objective_start_once(retry).await?;", 1))
        self.reject(SOURCE, "observe_original_after_ack", lambda body: body.replace(
            "Instant::now() >= deadline", "false", 1))
        self.reject(SOURCE, "submit_with_original_end", lambda body: body.replace(
            ".min(Duration::from_secs(60))", "", 1))

    def test_root_lane_contention_keeps_nonblocking_permanent_fence(self):
        self.reject(CURRENT, "exchange_response", lambda body: body.replace(
            "self.lane.try_lock()", "self.lane.lock()", 1))
        self.reject(CURRENT, "exchange_response", lambda body: body.replace(
            "self.fenced.store(true, Ordering::Release)",
            "self.fenced.store(false, Ordering::Release)", 1))

        def postpone_fence_until_after_diagnostic(body):
            fence = "self.fenced.store(true, Ordering::Release);"
            body = body.replace(fence, "", 1)
            marker = "uncertain()\n        })?;"
            self.assertIn(marker, body)
            return body.replace(marker, fence + "\n" + marker, 1)

        self.reject(CURRENT, "exchange_response", postpone_fence_until_after_diagnostic)

    def test_existing_source_cell_and_signature_rereads_remain_required(self):
        cases = (
            ("capture", "cell.committed(&publication)?"),
            ("capture", "result.require_current()?"),
            ("require_current", "self.cell.committed(&before)?"),
            ("require_current", "self.cell.task.require_current()"),
            ("require_original_admission", "self.publication.original_record().authentication != expected"),
        )
        for function, marker in cases:
            with self.subTest(function=function, marker=marker):
                self.reject(SOURCE, function,
                            lambda body, marker=marker: body.replace(marker, "removed_check", 1))


if __name__ == "__main__":
    unittest.main()
