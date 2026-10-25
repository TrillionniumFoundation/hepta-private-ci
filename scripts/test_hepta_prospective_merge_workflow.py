"""Execute the real workflow gate with local fake gh/git, never GitHub writes."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASE = "f9e047bf3eaa237dda3df8e3765c488ff905908d"
SOURCE = "30ce263c161d03aa7d4d8dc8e33757db96bbe3f3"
MERGE = "7eb8f75735d6d804ab297a04224fd053868a8763"
TREE = "4" * 40
WRONG = "c6784f0e4259cf4fce301691c890caf359961517"
REF = {"ref": "refs/pull/3592/merge", "object": {"type": "commit", "sha": MERGE}}
COMMIT = {
    "sha": MERGE,
    "parents": [{"sha": BASE}, {"sha": SOURCE}],
    "tree": {"sha": TREE},
}


class ProspectiveMergeWorkflowTests(unittest.TestCase):
    def run_gate(self, *, ref=None, commit=None, fail=None, tree=TREE + "\n", env=None):
        workflow = (
            ROOT / ".github/workflows/hepta-architecture-convergence.yml"
        ).read_text()
        block = workflow.split(
            "      - name: Verify GitHub prospective merge ref matches this exact candidate\n",
            1,
        )[1].split("      - name:", 1)[0]
        shell = textwrap.dedent(block.split("        run: |\n", 1)[1])
        responses = {
            "ref-api": [0, json.dumps(REF) if ref is None else ref],
            "commit-api": [0, json.dumps(COMMIT) if commit is None else commit],
            "merge-tree": [0, tree],
        }
        if fail:
            responses[fail] = [7, "fixture partial output"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "responses.json").write_text(json.dumps(responses))
            stub = f"#!{sys.executable}\n" + textwrap.dedent("""
                import json
                import os
                from pathlib import Path
                import sys
                root = Path(os.environ["FIXTURE_ROOT"])
                name = Path(sys.argv[0]).name
                args = sys.argv[1:]
                expected = {
                    ("gh", "api", "repos/fixture/repo/git/ref/pull/3592/merge"): "ref-api",
                    ("gh", "api", "repos/fixture/repo/git/commits/" + os.environ["MERGE"]): "commit-api",
                    ("git", "merge-tree", "--write-tree", os.environ["BASE_SHA"], os.environ["SOURCE_SHA"]): "merge-tree",
                }
                key = expected.get((name, *args))
                if key is None:
                    sys.exit(93)
                retained = json.loads((root / "hepta-command-records/prospective-merge.json").read_text())
                assert retained["stage"] == key and retained["status"] == "failed"
                with (root / "calls.jsonl").open("a") as stream:
                    stream.write(json.dumps([name, *args]) + "\\n")
                code, output = json.loads((root / "responses.json").read_text())[key]
                print(output, end="")
                sys.exit(code)
            """)
            for name in ("gh", "git"):
                path = root / name
                path.write_text(stub)
                path.chmod(0o700)
            variables = dict(
                os.environ,
                BASE_SHA=BASE,
                SOURCE_SHA=SOURCE,
                MERGE=MERGE,
                REPO="fixture/repo",
                PR_NUMBER="3592",
                GH_TOKEN="fixture-secret-not-real",
                RUNNER_TEMP=directory,
                FIXTURE_ROOT=directory,
                GITHUB_ENV=str(root / "env"),
                PATH=directory + os.pathsep + os.environ["PATH"],
            )
            variables.update(env or {})
            result = subprocess.run(
                ["bash", "-c", shell],
                cwd=ROOT,
                env=variables,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            retained = (
                root / "hepta-command-records/prospective-merge.json"
            ).read_text()
            record = json.loads(retained)
            exported = (root / "env").read_text() if (root / "env").exists() else ""
            calls = (
                [
                    json.loads(line)
                    for line in (root / "calls.jsonl").read_text().splitlines()
                ]
                if (root / "calls.jsonl").exists()
                else []
            )
        self.assertLess(len(retained), 2000)
        self.assertNotIn(
            variables["GH_TOKEN"], retained + result.stdout + result.stderr
        )
        self.assertEqual(
            record["expected"]["parents"],
            [variables["BASE_SHA"], variables["SOURCE_SHA"]],
        )
        self.assertLessEqual(len(calls), 3)
        self.assertEqual(len(calls), len({tuple(call) for call in calls}), "no retries")
        if result.returncode:
            self.assertEqual(record["status"], "failed")
            self.assertTrue(record["reason"])
            self.assertIn(
                "::error title=Prospective merge verification::" + record["stage"],
                result.stdout,
            )
            self.assertEqual(exported, "")
        return result, record, exported, calls

    def assert_rejected(self, stage, **kwargs):
        result, record, _, calls = self.run_gate(**kwargs)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(record["stage"], stage)
        return record, calls

    def test_exact_candidate_exports_only_after_all_checks(self):
        result, record, exported, calls = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            record,
            {
                "schema_version": 1,
                "status": "success",
                "stage": "complete",
                "reason": None,
                "expected": {
                    "base_sha": BASE,
                    "source_sha": SOURCE,
                    "parents": [BASE, SOURCE],
                    "tree": TREE,
                },
                "actual": {
                    "sha": MERGE,
                    "commit_sha": MERGE,
                    "parents": [BASE, SOURCE],
                    "parent_count": 2,
                    "parents_truncated": False,
                    "tree": TREE,
                },
            },
        )
        self.assertEqual(
            exported,
            f"GITHUB_PROSPECTIVE_MERGE_SHA={MERGE}\nGITHUB_PROSPECTIVE_MERGE_TREE={TREE}\n",
        )
        self.assertEqual(len(calls), 3)

    def test_each_parent_identity_and_order_is_strict(self):
        for parents, stage in (
            ([WRONG, SOURCE], "base-parent"),
            ([BASE, WRONG], "source-parent"),
            ([SOURCE, BASE], "base-parent"),
        ):
            with self.subTest(parents=parents):
                commit = copy.deepcopy(COMMIT)
                commit["parents"] = [{"sha": value} for value in parents]
                record, calls = self.assert_rejected(stage, commit=json.dumps(commit))
                self.assertEqual(record["actual"]["parents"], parents)
                self.assertEqual(record["actual"]["tree"], TREE)
                self.assertEqual(len(calls), 2)

    def test_parent_count_and_bounded_diagnostics(self):
        for parents in (
            [],
            [BASE],
            [BASE, SOURCE, WRONG],
            [BASE, SOURCE] + [WRONG] * 100,
        ):
            with self.subTest(count=len(parents)):
                commit = copy.deepcopy(COMMIT)
                commit["parents"] = [{"sha": value} for value in parents]
                record, _ = self.assert_rejected(
                    "parent-count", commit=json.dumps(commit)
                )
                self.assertEqual(record["actual"]["parent_count"], len(parents))
                self.assertEqual(record["actual"]["parents"], parents[:3])
                self.assertEqual(
                    record["actual"]["parents_truncated"], len(parents) > 3
                )

    def test_each_command_failure_is_retained(self):
        for stage in ("ref-api", "commit-api", "merge-tree"):
            with self.subTest(stage=stage):
                record, _ = self.assert_rejected(stage, fail=stage)
                self.assertEqual(record["command_exit_code"], 7)

    def test_invalid_truncated_multiple_and_duplicate_json_is_rejected(self):
        for key, good in (("ref", REF), ("commit", COMMIT)):
            duplicate_key = "ref" if key == "ref" else "sha"
            duplicate = (
                json.dumps(good)[:-1]
                + ", "
                + json.dumps(duplicate_key)
                + ": "
                + json.dumps(good[duplicate_key])
                + "}"
            )
            for body in (
                "",
                "null",
                "[]",
                "{}",
                json.dumps(good)[:-1],
                json.dumps(good) * 2,
                duplicate,
                json.dumps(dict(good, truncated=True)),
                json.dumps(dict(good, truncated="unknown")),
                json.dumps(dict(good, truncated=None)),
            ):
                with self.subTest(key=key, body=body):
                    self.assert_rejected(key + "-json", **{key: body})

    def test_ref_identity_and_full_sha_are_required(self):
        for updates in (
            {"ref": "refs/pull/1/merge"},
            {"object": {"sha": MERGE, "type": "tree"}},
            {"object": {"sha": MERGE[:7], "type": "commit"}},
            {"object": {"sha": True, "type": "commit"}},
        ):
            with self.subTest(updates=updates):
                self.assert_rejected("ref-json", ref=json.dumps(dict(REF, **updates)))

    def test_commit_identity_parents_and_tree_shape_are_required(self):
        for updates in (
            {"sha": WRONG},
            {"parents": None},
            {"parents": [{"sha": BASE}, {}]},
            {"parents": [{"sha": BASE}, {"sha": SOURCE[:7]}]},
            {"tree": {}},
            {"tree": {"sha": None}},
        ):
            with self.subTest(updates=updates):
                self.assert_rejected(
                    "commit-json", commit=json.dumps(dict(COMMIT, **updates))
                )

    def test_tree_mismatch_and_unknown_merge_tree_output_are_rejected(self):
        record, _ = self.assert_rejected("tree-match", tree=WRONG + "\n")
        self.assertEqual(record["expected"]["tree"], WRONG)
        self.assertEqual(record["actual"]["tree"], TREE)
        for tree in (
            "",
            TREE[:7],
            TREE + "\nconflicts",
            TREE + " ",
            TREE + "\n" + TREE,
        ):
            with self.subTest(tree=tree):
                self.assert_rejected("merge-tree", tree=tree)

    def test_missing_pr_and_invalid_input_sha_fail_before_api(self):
        for env in ({"PR_NUMBER": ""}, {"BASE_SHA": ""}, {"SOURCE_SHA": SOURCE[:7]}):
            with self.subTest(env=env):
                _, calls = self.assert_rejected("inputs", env=env)
                self.assertEqual(calls, [])

    def test_missing_env_output_keeps_failure_record(self):
        self.assert_rejected(
            "export", env={"GITHUB_ENV": "/nonexistent-prospective-merge-fixture/env"}
        )


if __name__ == "__main__":
    unittest.main()
