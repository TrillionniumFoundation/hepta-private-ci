import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().with_name("qualify_hepta_ui_native_storage.py")
spec = importlib.util.spec_from_file_location("qualify_hepta_ui_native_storage", SOURCE)
storage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(storage)
SOURCE_SHA = "a" * 40


class StorageQualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.budgets_path = self.root / "budgets.json"
        self.active_path = self.root / "active.json"
        self.retired_path = self.root / "retired.json"
        self.trace_prefix = self.root / "active.strace"
        self.trace = self.root / "active.strace.42"
        storage_root = str(self.root / "durable")
        self.trace.write_text(
            f'write(3<{storage_root}/journal.wal>, "data", 100) = 100\n'
            + f"fsync(3<{storage_root}/journal.wal>) = 0\n" * 12288
            + 'write(1</tmp/unrelated>, "ignore", 99999) = 99999\n'
            f'write(3<{storage_root}/journal.wal>, "failed", 500) = -1 EIO\n',
            encoding="utf-8",
        )
        self.budgets = {
            "status": "provisional-unqualified",
            "measurements": None,
            "productionQualified": False,
            "deploymentQualified": False,
            "releaseAuthorized": False,
            "structural": {
                "maxActiveRecords": 4096,
                "maxSnapshotBytes": 8388608,
                "maxWalBytes": 4194304,
            },
            "performance": {
                "activeRecordsSubject": 4096,
                "retiredIdentitiesSubject": 1000000,
                "freshProcessSamples": 20,
                "coldStartP95Milliseconds": 2000,
                "mutationP50Milliseconds": 25,
                "mutationP95Milliseconds": 100,
                "mutationP99Milliseconds": 250,
                "activePeakRssMiB": 256,
                "millionRetiredPeakRssMiB": 256,
                "millionRetiredIndexRebuildP95Milliseconds": 30000,
                "historyPageP95Milliseconds": 25,
                "historyPageRetainedSerializedBytes": 2097152,
                "maximumWriteAmplificationBytesPerStateTransition": 262144,
            },
        }
        self.active = {
            "schema": "hepta.ui-native-storage-active-evidence.v1",
            "sourceSha": SOURCE_SHA,
            "root": storage_root,
            "activeRecords": 4096,
            "transitions": 12288,
            "mutationP50Milliseconds": 1,
            "mutationP95Milliseconds": 2,
            "mutationP99Milliseconds": 3,
            "mutationSamplesMilliseconds": [1] * 6144 + [2] * 5530 + [3] * 614,
            "snapshotBytes": 4096,
            "walBytes": 2048,
            "peakRssMiB": 64,
            "processSampleCount": 20,
            "measurementScope": {
                "open": storage.OPEN_MEASUREMENT_SCOPE,
                "historyPageBytes": storage.HISTORY_BYTES_MEASUREMENT_SCOPE,
            },
            "freshProcessOpenSamplesMilliseconds": list(range(1, 21)),
            "freshProcessOpenP95Milliseconds": 19,
            "historyPageSize": 64,
            "historyPageSamplesMilliseconds": list(range(1, 21)),
            "historyPageP95Milliseconds": 19,
            "historyPageMaxRetainedJsonBytes": 64000,
        }
        self.retired = {
            "schema": "hepta.ui-native-storage-retirement-evidence.v1",
            "sourceSha": SOURCE_SHA,
            "retiredIdentities": 1000000,
            "deterministicRebuild": True,
            "peakRssMiB": 64,
            "processSampleCount": 20,
            "measurementScope": {"open": storage.OPEN_MEASUREMENT_SCOPE},
            "freshProcessOpenSamplesMilliseconds": list(range(1, 21)),
            "freshProcessOpenP95Milliseconds": 19,
            "freshProcessIndexRebuildSamplesMilliseconds": list(range(1, 21)),
            "freshProcessIndexRebuildP95Milliseconds": 19,
        }
        for evidence, key, kind, base_pid in (
            (self.active, "openProcessSamples", "active-open", 1000),
            (self.retired, "openProcessSamples", "retired-open", 2000),
            (self.retired, "indexRebuildProcessSamples", "retired-rebuild", 3000),
        ):
            evidence[key] = [
                {
                    "schema": "hepta.ui-native-storage-process-sample.v1",
                    "sourceSha": SOURCE_SHA,
                    "kind": kind,
                    "pid": base_pid + index,
                    "elapsedMilliseconds": index + 1,
                    "peakRssMiB": 32,
                }
                for index in range(20)
            ]
        for index, observation in enumerate(self.active["openProcessSamples"]):
            observation.update(
                {
                    "historyPageSize": 64,
                    "historyPageMilliseconds": index + 1,
                    "historyPageRetainedJsonBytes": 64000,
                }
            )

    def validate(self):
        for path, value in (
            (self.budgets_path, self.budgets),
            (self.active_path, self.active),
            (self.retired_path, self.retired),
        ):
            path.write_text(json.dumps(value), encoding="utf-8")
        return storage.validate_storage(
            self.budgets_path,
            self.active_path,
            self.retired_path,
            self.trace_prefix,
            SOURCE_SHA,
        )

    def assert_rejected(self, message):
        with self.assertRaisesRegex(RuntimeError, message):
            self.validate()

    def sample_populations(self):
        return (
            (
                self.active,
                "freshProcessOpenSamplesMilliseconds",
                "freshProcessOpenP95Milliseconds",
            ),
            (
                self.retired,
                "freshProcessOpenSamplesMilliseconds",
                "freshProcessOpenP95Milliseconds",
            ),
            (
                self.retired,
                "freshProcessIndexRebuildSamplesMilliseconds",
                "freshProcessIndexRebuildP95Milliseconds",
            ),
            (
                self.active,
                "historyPageSamplesMilliseconds",
                "historyPageP95Milliseconds",
            ),
        )

    def test_valid_raw_evidence_is_bound_to_hashes_and_nonpromoting_flags(self):
        result = self.validate()
        self.assertEqual(result["activeEvidence"]["measurements"], self.active)
        self.assertEqual(
            result["activeEvidence"]["sha256"], storage.sha256_file(self.active_path)
        )
        self.assertEqual(result["retirementEvidence"]["measurements"], self.retired)
        self.assertEqual(result["durabilitySyscalls"]["writeBytes"], 100)
        self.assertEqual(result["durabilitySyscalls"]["fsyncOrFdatasyncCalls"], 12288)
        self.assertIs(result["storageQualified"], True)
        for flag in ("productionQualified", "deploymentQualified", "releaseAuthorized"):
            self.assertIs(result[flag], False)

    def test_cli_emits_same_validated_result(self):
        expected = self.validate()
        emitted = self.root / "output/qualification.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(SOURCE),
                "--budgets",
                str(self.budgets_path),
                "--active",
                str(self.active_path),
                "--retired",
                str(self.retired_path),
                "--trace-prefix",
                str(self.trace_prefix),
                "--source-sha",
                SOURCE_SHA,
                "--emit",
                str(emitted),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(json.loads(completed.stdout), expected)
        self.assertEqual(json.loads(emitted.read_text(encoding="utf-8")), expected)

    def test_nearest_rank_p95_does_not_use_maximum_sample(self):
        self.active["freshProcessOpenSamplesMilliseconds"][-1] = 3000
        self.active["openProcessSamples"][-1]["elapsedMilliseconds"] = 3000
        self.assertEqual(self.validate()["status"], "pass")

    def test_percentile_substitution_rejected_for_every_population(self):
        for evidence, _, percentile_key in self.sample_populations():
            with self.subTest(percentile=percentile_key, schema=evidence["schema"]):
                evidence[percentile_key] = 1
                self.assert_rejected("nearest-rank p95")
                evidence[percentile_key] = 19

    def test_missing_or_short_sample_arrays_rejected(self):
        for evidence, sample_key, _ in self.sample_populations():
            for samples in (None, [], list(range(19))):
                with self.subTest(sample=sample_key, samples=samples):
                    evidence[sample_key] = samples
                    self.assert_rejected("exactly 20 samples")
            evidence[sample_key] = list(range(1, 21))

    def test_nonfinite_negative_and_boolean_samples_rejected(self):
        for evidence, sample_key, _ in self.sample_populations():
            for invalid in (float("nan"), float("inf"), -1, True, "1"):
                with self.subTest(sample=sample_key, invalid=invalid):
                    evidence[sample_key][0] = invalid
                    self.assert_rejected("not numeric|not a finite non-negative")
            evidence[sample_key][0] = 1

    def test_each_sample_population_obeys_its_budget(self):
        for evidence, sample_key, percentile_key in self.sample_populations():
            original = evidence[sample_key]
            evidence[sample_key] = [40000] * 20
            evidence[percentile_key] = 40000
            self.assert_rejected("exceeded")
            evidence[sample_key], evidence[percentile_key] = original, 19

    def test_insufficient_process_count_and_budget_rejected(self):
        for evidence in (self.active, self.retired):
            evidence["processSampleCount"] = 19
            self.assert_rejected("did not measure 20")
            evidence["processSampleCount"] = 20
        self.budgets["performance"]["freshProcessSamples"] = 19
        self.assert_rejected("at least 20")

    def test_process_observations_require_unique_positive_pids(self):
        for evidence, key in (
            (self.active, "openProcessSamples"),
            (self.retired, "openProcessSamples"),
            (self.retired, "indexRebuildProcessSamples"),
        ):
            observation = evidence[key][0]
            original_pid = observation["pid"]
            for pid in (0, -1, evidence[key][1]["pid"]):
                observation["pid"] = pid
                self.assert_rejected("unique positive")
            observation["pid"] = original_pid

    def test_process_identity_and_elapsed_substitution_rejected(self):
        observation = self.active["openProcessSamples"][0]
        for key, invalid, message in (
            ("schema", "other", "schema mismatch"),
            ("sourceSha", "b" * 40, "source SHA mismatch"),
            ("kind", "retired-open", "kind mismatch"),
            ("elapsedMilliseconds", 2, "summary sample"),
            ("historyPageMilliseconds", 2, "history latency"),
            ("historyPageSize", 32, "page size"),
        ):
            original = observation[key]
            observation[key] = invalid
            self.assert_rejected(message)
            observation[key] = original

    def test_missing_process_observations_rejected(self):
        self.retired["indexRebuildProcessSamples"] = []
        self.assert_rejected("exactly 20 process observations")

    def test_rss_requires_nonnegative_integer_and_respects_each_budget(self):
        for evidence in (self.active, self.retired):
            for invalid in (-1, 1.5, True, float("nan"), 257):
                evidence["peakRssMiB"] = invalid
                self.assert_rejected("negative|not an integer|exceeded")
            evidence["peakRssMiB"] = 64
        self.budgets["performance"]["activePeakRssMiB"] = 63
        self.assert_rejected("active peak RSS exceeded")

    def test_process_rss_cannot_exceed_summary_or_be_negative(self):
        for invalid in (-1, 65):
            self.active["openProcessSamples"][0]["peakRssMiB"] = invalid
            self.assert_rejected("RSS is negative or exceeds")

    def test_history_bytes_are_positive_bounded_and_bound_to_observations(self):
        for invalid in (0, -1, True, 2097153):
            self.active["historyPageMaxRetainedJsonBytes"] = invalid
            self.assert_rejected("not positive|not an integer|exceeded")
        self.active["historyPageMaxRetainedJsonBytes"] = 64001
        self.assert_rejected("retained-byte summary")

    def test_history_scope_and_page_size_are_explicit(self):
        self.active["historyPageSize"] = 63
        self.assert_rejected("64-record page")
        self.active["historyPageSize"] = 64
        self.active["measurementScope"]["historyPageBytes"] = "allocator-accounting"
        self.assert_rejected("serialized receipts")

    def test_open_scope_cannot_claim_controlled_page_cache(self):
        for evidence in (self.active, self.retired):
            evidence["measurementScope"]["open"] = "cold-cache"
            self.assert_rejected("uncontrolled OS page cache")
            evidence["measurementScope"]["open"] = storage.OPEN_MEASUREMENT_SCOPE

    def test_foreign_source_and_promoting_budgets_rejected(self):
        self.active["sourceSha"] = "b" * 40
        self.assert_rejected("source SHA mismatch")
        self.active["sourceSha"] = SOURCE_SHA
        for flag in ("productionQualified", "deploymentQualified", "releaseAuthorized"):
            self.budgets[flag] = True
            self.assert_rejected(flag)
            self.budgets[flag] = False

    def test_missing_sync_or_writes_rejected(self):
        self.trace.write_text(
            f'write(3<{self.active["root"]}/journal.wal>, "data", 100) = 100\n'
        )
        self.assert_rejected("no successful fsync")
        self.trace.write_text(f"fsync(3<{self.active['root']}/journal.wal>) = 0\n")
        self.assert_rejected("no successful durable-state writes")

    def test_inflated_short_or_noninteger_transition_counts_rejected(self):
        for invalid in (1_000_000_000_000, 12287, 12289, 0, -1, True, 12288.0):
            with self.subTest(transitions=invalid):
                self.active["transitions"] = invalid
                self.assert_rejected("three transitions per active record|not an integer")

    def test_trace_requires_a_successful_sync_for_every_state_transition(self):
        for sync_count in (1, 12287):
            with self.subTest(sync_count=sync_count):
                self.trace.write_text(
                    f'write(3<{self.active["root"]}/journal.wal>, "data", 100) = 100\n'
                    + f'fsync(3<{self.active["root"]}/journal.wal>) = 0\n' * sync_count,
                    encoding="utf-8",
                )
                self.assert_rejected("fewer successful fsync/fdatasync calls than state transitions")

    def test_raw_mutation_samples_are_complete_finite_and_nonnegative(self):
        original = self.active["mutationSamplesMilliseconds"]
        for samples in (None, [], original[:-1], original + [1]):
            with self.subTest(sample_count=None if samples is None else len(samples)):
                self.active["mutationSamplesMilliseconds"] = samples
                self.assert_rejected("exactly 12288 samples")
        self.active["mutationSamplesMilliseconds"] = original
        for invalid in (float("nan"), float("inf"), -1, True, "1"):
            with self.subTest(sample=invalid):
                original[0] = invalid
                self.assert_rejected("not numeric|not a finite non-negative")
        original[0] = 1

    def test_mutation_percentile_substitution_is_rejected(self):
        for percentile, original in ((50, 1), (95, 2), (99, 3)):
            with self.subTest(percentile=percentile):
                metric = f"mutationP{percentile}Milliseconds"
                self.active[metric] = 0
                self.assert_rejected(f"nearest-rank p{percentile}")
                self.active[metric] = original

    def test_mutation_raw_percentiles_obey_each_performance_ceiling(self):
        for percentile, observed in ((50, 1), (95, 2), (99, 3)):
            with self.subTest(percentile=percentile):
                metric = f"mutationP{percentile}Milliseconds"
                original_budget = self.budgets["performance"][metric]
                self.budgets["performance"][metric] = observed - 0.5
                self.assert_rejected(f"{metric} exceeded")
                self.budgets["performance"][metric] = original_budget

    def test_resumed_state_writes_and_syncs_are_counted(self):
        self.trace.write_text(
            f'write(3<{self.active["root"]}/journal.wal>, "data", 100 <unfinished ...>\n'
            '<... write resumed>) = 100\n'
            f'fsync(3<{self.active["root"]}/journal.wal> <unfinished ...>\n'
            '<... fsync resumed>) = 0\n',
            encoding="utf-8",
        )
        write_bytes, sync_calls, _ = storage.parse_traces(self.trace_prefix, self.active["root"])
        self.assertEqual(write_bytes, 100)
        self.assertEqual(sync_calls, 1)

    def test_root_name_in_stdout_and_similar_prefix_does_not_count(self):
        with self.trace.open("a", encoding="utf-8") as stream:
            stream.write(f'write(1</tmp/stdout>, "{self.active["root"]} fsync(", 999999) = 999999\n')
            stream.write(f'write(3<{self.active["root"]}-foreign/journal.wal>, "foreign", 999999) = 999999\n')
        self.assertEqual(self.validate()["durabilitySyscalls"]["writeBytes"], 100)

    def test_unfinished_state_syscall_cannot_lower_write_amplification(self):
        with self.trace.open("a", encoding="utf-8") as stream:
            stream.write(f'write(3<{self.active["root"]}/journal.wal>, "data", 100 <unfinished ...>\n')
        self.assert_rejected("unfinished durable-state syscall")

    def test_duplicate_json_keys_rejected_including_nested_observations(self):
        self.validate()
        self.active_path.write_text(
            '{"sourceSha": "a", "sourceSha": "b"}', encoding="utf-8"
        )
        with self.assertRaisesRegex(RuntimeError, "duplicate JSON key: sourceSha"):
            storage.load_object(self.active_path)
        self.active_path.write_text(
            '{"samples": [{"pid": 1, "pid": 2}]}', encoding="utf-8"
        )
        with self.assertRaisesRegex(RuntimeError, "duplicate JSON key: pid"):
            storage.load_object(self.active_path)

    @unittest.skipIf(os.name == "nt", "symlink creation requires host privilege")
    def test_raw_evidence_and_trace_symlinks_rejected(self):
        self.validate()
        target = self.root / "real-active.json"
        self.active_path.rename(target)
        self.active_path.symlink_to(target)
        with self.assertRaisesRegex(RuntimeError, "regular non-symlink file"):
            storage.load_object(self.active_path)
        self.trace.unlink()
        self.trace.symlink_to(target)
        with self.assertRaisesRegex(RuntimeError, "regular non-symlink trace"):
            storage.parse_traces(self.trace_prefix, self.active["root"])


if __name__ == "__main__":
    unittest.main()
