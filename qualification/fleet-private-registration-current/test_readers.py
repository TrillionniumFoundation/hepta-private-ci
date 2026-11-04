#!/usr/bin/env python3
"""Controls for rejecting incomplete evidence; these are not product test passes."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from run_native import WINDOWS_FULL_REQUIRED, inventory, require_windows_cases, validate_junit
from run_bazel import complete_shard_counts, libtest_inventory, report_members, test_counts, validate_wrapper_xml


class EvidenceReaderTests(unittest.TestCase):
    def setUp(self):
        self.document = {"test-count": 2, "rust-suites": {"package": {
            "package-name": "package", "kind": "lib", "status": "listed",
            "binary-path": "/not-executed/test",
            "testcases": {name: {"kind": "test", "ignored": False, "filter-match": {"status": "matches"}}
                          for name in ("first", "second")}}}}
        self.listed = inventory(json.dumps(self.document), "package", [])
        self.xml = '<testsuites><testsuite tests="2" failures="0" errors="0"><testcase name="first"/><testcase name="second"/></testsuite></testsuites>'

    def test_complete_inventory_and_junit(self):
        self.assertEqual(validate_junit(self.xml, self.listed)["passed"], 2)

    def test_incomplete_junit_rejected(self):
        with self.assertRaises(RuntimeError):
            validate_junit(self.xml.replace('<testcase name="second"/>', ''), self.listed)

    def test_duplicate_case_rejected(self):
        with self.assertRaises(RuntimeError):
            validate_junit(self.xml.replace('name="second"', 'name="first"'), self.listed)

    def test_unknown_case_rejected(self):
        with self.assertRaises(RuntimeError):
            validate_junit(self.xml.replace('name="second"', 'name="other"'), self.listed)

    def test_failure_skip_and_retry_rejected(self):
        for tag in ("failure", "error", "skipped", "rerunFailure", "rerunError", "flakyFailure", "flakyError"):
            with self.subTest(tag=tag), self.assertRaises(RuntimeError):
                validate_junit(self.xml.replace('<testcase name="second"/>',
                              '<testcase name="second"><' + tag + '/></testcase>'), self.listed)

    def test_zero_run_rejected(self):
        with self.assertRaises(RuntimeError):
            validate_junit('<testsuites><testsuite tests="0"/></testsuites>', self.listed)

    def test_counters_rejected(self):
        with self.assertRaises(RuntimeError):
            validate_junit(self.xml.replace('tests="2"', 'tests="9"'), self.listed)

    def test_filter_is_not_an_ignore(self):
        row = self.document["rust-suites"]["package"]["testcases"]["second"]
        row["filter-match"] = {"status": "mismatch", "reason": "expression"}
        with self.assertRaises(RuntimeError):
            inventory(json.dumps(self.document), "package", [])

    def test_exact_original_ignored_set(self):
        row = self.document["rust-suites"]["package"]["testcases"]["second"]
        row.update({"ignored": True, "filter-match": {"status": "mismatch", "reason": "ignored"}})
        with self.assertRaises(RuntimeError):
            inventory(json.dumps(self.document), "package", [])
        listed = inventory(json.dumps(self.document), "package", ["second"])
        self.assertEqual(listed["expected"], ["first"])
        self.assertEqual(listed["original_ignored"], ["second"])

    def test_wrong_or_unlisted_library_rejected(self):
        for field, value in (("status", "skipped"), ("kind", "test"), ("package-name", "other")):
            doc = copy.deepcopy(self.document)
            doc["rust-suites"]["package"][field] = value
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                inventory(json.dumps(doc), "package", [])

    def test_duplicate_json_key_rejected(self):
        with self.assertRaises(RuntimeError):
            inventory('{"test-count":2,"test-count":2}', "package", [])

    def test_bazel_complete_and_incomplete_results(self):
        good = b"test first ... ok\ntest result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;\n"
        self.assertEqual(test_counts(good, [])["passed"], 1)
        for bad in (b"running 2 tests\ntest first ... ok\n",
                    good.replace(b"1 passed", b"0 passed"),
                    good.replace(b"0 filtered", b"1 filtered"),
                    good + b"test result: FAILED. 1 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out;\n"):
            with self.subTest(raw=bad), self.assertRaises(RuntimeError):
                test_counts(bad, [])

    def test_bazel_only_original_ignored_names(self):
        log = b"test first ... ok\ntest probe ... ignored\n" + b"test result: ok. 1 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out;\n"
        self.assertEqual(test_counts(log, ["probe"])["original_ignored"], ["probe"])
        with self.assertRaises(RuntimeError):
            test_counts(log, [])



class OriginalShardReaderTests(unittest.TestCase):
    # Explicit FNV-1a partition of eight fixed names, independently enumerated
    # against the committed shell launcher's documented algorithm.
    PARTITION = [("case1", "case5"), ("case2", "case6"),
                 ("case3", "case7"), ("case0", "case4")]

    def setUp(self):
        self.listed = [f"case{index}" for index in range(8)]
        self.logs = [self.log(names) for names in self.PARTITION]

    @staticmethod
    def log(names):
        return ("".join(f"test {name} ... ok\n" for name in names) +
                f"test result: ok. {len(names)} passed; 0 failed; 0 ignored; "
                f"0 measured; {8 - len(names)} filtered out;\n").encode()

    def test_all_four_shards_cover_actual_inventory(self):
        result = complete_shard_counts(self.logs, self.listed, [])
        self.assertEqual(result["passed"], 8)
        self.assertTrue(result["complete_disjoint_coverage"])

    def test_missing_or_duplicate_shard_is_rejected(self):
        for logs in (self.logs[:-1], self.logs + self.logs[:1],
                     [self.logs[0], self.logs[0], *self.logs[2:]]):
            with self.subTest(logs=logs), self.assertRaises(RuntimeError):
                complete_shard_counts(logs, self.listed, [])

    def test_correct_total_with_wrong_shard_assignment_is_rejected(self):
        with self.assertRaises(RuntimeError):
            complete_shard_counts([self.logs[1], self.logs[0], *self.logs[2:]], self.listed, [])

    def test_inventory_omission_or_extra_name_is_rejected(self):
        for listed in (self.listed[:-1], self.listed + ["unexpected"], self.listed + [self.listed[0]]):
            with self.subTest(listed=listed), self.assertRaises(RuntimeError):
                complete_shard_counts(self.logs, listed, [])

    def test_wrong_filter_counter_is_rejected(self):
        with self.assertRaises(RuntimeError):
            complete_shard_counts([self.logs[0].replace(b"6 filtered", b"0 filtered"), *self.logs[1:]],
                                  self.listed, [])

    def test_missing_or_retried_summary_is_rejected(self):
        for first in (self.logs[0].split(b"test result:")[0], self.logs[0] + self.logs[0]):
            with self.subTest(first=first), self.assertRaises(RuntimeError):
                complete_shard_counts([first, *self.logs[1:]], self.listed, [])

    def test_pass_count_cannot_replace_actual_case_rows(self):
        with self.assertRaises(RuntimeError):
            complete_shard_counts([self.logs[0].replace(b"test case1 ... ok\n", b""), *self.logs[1:]],
                                  self.listed, [])

    def test_original_ignored_identity_is_checked(self):
        changed = self.logs[0].replace(b"case1 ... ok", b"case1 ... ignored").replace(
            b"2 passed; 0 failed; 0 ignored", b"1 passed; 0 failed; 1 ignored")
        logs = [changed, *self.logs[1:]]
        self.assertEqual(complete_shard_counts(logs, self.listed, ["case1"])["passed"], 7)
        with self.assertRaises(RuntimeError):
            complete_shard_counts(logs, self.listed, [])
        with self.assertRaises(RuntimeError):
            complete_shard_counts(logs, self.listed, ["case5"])

    def test_list_inventory_rejects_duplicate_empty_and_benchmarks(self):
        self.assertEqual(libtest_inventory(b"case0: test\ncase1: test\n"), ["case0", "case1"])
        self.assertEqual(libtest_inventory(b"", allow_empty=True), [])
        for raw in (b"", b"case0: test\ncase0: test\n", b"case0: benchmark\n"):
            with self.subTest(raw=raw), self.assertRaises(RuntimeError):
                libtest_inventory(raw)

    def test_report_layout_requires_exact_fresh_shard_set(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for index in range(4):
                shard = directory / f"shard_{index + 1}_of_4"
                shard.mkdir()
                (shard / "test.log").write_bytes(self.logs[index])
                (shard / "test.xml").write_text("<testsuite tests='1'><testcase name='wrapper'/></testsuite>")
            self.assertEqual(len(report_members(directory, 4)), 4)
            missing = directory / "shard_4_of_4/test.xml"
            missing.unlink()
            with self.assertRaises(RuntimeError):
                report_members(directory, 4)
            missing.write_text("<testsuite tests='1'><testcase name='wrapper'/></testsuite>")
            retry = directory / "shard_1_of_4/test_attempts"
            retry.mkdir()
            (retry / "test.log").write_bytes(self.logs[0])
            with self.assertRaises(RuntimeError):
                report_members(directory, 4)

    def test_wrapper_xml_cannot_hide_failure_skip_or_retry(self):
        good = b"<testsuite tests='1'><testcase name='wrapper'/></testsuite>"
        validate_wrapper_xml(good)
        for tag in ("failure", "error", "skipped", "rerunFailure", "flakyFailure"):
            bad = good.replace(b"<testcase name='wrapper'/>",
                               ("<testcase name='wrapper'><" + tag + "/></testcase>").encode())
            with self.subTest(tag=tag), self.assertRaises(RuntimeError):
                validate_wrapper_xml(bad)



class ComposedWindowsCoverageControls(unittest.TestCase):
    def test_fleet_requires_exact_full_case_name(self):
        name = next(iter(WINDOWS_FULL_REQUIRED["codex-hepta-fleet"]))
        require_windows_cases({"expected": [name]}, "codex-hepta-fleet")
        with self.assertRaisesRegex(RuntimeError, "full Windows case"):
            require_windows_cases({"expected": ["wrong::" + name.rsplit("::", 1)[-1]]},
                                  "codex-hepta-fleet")

    def test_each_original_agentd_failure_is_mandatory(self):
        names = sorted(WINDOWS_FULL_REQUIRED["codex-hepta-agentd"])
        require_windows_cases({"expected": names}, "codex-hepta-agentd")
        for missing in names:
            with self.subTest(missing=missing), self.assertRaises(RuntimeError):
                require_windows_cases({"expected": [name for name in names if name != missing]},
                                      "codex-hepta-agentd")

    def test_new_creation_controls_cannot_be_replaced_by_legacy_suffixes(self):
        from run_native import WINDOWS_REQUIRED
        legacy = ["existing::" + name for name in WINDOWS_REQUIRED["codex-utils-path"]]
        complete = legacy + sorted(WINDOWS_FULL_REQUIRED["codex-utils-path"])
        require_windows_cases({"expected": complete}, "codex-utils-path")
        with self.assertRaisesRegex(RuntimeError, "full Windows case"):
            require_windows_cases({"expected": legacy}, "codex-utils-path")

    def test_explicit_groups_preserve_the_complete_original_memory_set(self):
        from common import BAZEL_GROUPS, BAZEL_SHARDS, NATIVE_GROUPS
        self.assertEqual(NATIVE_GROUPS["retained-memory"],
                         ("codex-utils-path", "codex-state", "codex-hepta-memory"))
        self.assertEqual(set(NATIVE_GROUPS["path-fleet"]),
                         {"codex-utils-path", "codex-hepta-fleet"})
        self.assertEqual(NATIVE_GROUPS["agentd"], ("codex-hepta-agentd",))
        self.assertEqual(BAZEL_SHARDS["retained-memory"], {"path": 1, "state": 4, "memory": 1})
        self.assertEqual(set(BAZEL_GROUPS["fleet-owner"]), {"path", "fleet", "agentd"})



class OriginalUnixSubprocessCoverageControls(unittest.TestCase):
    def setUp(self):
        from common import HERE, OBJECTIVE_SENDER_CHILD, OBJECTIVE_SENDER_PARENTS
        self.config = json.loads((HERE / "scope.json").read_bytes())
        self.child = OBJECTIVE_SENDER_CHILD
        self.parents = OBJECTIVE_SENDER_PARENTS
        self.all_cases = sorted(self.parents | {self.child, "ordinary_case"})
        self.expected = sorted(self.parents | {"ordinary_case"})

    def test_unix_keeps_original_probes_and_exact_subprocess_fixture(self):
        from common import memory_ignored_cases, require_memory_process_cases
        original = self.config["original_ignored_memory_cases"]
        for system in ("Linux", "Darwin"):
            self.assertEqual(memory_ignored_cases(self.config, system),
                             sorted([*original, self.child]))
            require_memory_process_cases(self.all_cases, self.expected, system)
        for name in (self.child + "_other", next(iter(self.parents))):
            changed = copy.deepcopy(self.config)
            changed["original_ignored_memory_unix_subprocess_cases"] = [name]
            with self.assertRaises(RuntimeError):
                memory_ignored_cases(changed, "Linux")

    def test_each_original_parent_is_required_and_cannot_be_an_ignored_pass(self):
        from common import require_memory_process_cases
        for parent in self.parents:
            selected = [name for name in self.expected if name != parent]
            with self.subTest(parent=parent), self.assertRaises(RuntimeError):
                require_memory_process_cases(self.all_cases, selected, "Linux")
        with self.assertRaises(RuntimeError):
            require_memory_process_cases(self.all_cases, self.all_cases, "Linux")
        wrong = [name.replace("production_writer::", "other_owner::") for name in self.expected]
        with self.assertRaises(RuntimeError):
            require_memory_process_cases(self.all_cases, wrong, "Darwin")

    def test_windows_preserves_original_seven_and_rejects_unix_case_inventory(self):
        from common import memory_ignored_cases, require_memory_process_cases
        self.assertEqual(memory_ignored_cases(self.config, "Windows"),
                         sorted(self.config["original_ignored_memory_cases"]))
        require_memory_process_cases(["ordinary_case"], ["ordinary_case"], "Windows")
        for name in self.parents | {self.child}:
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                require_memory_process_cases(["ordinary_case", name], ["ordinary_case"], "Windows")

    def test_unknown_hosts_and_replacing_original_probes_are_rejected(self):
        from common import memory_ignored_cases, require_memory_process_cases
        with self.assertRaises(RuntimeError):
            memory_ignored_cases(self.config, "Other")
        with self.assertRaises(RuntimeError):
            require_memory_process_cases(self.all_cases, self.expected, "Other")
        for name in self.parents | {self.child}:
            changed = copy.deepcopy(self.config)
            changed["original_ignored_memory_cases"].append(name)
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                memory_ignored_cases(changed, "Linux")

if __name__ == "__main__":
    unittest.main()
