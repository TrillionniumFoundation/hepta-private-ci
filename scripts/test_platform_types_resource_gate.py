"""Verifier regressions use synthetic samples; they are not performance evidence."""
import copy
import unittest

from platform_types_resource_gate import CASES, METHODOLOGY_PATHS, evaluate


def fixture():
    rows = []
    for name in CASES:
        calls, size = (128, 10240)
        if name.startswith("hash-streaming"):
            calls, size = 64, 512
        if name.startswith(("registry-identity", "registry-digest")):
            calls, size = 0, 0
        for sample in range(17):
            rows.append(dict(case=name, sample=sample, iterations=64,
                             elapsedNs=64000 + sample, allocationCalls=calls,
                             reallocations=0, requestedBytes=size))
    return dict(schema="hepta.platform-types.semantic-benchmark.v1", samplesPerCase=17,
                iterationsPerSample=64, allocationMetric="successful-global-allocation-and-reallocation-requested-bytes",
                timingAuthority="diagnostic-only", rows=rows)


def check(raw, **kwargs):
    return evaluate(raw, "a" * 40, "b" * 40, {"host": "test-only"}, "c" * 64, **kwargs)


class ResourceGateTests(unittest.TestCase):
    def test_methodology_fingerprint_covers_measurement_and_interpretation(self):
        expected = (
            "codex-rs/hepta-types/src/bin/platform-types-semantic-bench.rs",
            "codex-rs/hepta-types/src/bin/semantic_bench_support/allocator.rs",
            "scripts/platform_types_resource_gate.py",
            "scripts/run_platform_types_resource_qualification.sh",
        )
        self.assertEqual(METHODOLOGY_PATHS, expected)
        self.assertEqual(check(fixture())["methodologyFiles"], list(expected))

    def test_valid_sample_shape_preserves_nonclaims(self):
        report = check(fixture())
        self.assertEqual(report["allocationGate"], "passed")
        self.assertEqual(report["latencyGate"], "not_requested")
        self.assertFalse(report["targetHostQualified"])
        self.assertFalse(report["productActivation"])

    def test_rejects_missing_duplicate_unknown_and_boolean_samples(self):
        for mutation in (
            lambda v: v["rows"].pop(),
            lambda v: v["rows"].__setitem__(0, copy.deepcopy(v["rows"][1])),
            lambda v: v["rows"][0].__setitem__("case", "unknown"),
            lambda v: v["rows"][0].__setitem__("elapsedNs", True),
            lambda v: v["rows"][0].__setitem__("elapsedNs", 0),
            lambda v: v["rows"][0].__setitem__("iterations", 1),
        ):
            raw = fixture()
            mutation(raw)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                check(raw)

    def test_allocation_regression_cannot_be_hidden_by_other_samples(self):
        raw = fixture()
        row = next(row for row in raw["rows"] if row["case"] == "hash-streaming-8")
        row["requestedBytes"] = 10240
        with self.assertRaisesRegex(ValueError, "did not decrease"):
            check(raw)

    def test_lookup_allocation_rejects(self):
        raw = fixture()
        row = next(row for row in raw["rows"] if row["case"] == "registry-digest-256")
        row.update(allocationCalls=1, requestedBytes=8)
        with self.assertRaisesRegex(ValueError, "lookup allocated"):
            check(raw)

    def test_latency_requires_context_methodology_and_explicit_threshold(self):
        baseline = check(fixture())
        report = check(fixture(), baseline=baseline, maximum_ratio=1.15)
        self.assertEqual(report["latencyGate"], "passed")
        for key, value in (("environmentDigest", "0" * 64), ("harnessDigest", "0" * 64)):
            changed = copy.deepcopy(baseline)
            changed[key] = value
            with self.assertRaises(ValueError):
                check(fixture(), baseline=changed, maximum_ratio=1.15)
        changed = copy.deepcopy(baseline)
        changed["methodologyFiles"] = changed["methodologyFiles"][:-1]
        with self.assertRaises(ValueError):
            check(fixture(), baseline=changed, maximum_ratio=1.15)
        for ratio in (None, True, float("nan"), float("inf"), 0.5, 3):
            with self.assertRaises(ValueError):
                check(fixture(), baseline=baseline, maximum_ratio=ratio)

    def test_latency_regression_is_blocking(self):
        baseline = check(fixture())
        raw = fixture()
        for row in raw["rows"]:
            row["elapsedNs"] *= 2
        with self.assertRaisesRegex(ValueError, "latency regression"):
            check(raw, baseline=baseline, maximum_ratio=1.15)


if __name__ == "__main__":
    unittest.main()
