"""Profiler/fixture regressions. Synthetic executables do not qualify Rust."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from probe_execution import invoke_probe
from resource_profile import measure, parse_dhat, parse_time, read_observation
from resource_workloads import (
    EVENT_PAYLOAD_LIMIT, EVENT_ENVELOPE_LIMIT, PATH_LIMIT,
    boundary_cases, byte_boundary_event, canonical,
)


def maximum_count_fixture():
    # Shape-only fixture for testing the byte builder. Real execution loads the
    # retained golden vector and maximal_memory_event from quality_checks.py.
    digest = "1" * 64
    spans = [{"spanId": f"span:{i:02}", "modality": "text", "assetSha256": digest,
              "range": {"kind": "byte_range", "start": 0, "end": 1},
              "preprocessorManifestSha256": digest, "featureBlobSha256": None,
              "symbolicProjectionSha256": None, "uncertaintyPpm": 0,
              "privacyClass": "agent_private", "redactionMaskSha256": None} for i in range(32)]
    payload = {"eventId": "event:1", "episodeId": "episode:1",
               "scope": {"kind": "agent_private", "agentId": "agent:1"},
               "observedInterval": {"startUnixMs": 1, "endUnixMs": None},
               "modalitySpans": spans,
               "crossModalBindings": [{"bindingId": f"binding:{i:02}", "eventId": "event:1",
                   "spanRefs": ["span:00", "span:01"], "alignmentKind": "same_observation",
                   "confidencePpm": 1_000_000, "producerManifestSha256": digest} for i in range(32)],
               "semanticKeys": [f"key:{i:02}:".ljust(128, "x") for i in range(64)],
               "provenance": [{"sourceId": f"source:{i:02}", "sourceRevision": 1,
                   "sourceSha256": f"{i + 1:064x}", "observedAtUnixMs": i + 1} for i in range(64)],
               "verification": "verified", "retentionPolicy": {"kind": "session"},
               "objectiveDigest": digest, "nduStateDigest": digest,
               "causalParents": [f"causal:{i:02}" for i in range(64)],
               "temporalNeighbors": [f"temporal:{i:02}" for i in range(64)],
               "behaviorPropensityPpm": None, "lifecycle": {"state": "active"}}
    return {"contract": "MemoryEventV1", "schema": "hepta.hnmf.memory-event.v1",
            "schemaVersion": 1, "payload": payload}


def dhat_fixture():
    return {"dhatFileVersion": 2, "mode": "heap", "bklt": True, "tu": "instrs", "tg": 10, "te": 20,
            "pps": [{"tb": 100, "tbk": 10, "mb": 80, "gb": 50, "gbk": 5, "eb": 10, "ebk": 1},
                    {"tb": 200, "tbk": 20, "mb": 150, "gb": 70, "gbk": 7, "eb": 20, "ebk": 2}]}


class ResourceObservations(unittest.TestCase):
    def test_exact_payload_sizes_preserve_registered_field_and_count_bounds(self):
        source = maximum_count_fixture()
        before = copy.deepcopy(source)
        for size in (EVENT_PAYLOAD_LIMIT - 1, EVENT_PAYLOAD_LIMIT, EVENT_PAYLOAD_LIMIT + 1):
            value = byte_boundary_event(source, size)
            self.assertEqual(len(canonical(value["payload"])), size)
            self.assertEqual(len(value["payload"]["modalitySpans"]), 32)
            for span in value["payload"]["modalitySpans"]:
                path = span["range"].get("pointer", span["range"].get("path"))
                self.assertLessEqual(len(path), PATH_LIMIT)
                self.assertTrue(path.startswith("/"))
            self.assertTrue(all(len(binding["spanRefs"]) == 16
                                for binding in value["payload"]["crossModalBindings"]))
        self.assertEqual(source, before)

    def test_payload_and_envelope_boundary_cases_are_not_conflated(self):
        cases = {name: (wire, value, refusal) for name, wire, value, refusal in boundary_cases(maximum_count_fixture())}
        self.assertEqual(len(cases), 7)
        self.assertEqual(len(cases["noncanonical-at-envelope-limit"][0]), EVENT_ENVELOPE_LIMIT)
        self.assertEqual(len(cases["envelope-over-limit"][0]), EVENT_ENVELOPE_LIMIT + 1)
        self.assertEqual(cases["logical-conflict-near-limit"][2], "duplicate_identity")
        mutant = json.loads(cases["logical-conflict-near-limit"][0])["payload"]["provenance"]
        self.assertEqual(mutant[-1]["sourceId"], mutant[-2]["sourceId"])
        self.assertNotEqual(mutant[-1]["sourceSha256"], mutant[-2]["sourceSha256"])

    def test_invalid_boundary_arguments_reject_without_mutating_input(self):
        source = maximum_count_fixture()
        for value in (True, 262144.0, "262144", 0, 1, EVENT_PAYLOAD_LIMIT + 2):
            with self.subTest(value=value), self.assertRaises(ValueError):
                byte_boundary_event(source, value)

    def test_time_units_and_zero_cpu_precision(self):
        result = parse_time(b"0.00\n1.25\n123\n2\n", 2)
        self.assertEqual((result["user_cpu_ns"], result["system_cpu_ns"], result["max_rss_bytes"]),
                         (0, 1_250_000_000, 123 * 1024))

    def test_ambiguous_time_and_wrong_exit_reject(self):
        for value in (b"0\n1.00\n123\n0\n", b"nan\n1.00\n123\n0\n", b"0.00\n1.00\n0\n0\n",
                      b"0.00\n1.00\n123\n2\n", b"0.00\n1.00\n123\n0\nextra\n"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_time(value, 0)
        with self.assertRaises(ValueError):
            parse_time(b"0.00\n1.00\n123\n0\n", False)

    def test_heap_global_peak_is_not_sum_of_independent_point_peaks(self):
        result = parse_dhat(json.dumps(dhat_fixture()).encode())
        self.assertEqual((result["total_allocated_bytes"], result["total_allocated_blocks"],
                          result["global_peak_live_bytes"]), (300, 30, 120))
        self.assertFalse(result["native_latency_measurement"])

    def test_heap_counters_are_strict_and_internally_consistent(self):
        for value in (True, 1.5, "1", -1, 2**64, 101):
            report = dhat_fixture()
            report["pps"][0]["gb"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_dhat(json.dumps(report).encode())

    def test_heap_version_mode_and_duplicate_fields_reject(self):
        for key, value in (("dhatFileVersion", True), ("mode", "rust-heap"), ("bklt", 1), ("tg", 30)):
            report = dhat_fixture()
            report[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                parse_dhat(json.dumps(report).encode())
        with self.assertRaises(ValueError):
            parse_dhat(b'{"dhatFileVersion":2,' + json.dumps(dhat_fixture()).encode()[1:])

    def test_observation_files_reject_symlinks_empty_and_oversize(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observation"
            path.write_bytes(b"12")
            self.assertEqual(read_observation(path, 2), b"12")
            with self.assertRaises(ValueError):
                read_observation(path, 1)
            link = Path(directory) / "link"
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                read_observation(link, 2)
            path.write_bytes(b"")
            with self.assertRaises(ValueError):
                read_observation(path, 2)
            path.unlink()
            os.mkfifo(path)
            with self.assertRaises(ValueError):
                read_observation(path, 2)

    def test_real_time_wrapper_with_synthetic_probe_not_rust(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            probe = root / "synthetic"
            probe.write_text(f"#!{sys.executable}\nimport json,sys\nsys.stdin.buffer.read()\n"
                             "print(json.dumps({'outcome':'accepted','repeat':256,'elapsed_ns':'1'}))\n")
            probe.chmod(0o700)
            result = measure(probe, b"fixture", {"outcome": "accepted"}, None, root / "evidence")
            self.assertGreater(result["metrics"]["max_rss_bytes"], 0)
            self.assertEqual(result["metrics"]["scope"], "whole_probe_process_including_startup")
            with self.assertRaises(FileExistsError):
                measure(probe, b"fixture", {"outcome": "accepted"}, None, root / "evidence")
            with patch("resource_profile.shutil.which", return_value=None), self.assertRaises(ValueError):
                measure(probe, b"fixture", None, "invalid_value", root / "heap", heap=True)

    def test_real_negative_exit_is_measured_but_wrong_refusal_rejects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            probe = root / "synthetic"
            probe.write_text(f"#!{sys.executable}\nimport json,sys\nsys.stdin.buffer.read()\n"
                             "print(json.dumps({'outcome':'rejected','violation':{'code':'invalid_value'}}))\n"
                             "sys.exit(2)\n")
            probe.chmod(0o700)
            result = measure(probe, b"fixture", None, "invalid_value", root / "negative")
            self.assertEqual(result["rejection_scope"], "one decode per process")
            with self.assertRaises(ValueError):
                measure(probe, b"fixture", None, "limit_exceeded", root / "wrong")
            observation = json.loads((root / "wrong/probe-observation.json").read_text())
            self.assertEqual(observation["execution"]["exit_code"], 2)

    def test_probe_leader_exit_cannot_hide_redirected_descendants(self):
        script = ("import subprocess,sys; subprocess.Popen([sys.executable,'-c',"
                  "'import time; time.sleep(60)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
                  "stderr=subprocess.DEVNULL); print('{\"outcome\":\"accepted\"}')")
        result = invoke_probe([sys.executable, "-c", script], b"", {"outcome": "accepted"})
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "infrastructure_invalid")
        self.assertIn("residual descendants", result["error"])


if __name__ == "__main__":
    unittest.main()
