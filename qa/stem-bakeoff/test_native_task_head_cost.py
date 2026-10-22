"""Protocol/cost-harness tests; fixture processes are not model-quality evidence."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import native_task_head_cost as cost


SERVICE = '''#!{python}
import hashlib, json, sys, time
mode = {mode!r}
if mode == "stall":
    time.sleep(10)
index = 0
for raw in sys.stdin.buffer:
    request = json.loads(raw)
    p = {{"task_logits": [0.0, 2.0], "task_probabilities": [0.2, 0.8],
         "predicted_class": 1, "accepted": True, "gate": 0.5,
         "mode": "SHADOW_ONLY", "authority": "DENY_ALL"}}
    result = {{"row_index": index, "request_sha256": hashlib.sha256(raw).hexdigest(),
        "source_record_digest": request["source_record_digest"],
        "artifact_sha256": sys.argv[3], "status": "SCORED_RESEARCH_ONLY",
        "prediction": p, "task_admission_allowed": False,
        "action_execution_allowed": False}}
    if mode == "wrong_request": result["request_sha256"] = "a" * 64
    if mode == "wrong_source": result["source_record_digest"] = "a" * 64
    if mode == "wrong_artifact": result["artifact_sha256"] = "a" * 64
    if mode == "wrong_index": result["row_index"] = index + 1
    if mode == "authority": result["action_execution_allowed"] = True
    if mode == "null_prediction": result["prediction"] = None
    if mode == "nonfinite": p["task_logits"][0] = float("nan")
    if mode == "huge_logits": p["task_logits"][0] = 10 ** 400
    if mode == "huge_probs": p["task_probabilities"][0] = 10 ** 400
    if mode == "huge_gate": p["gate"] = 10 ** 400
    if mode == "unstable": p["gate"] = 0.25 if index % 2 else 0.5
    if mode == "wrong_acceptance": p["accepted"] = False
    if mode == "early_exit": sys.exit(4)
    if mode == "oversized":
        sys.stdout.write("x" * (256 * 1024 + 1) + "\\n"); sys.stdout.flush()
        continue
    line = json.dumps(result, separators=(",", ":"))
    if mode == "duplicate": line = line[:-1] + ',"row_index":0}}'
    sys.stdout.write(line + "\\n"); sys.stdout.flush()
    index += 1
if mode == "extra": print("{{}}", flush=True)
'''


class NativeCostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture()

    def fixture(self, mode="normal", width=5):
        self.binary = self.root / "protocol_fixture"
        self.binary.write_text(SERVICE.format(python=Path(sys.executable).resolve(), mode=mode))
        self.binary.chmod(0o700)
        self.weights = self.root / "weights.f32le"
        self.weights.write_bytes(b"\0\0\0\0")
        self.identity = {"encoder_sha256": "e" * 64, "checkpoint_revision": "r" * 40,
                         "preprocess_sha256": "f" * 64, "generation": 1,
                         "scope_id": "fixture", "purpose": "research", "revocation_epoch": 0}
        self.spec = {"schema": "hepta.native-task-head.v1",
            "numeric_profile": "f32-io-f64-accum-gelu-erf-v1", "state_contract": "zero_state_only",
            "authority": "DENY_ALL", "mode": "SHADOW_ONLY", "required_present_mask": 3,
            "feature_layout": "concat-text-image-product-absolute-difference-cosine-v1",
            "feature_identity": self.identity, "width": width, "task_count": 2,
            "confidence_threshold": 0.7, "weights_sha256": cost._sha(self.weights.read_bytes()),
            "weights_bytes": 4}
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(json.dumps(self.spec) + "\n")
        self.requests = self.root / "requests.jsonl"
        self.rows = [{"identity": self.identity, "features": [float(i)] * width,
                      "present_mask": 3, "source_record_digest": hashlib.sha256(str(i).encode()).hexdigest()}
                     for i in range(2)]
        self.write_requests()

    def write_requests(self):
        self.requests.write_bytes(b"".join(json.dumps(row).encode() + b"\n" for row in self.rows))

    def run_cost(self, **changes):
        arguments = dict(binary=self.binary, manifest=self.manifest, weights=self.weights,
            requests=self.requests, expected_manifest_sha256=cost._sha(self.manifest.read_bytes()),
            expected_requests_sha256=cost._sha(self.requests.read_bytes()), warmup=2, samples=4,
            timeout_seconds=3, source_identity={"fixture_only": True})
        arguments.update(changes)
        return cost.run_cost(**arguments)

    def test_live_process_correlates_rows_cycles_input_and_records_measured_units(self):
        receipt = self.run_cost()
        ordered = [cost._sha(line) for line in self.requests.read_bytes().splitlines(keepends=True)] * 2
        self.assertEqual(receipt["measured_ordered_request_digests_sha256"],
                         cost._sha(b"".join(bytes.fromhex(x) for x in ordered)))
        ns = sorted(receipt["latency"]["raw_nanoseconds"])
        self.assertEqual((receipt["latency"]["p50_ms"], receipt["latency"]["p95_ms"],
                          receipt["latency"]["p99_ms"]), (ns[1] / 1e6, ns[3] / 1e6, ns[3] / 1e6))
        self.assertTrue(all(value > 0 for value in ns))
        self.assertEqual(receipt["distinct_executed_requests"], 2)
        self.assertEqual(receipt["requests_sha256"], cost._sha(self.requests.read_bytes()))
        self.assertEqual(receipt["native_binary_sha256"], cost._sha(self.binary.read_bytes()))
        self.assertFalse(receipt["target_device_qualified"])
        self.assertIsNone(receipt["energy_joules"])
        self.assertFalse(receipt["numerical_parity_established_by_this_measurement"])
        self.assertGreater(receipt["wait4_process_lifetime_peak_rss_bytes"], 0)
        # A script's executable is Python, not the hashed script: never relabel its RSS.
        self.assertIsNone(receipt["native_rss_after_measurement"]["rss_bytes"])
        self.assertIsNotNone(receipt["native_rss_after_measurement"]["reason"])

    def test_presence_filter_is_deterministic_and_missing_only_never_launches(self):
        self.rows[0]["present_mask"] = 1
        self.write_requests()
        result = self.run_cost()
        self.assertEqual((result["complete_input_rows"], result["missing_input_rows_excluded_before_measurement"],
                          result["distinct_executed_requests"]), (1, 1, 1))
        self.rows[1]["present_mask"] = 2
        self.write_requests()
        with patch.object(cost.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(cost.NativeCostError, "no complete"):
                self.run_cost()
            launch.assert_not_called()

    def test_digest_and_source_identity_fail_before_process_launch(self):
        with patch.object(cost.subprocess, "Popen") as launch:
            for key in ("expected_manifest_sha256", "expected_requests_sha256"):
                with self.subTest(key=key), self.assertRaisesRegex(cost.NativeCostError, "digest differs"):
                    self.run_cost(**{key: "a" * 64})
            self.rows[0]["identity"] = {**self.identity, "generation": 2}
            self.write_requests()
            with self.assertRaisesRegex(cost.NativeCostError, "identity"):
                self.run_cost()
            launch.assert_not_called()

    def test_bounded_inputs_reject_link_truncation_nonfinite_duplicate_and_oversize(self):
        original = self.requests.read_bytes()
        cases = [original[:-1], original.replace(b"0.0", b"NaN", 1),
                 original.replace(b'"present_mask": 3', b'"present_mask":3,"present_mask":3', 1),
                 b" " * cost.MAX_LINE + b"\n"]
        with patch.object(cost.subprocess, "Popen") as launch:
            for raw in cases:
                with self.subTest(raw_prefix=raw[:20]):
                    self.requests.write_bytes(raw)
                    with self.assertRaises(cost.NativeCostError):
                        self.run_cost()
            self.requests.write_bytes(original)
            link = self.root / "linked.jsonl"
            link.symlink_to(self.requests)
            with self.assertRaisesRegex(cost.NativeCostError, "symlink"):
                self.run_cost(requests=link)
            launch.assert_not_called()

    def test_giant_integer_request_is_denied_before_native_launch(self):
        self.rows[0]["features"][0] = 10 ** 400
        self.write_requests()
        with patch.object(cost.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(cost.NativeCostError, "request feature identity"):
                self.run_cost()
            launch.assert_not_called()

    def test_protocol_corruption_and_authority_never_produce_measurement_receipt(self):
        modes = ("wrong_request", "wrong_source", "wrong_artifact", "wrong_index", "authority",
                 "null_prediction", "nonfinite", "huge_logits", "huge_probs", "huge_gate",
                 "wrong_acceptance", "duplicate", "oversized", "extra", "early_exit")
        for mode in modes:
            with self.subTest(mode=mode):
                self.fixture(mode)
                with self.assertRaises(cost.NativeCostError):
                    self.run_cost()

    def test_non_deterministic_repeated_input_is_detected(self):
        self.fixture("unstable")
        self.rows = self.rows[:1]
        self.write_requests()
        with self.assertRaisesRegex(cost.NativeCostError, "different task prediction"):
            self.run_cost()

    def test_timeout_covers_blocked_large_request_write_and_reaps_child(self):
        self.fixture("stall", width=4093)
        # Whitespace is legal JSON, and this line exceeds a pipe buffer but not the ABI cap.
        raw = json.dumps(self.rows[0]).replace(",", "," + " " * 25).encode() + b"\n"
        self.requests.write_bytes(raw)
        launched = []
        actual = subprocess.Popen
        def launch(*args, **kwargs):
            process = actual(*args, **kwargs)
            launched.append(process)
            return process
        with patch.object(cost.subprocess, "Popen", side_effect=launch):
            with self.assertRaisesRegex(cost.NativeCostError, "timeout"):
                self.run_cost(timeout_seconds=0.1)
        self.assertEqual(len(launched), 1)
        self.assertIsNotNone(launched[0].returncode)

    def test_input_mutation_after_execution_is_detected(self):
        original = cost._response
        mutated = False
        def mutate(*args, **kwargs):
            nonlocal mutated
            value = original(*args, **kwargs)
            if not mutated:
                self.weights.write_bytes(b"\1\0\0\0")
                mutated = True
            return value
        with patch.object(cost, "_response", side_effect=mutate):
            with self.assertRaisesRegex(cost.NativeCostError, "changed during measurement"):
                self.run_cost()

    def test_proc_identity_rejects_wrong_namespace_parent_executable_and_reused_pid(self):
        directory = self.root / "12345"
        directory.mkdir()
        executable = Path(sys.executable).resolve()
        (directory / "exe").symlink_to(executable)
        base = "Pid:\t12345\nPPid:\t4321\nNSpid:\t12345\t7\nVmRSS:\t8 kB\nVmHWM:\t12 kB\n"
        (directory / "status").write_text(base)
        (directory / "stat").write_text("12345 (space name) " + " ".join(["R"] + ["0"] * 18 + ["999"]))
        identity = (directory, 7, 4321, executable, 999)
        self.assertEqual(cost._sample_rss(identity, None),
                         {"rss_bytes": 8192, "post_exec_peak_rss_bytes": 12288, "reason": None})
        for status in (base.replace("PPid:\t4321", "PPid:\t1"),
                       base.replace("12345\t7", "12345\t8"), base.replace("8 kB", "8 MB")):
            (directory / "status").write_text(status)
            self.assertIsNone(cost._sample_rss(identity, None)["rss_bytes"])
        (directory / "status").write_text(base)
        self.assertIsNone(cost._sample_rss((*identity[:-1], 1000), None)["rss_bytes"])
        self.assertIsNone(cost._sample_rss((directory, 7, 4321, self.binary, 999), None)["rss_bytes"])

    def test_real_child_proc_mapping_tracks_post_exec_rss_not_wrong_virtual_pid(self):
        program = ('import sys; print("ready",flush=True); sys.stdin.readline(); '
                   'memory=bytearray(8*1024*1024); print("allocated",flush=True); sys.stdin.readline()')
        child = subprocess.Popen([sys.executable, "-u", "-c", program], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "ready")
            identity, reason = cost._locate_child(child, Path(sys.executable).resolve())
            self.assertIsNotNone(identity, reason)
            before = cost._sample_rss(identity, None)
            child.stdin.write("allocate\n"); child.stdin.flush()
            self.assertEqual(child.stdout.readline().strip(), "allocated")
            after = cost._sample_rss(identity, None)
            self.assertGreater(after["rss_bytes"], before["rss_bytes"] + 4 * 1024 * 1024)
            self.assertGreaterEqual(after["post_exec_peak_rss_bytes"], after["rss_bytes"])
        finally:
            child.communicate("finish\n", timeout=5)


if __name__ == "__main__":
    unittest.main()
