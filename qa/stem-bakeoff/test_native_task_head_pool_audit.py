"""Fault regressions for independent pool auditing, not semantic quality tests."""
import copy
from pathlib import Path
import tempfile
import unittest

import audit_native_task_head_pool as audit
import native_task_head_pool as pool
from test_native_task_head_pool import fixture


def observation():
    data, count, artifact, request_sha, references = fixture()
    summary = pool.summarize(data, count, artifact, request_sha, references)
    return data, summary, count, artifact, request_sha, references


class IndependentPoolAuditTests(unittest.TestCase):
    def test_independent_recomputation_accepts_complete_observation(self):
        args = observation()
        self.assertEqual(audit.check_child(*args), 0.0)
        self.assertEqual((args[1]["timings"]["dispatch"]["p99_ms"],
                          args[1]["timings"]["fanout"]["median_ms"]), (0.002, 0.85))

    def test_changed_quantile_sample_or_extra_fanout_tail_is_rejected(self):
        for mutate in (
            lambda data, summary: summary["timings"]["dispatch"].update(p95_ms=0.0),
            lambda data, summary: data["dispatch_nanoseconds"].__setitem__(0, 3000),
            lambda data, summary: summary["timings"]["fanout"].update(p99_ms=1.6),
            lambda data, summary: data["fanout_nanoseconds"].pop(),
        ):
            args = observation()
            mutate(args[0], args[1])
            with self.assertRaisesRegex(ValueError, "timing summary|sample inventory"):
                audit.check_child(*args)

    def test_truncated_predictions_and_reordered_sources_are_not_zip_accepted(self):
        for mutate in (
            lambda data: data["reference_predictions"].pop(),
            lambda data: data["reference_source_record_digests"].reverse(),
            lambda data: data["dispatch_calls_per_head"].__setitem__(0, 0),
        ):
            args = observation()
            mutate(args[0])
            with self.assertRaises(ValueError):
                audit.check_child(*args)

    def test_bool_4096_head_dispatch_counters_fail_independent_audit(self):
        data, _, artifact, request_sha, reference = fixture()
        cells = 4096
        data.update(cells=cells, resident_heads=cells,
                    private_weights_payload_bytes=cells * artifact["weights_bytes"],
                    warmup_calls=cells, fanout_predictions_per_sample=cells,
                    dispatch_calls_per_head=[1] * cells)
        summary = pool.summarize(data, cells, artifact, request_sha, reference)
        self.assertEqual(audit.check_child(data, summary, cells, artifact, request_sha, reference), 0.0)
        data["dispatch_calls_per_head"] = [True] * cells
        with self.assertRaisesRegex(ValueError, "per-Head dispatch counts must be exact integers"):
            audit.check_child(data, summary, cells, artifact, request_sha, reference)

    def test_bool_one_head_headers_fail_independent_audit(self):
        data, _, artifact, request_sha, reference = fixture()
        cells = 1
        data.update(cells=cells, resident_heads=cells,
                    private_weights_payload_bytes=artifact["weights_bytes"],
                    warmup_calls=cells, fanout_predictions_per_sample=cells,
                    dispatch_calls_per_head=[4096])
        summary = pool.summarize(data, cells, artifact, request_sha, reference)
        self.assertEqual(audit.check_child(data, summary, cells, artifact, request_sha, reference), 0.0)
        for key in ("cells", "resident_heads", "independently_trained_templates",
                    "warmup_calls", "fanout_predictions_per_sample"):
            changed = copy.deepcopy(data)
            changed[key] = True
            with self.subTest(field=key):
                with self.assertRaisesRegex(ValueError, "native count must be an exact integer"):
                    audit.check_child(changed, summary, cells, artifact, request_sha, reference)

    def test_fixed_tolerance_allows_numeric_rounding_but_never_decision_change(self):
        reference = fixture()[4][0]["prediction"]
        actual = copy.deepcopy(reference)
        actual["task_logits"][0] += 1e-6
        self.assertLessEqual(audit.prediction_error(actual, reference), audit.TOLERANCE)
        for key, value in (("task_logits", [0.5001, -0.5]), ("gate", float("nan")),
                           ("accepted", 1), ("accepted", False), ("predicted_class", False)):
            changed = copy.deepcopy(actual)
            changed[key] = value
            with self.assertRaises(ValueError):
                audit.prediction_error(changed, reference)

    def test_memory_summary_cannot_hide_different_process_or_hard_limit(self):
        args = observation()
        for phase in ("baseline", "post_load", "post_warmup", "post_measurement"):
            self.assertNotEqual(args[0][phase]["getpid"], args[0][phase]["proc_self_pid"])
        self.assertEqual(audit.check_child(*args), 0.0)
        for key, value in (("proc_self_pid", 201), ("rss_anon_bytes", 40000),
                           ("post_exec_peak_rss_bytes", 100), ("virtual_bytes", audit.MEMORY_BYTES + 1)):
            args = observation()
            args[0]["post_measurement"][key] = value
            args[1]["post_measurement"][key] = value
            with self.assertRaises(ValueError):
                audit.check_child(*args)
        args = observation()
        args[0]["address_space_hard_limit_bytes"] += 1
        with self.assertRaisesRegex(ValueError, "memory enforcement"):
            audit.check_child(*args)

    def test_inconsistent_time_units_and_authority_fail_without_rerunning(self):
        for mutate in (
            lambda data, summary: summary.update(native_elapsed_ms=100000000),
            lambda data, summary: data.update(allocation_nanoseconds=True),
            lambda data, summary: data.update(task_admission_allowed=True),
            lambda data, summary: data.update(new_independent_quality_trial=True),
        ):
            args = observation()
            mutate(args[0], args[1])
            with self.assertRaises(ValueError):
                audit.check_child(*args)

    def test_digest_bound_reader_rejects_file_change_link_and_byte_overflow(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "report.json"
            path.write_bytes(b"first")
            pin = audit.digest(b"first")
            self.assertEqual(audit.checked(path, pin, 5), b"first")
            with self.assertRaises(ValueError):
                audit.checked(path, pin, 4)
            path.write_bytes(b"other")
            with self.assertRaises(ValueError):
                audit.checked(path, pin, 5)
            link = root / "linked.json"
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                audit.checked(link)


if __name__ == "__main__":
    unittest.main()
