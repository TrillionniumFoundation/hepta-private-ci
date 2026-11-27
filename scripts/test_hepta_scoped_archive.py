"""Reject incomplete archive/replay evidence without building the product."""

import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import hepta_scoped_archive as q


def listing(selected, *, ignored=True):
    cases = {
        f"case_{i}": {
            "ignored": False,
            "filter-match": {"status": "matches"}
            if i in selected
            else {"status": "mismatch", "reason": "partition"},
        }
        for i in range(4)
    }
    if ignored:
        cases["root_fixture"] = {
            "ignored": True,
            "filter-match": {"status": "mismatch", "reason": "ignored"},
        }
    return {
        "test-count": len(cases),
        "rust-suites": {
            "pkg": {
                "package-name": "pkg",
                "binary-id": "pkg",
                "status": "listed",
                "testcases": cases,
            }
        },
    }


def xml(indices):
    return (
        '<testsuites tests="%s" failures="0" errors="0"><testsuite name="pkg" tests="%s">'
        % (len(indices), len(indices))
        + "".join(f'<testcase classname="pkg" name="case_{i}"/>' for i in indices)
        + "</testsuite></testsuites>"
    )


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_original_ignored_and_partition_identities_are_distinct(self):
        full, selected, ignored = q.inventory(listing(range(4)), ["pkg"])
        self.assertEqual(
            (len(full), len(selected), ignored), (5, 4, {("pkg", "root_fixture")})
        )
        part = q.inventory(listing([2]), ["pkg"], partition=True)
        self.assertEqual(part, (full, {("pkg", "case_2")}, ignored))

    def test_ignored_filter_and_incomplete_inventory_refuse(self):
        changes = (
            lambda d: d.update({"test-count": 999}),
            lambda d: d["rust-suites"]["pkg"]["testcases"]["root_fixture"].update(
                {"filter-match": {"status": "matches"}}
            ),
            lambda d: d["rust-suites"]["pkg"].update({"status": "skipped"}),
        )
        for change in changes:
            document = listing(range(4))
            change(document)
            with self.subTest(document=document), self.assertRaises(ValueError):
                q.inventory(document, ["pkg"])

    def test_same_test_name_in_two_binaries_retains_two_identities(self):
        document = listing(range(4))
        second = copy.deepcopy(document["rust-suites"]["pkg"])
        second["binary-id"] = "pkg::integration/second"
        document["rust-suites"][second["binary-id"]] = second
        document["test-count"] *= 2
        _, selected, _ = q.inventory(document, ["pkg"])
        self.assertEqual(len(selected), 8)
        self.assertTrue(
            {("pkg", "case_0"), (second["binary-id"], "case_0")} <= selected
        )

    def test_junit_requires_each_selected_identity_and_reports_retries(self):
        path = self.root / "junit.xml"
        expected = {("pkg", "case_0"), ("pkg", "case_1")}
        path.write_text(
            xml([0, 1]).replace(
                'name="case_0"/>', 'name="case_0"><flakyFailure/></testcase>'
            )
        )
        self.assertEqual(q.junit_passes(path, expected), [("pkg", "case_0", 1)])
        for text in (
            xml([0, 0]),
            xml([0]),
            xml([0, 2]),
            xml([0, 1]).replace(
                'name="case_1"/>', 'name="case_1"><skipped/></testcase>'
            ),
            xml([0, 1]).replace(
                'name="case_1"/>', 'name="case_1"><failure/></testcase>'
            ),
        ):
            path.write_text(text)
            with self.subTest(text=text), self.assertRaises(ValueError):
                q.junit_passes(path, expected)

    def test_runtime_binary_environment_covers_every_package_entry(self):
        target = self.root / "target"
        (target / "debug").mkdir(parents=True)
        bins = {}
        files, environment = {}, {}
        for package, names in {"p1": ["app-server", "host"], "p2": ["fixture"]}.items():
            bins[package] = []
            for name in names:
                path = target / "debug" / name
                path.write_text(name)
                path.chmod(0o755)
                bins[package].append(
                    {"name": name, "kind": "bin-exe", "path": f"debug/{name}"}
                )
                files[name] = {
                    "path": str(path),
                    "bytes": len(name),
                    "sha256": q.digest(path),
                }
                for suffix in {name, name.replace("-", "_")}:
                    environment[f"CARGO_BIN_EXE_{suffix}"] = str(path)
        document = {
            "rust-build-meta": {
                "target-directory": str(target),
                "base-output-directories": ["debug"],
                "non-test-binaries": bins,
            }
        }
        self.assertEqual(
            q.runtime_binaries(document, target),
            {"files": files, "environment": environment},
        )
        for bad in ("/outside/app-server", "debug/../app-server"):
            changed = copy.deepcopy(document)
            changed["rust-build-meta"]["non-test-binaries"]["p1"][0]["path"] = bad
            with self.subTest(path=bad), self.assertRaises(ValueError):
                q.runtime_binaries(changed, target)
        path.unlink()
        with self.assertRaises(ValueError):
            q.runtime_binaries(document, target)

    def test_runtime_binary_alias_collision_and_symlink_refuse(self):
        target = self.root / "target"
        (target / "debug").mkdir(parents=True)
        entries = []
        for name in ("app-server", "app_server"):
            path = target / "debug" / name
            path.write_text(name)
            path.chmod(0o755)
            entries.append({"name": name, "kind": "bin-exe", "path": f"debug/{name}"})
        document = {
            "rust-build-meta": {
                "target-directory": str(target),
                "base-output-directories": ["debug"],
                "non-test-binaries": {"pkg": entries},
            }
        }
        with self.assertRaises(ValueError):
            q.runtime_binaries(document, target)
        document["rust-build-meta"]["non-test-binaries"]["pkg"] = entries[:1]
        (target / "debug/app-server").unlink()
        (target / "debug/app-server").symlink_to(target / "debug/app_server")
        with self.assertRaises(ValueError):
            q.runtime_binaries(document, target)

    def make_evidence(self, groups=None, bad_record=False):
        build, shards = self.root / "build", self.root / "shards"
        build.mkdir()
        shards.mkdir()
        bound = {
            "source_sha": q.SOURCE,
            "source_tree": q.TREE,
            "base_sha": q.BASE,
            "workflow_sha": "workflow",
            "run_id": "run",
            "run_attempt": "1",
            "qualification_helper_sha256": q.digest(Path(q.__file__)),
        }
        q.save(build / "identity.json", bound)
        q.save(
            build / "plan.json",
            {"packages": ["pkg", *[f"other_{i}" for i in range(123)]]},
        )
        q.save(build / "inventory.json", listing(range(4)))
        before = {"commit": q.SOURCE, "tree": q.TREE, "dirty": False}
        stages = ("plan-command.json", "archive-command.json", "helper-command.json")
        for name in stages:
            q.save(
                build / name,
                {
                    "status": "passed",
                    "exit_code": 0,
                    "tested_sha": q.SOURCE,
                    "before": before,
                    "after": before,
                },
            )
        manifest = {
            "status": "built",
            "identity": bound,
            "all_tests": 5,
            "runnable_tests": 4,
            "ignored_tests": 1,
            "records": {name: q.digest(build / name) for name in stages},
            "files": {
                n: {"sha256": q.digest(build / n)}
                for n in ("identity.json", "plan.json", "inventory.json")
            },
        }
        q.save(build / "manifest.json", manifest)
        groups = groups or [[i] for i in range(4)]
        for i, group in enumerate(groups, 1):
            directory = shards / f"shard-{i}"
            directory.mkdir()
            q.save(directory / "inventory.json", listing(group))
            (directory / "junit.xml").write_text(xml(group))
            q.save(
                directory / "runtime-binaries.json", {"files": {}, "environment": {}}
            )
            before = {"commit": q.SOURCE, "tree": q.TREE, "dirty": False}
            q.save(
                directory / "test-command.json",
                {
                    "status": "failed" if bad_record and i == 2 else "passed",
                    "exit_code": 0,
                    "tested_sha": q.SOURCE,
                    "minimum_tests": len(group),
                    "observed_passed_tests": len(group),
                    "observed_failed_tests": 0,
                    "timed_out": False,
                    "output_limit_exceeded": False,
                    "before": before,
                    "after": before,
                },
            )
            q.save(
                directory / "result.json",
                {
                    "status": "passed",
                    "shard": i,
                    "retried": [],
                    "ignored_not_qualified": 1,
                    "partition_excluded": 4 - len(group),
                    "missing": 0,
                    "manifest_sha256": q.digest(build / "manifest.json"),
                    "selected": [["pkg", f"case_{j}"] for j in group],
                    "junit_sha256": q.digest(directory / "junit.xml"),
                    "inventory_sha256": q.digest(directory / "inventory.json"),
                    "record_sha256": q.digest(directory / "test-command.json"),
                    "runtime_binaries_sha256": q.digest(
                        directory / "runtime-binaries.json"
                    ),
                },
            )
        return build, shards

    def summarize(self, build, shards, needs=None):
        with patch.dict(
            os.environ,
            WORKFLOW_SHA="workflow",
            GITHUB_RUN_ID="run",
            GITHUB_RUN_ATTEMPT="1",
        ):
            q.summarize(
                self.root / "summary",
                build,
                shards,
                needs
                or {"archive": {"result": "success"}, "replay": {"result": "success"}},
            )

    def test_complete_disjoint_four_shards_pass(self):
        self.summarize(*self.make_evidence())
        summary = q.load(self.root / "summary/summary.json")
        self.assertEqual(
            (
                summary["runnable_passed"],
                summary["ignored_tests"],
                summary["missing_tests"],
            ),
            (4, [["pkg", "root_fixture"]], 0),
        )

    def test_missing_shard_refuses(self):
        self.summarize_refuses(self.make_evidence(groups=[[0], [1], [2]]))

    def test_equal_counts_with_overlap_and_missing_identity_refuse(self):
        self.summarize_refuses(self.make_evidence(groups=[[0], [1], [1], [3]]))

    def test_failed_original_native_record_refuses_even_when_junit_passes(self):
        self.summarize_refuses(self.make_evidence(bad_record=True))

    def test_skipped_job_refuses(self):
        with self.assertRaises(ValueError):
            self.summarize(
                *self.make_evidence(),
                needs={
                    "archive": {"result": "success"},
                    "replay": {"result": "skipped"},
                },
            )

    def summarize_refuses(self, paths):
        with self.assertRaises(ValueError):
            self.summarize(*paths)
        self.assertFalse((self.root / "summary/summary.json").exists())


if __name__ == "__main__":
    unittest.main()
