"""Regression tests for executable inference-control evidence navigation."""
import copy
import importlib.util
from pathlib import Path
import unittest
import argparse
import hashlib
import json
import tempfile

PATH = Path(__file__).with_name("hepta-inference-control-current-state.py")
SPEC = importlib.util.spec_from_file_location("inference_current_state", PATH)
STATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STATE)


class CurrentStateTests(unittest.TestCase):
    def setUp(self):
        self.source = STATE.load_json(STATE.SOURCE_PATH)

    def test_current_references_resolve_to_source(self):
        STATE.validate_source(self.source)

    def test_descriptive_non_path_is_not_evidence(self):
        self.source["operations"][0]["tests"] = ["qualification pending exact-head CI"]
        with self.assertRaisesRegex(ValueError, "missing test source"):
            STATE.validate_source(self.source)

    def test_missing_rust_function_is_not_evidence(self):
        self.source["operations"][0]["tests"] = [
            "codex-rs/hepta-infer-core/src/control_contracts.rs::absent_test_function"
        ]
        with self.assertRaisesRegex(ValueError, "missing Rust test"):
            STATE.validate_source(self.source)

    def test_unsafe_paths_are_rejected(self):
        for value in ("../outside.rs", "/etc/passwd"):
            with self.subTest(value=value):
                source = copy.deepcopy(self.source)
                source["operations"][0]["tests"] = [value]
                with self.assertRaisesRegex(ValueError, "unsafe test path"):
                    STATE.validate_source(source)

    def test_map_preserves_external_gates_and_exact_receipt_policy(self):
        mapping = STATE.build_map(self.source)
        self.assertEqual(mapping["sourceIdentityPolicy"], "exact_ci_receipt_v1")
        for field in ("productionImplementation", "productExecutionProved", "targetHostQualification",
                      "independentAcceptance", "activation", "release"):
            self.assertFalse(mapping["claimBoundary"][field])
        self.assertNotIn("observedAtHead", mapping)
        self.assertEqual(mapping["externalEvidenceGates"], self.source["externalEvidenceGates"])


class ReceiptTests(unittest.TestCase):
    def args(self):
        return argparse.Namespace(lane="source-head", source_sha="a" * 40,
            tested_sha="a" * 40, base_sha="b" * 40, candidate_tree="c" * 40)

    def fixtures(self, directory):
        paths = []
        for name in sorted(STATE.OWNER_RECORDS):
            path = Path(directory) / name
            log = path.with_suffix(".log")
            log.write_bytes(b"fixture output, not execution evidence\n")
            args = self.args()
            value = {"source_sha": args.source_sha, "tested_sha": args.tested_sha,
                "base_sha": args.base_sha, "lane": args.lane, "status": "passed", "exit_code": 0,
                "before": {"commit": args.tested_sha, "tree": args.candidate_tree, "dirty": False},
                "after": {"commit": args.tested_sha, "tree": args.candidate_tree, "dirty": False},
                "log_file": log.name, "log_bytes": log.stat().st_size,
                "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
                "timed_out": False, "output_limit_exceeded": False}
            path.write_text(json.dumps(value))
            paths.append(path)
        return paths

    def test_full_record_shape_and_partial_record_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self.fixtures(directory)
            self.assertEqual(STATE.record_failures(paths, self.args()), [])
            self.assertTrue(STATE.record_failures(paths[:-1], self.args()))
            self.assertTrue(STATE.record_failures(paths + paths[:1], self.args()))

    def test_boolean_exit_dirty_identity_and_tampered_log_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self.fixtures(directory)
            original = json.loads(paths[0].read_text())
            for key, value in (("exit_code", False), ("tested_sha", "d" * 40),
                               ("timed_out", True), ("log_file", "../outside")):
                changed = dict(original, **{key: value})
                paths[0].write_text(json.dumps(changed))
                self.assertTrue(STATE.record_failures(paths, self.args()))
            changed = copy.deepcopy(original)
            changed["after"]["dirty"] = True
            paths[0].write_text(json.dumps(changed))
            self.assertTrue(STATE.record_failures(paths, self.args()))
            paths[0].write_text(json.dumps(original))
            paths[0].with_suffix(".log").write_text("changed")
            self.assertTrue(STATE.record_failures(paths, self.args()))


if __name__ == "__main__":
    unittest.main()
