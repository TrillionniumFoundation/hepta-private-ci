"""Exercise the checked-in identity gate, including retained failure receipts."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASE = "a" * 40
SOURCE = "b" * 40
MERGE = "c" * 40
TREE = "d" * 40


class ProspectiveMergeIdentityTests(unittest.TestCase):
    def run_gate(
        self,
        *,
        parents=None,
        tree=TREE,
        api_status=0,
        malformed=False,
        merge_status=0,
        timeout=False,
        base=BASE,
    ):
        workflow = (
            ROOT / ".github/workflows/hepta-architecture-convergence.yml"
        ).read_text()
        block = workflow.split(
            "      - name: Verify GitHub prospective merge ref matches this exact candidate\n",
            1,
        )[1].split("      - name:", 1)[0]
        shell = textwrap.dedent(block.split("        run: |\n", 1)[1])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env_file = root / "environment"
            env_file.touch()
            gh = root / "gh"
            gh.write_text(
                "#!/usr/bin/env python3\n"
                + textwrap.dedent("""
                import json, os, sys
                from pathlib import Path
                with Path(os.environ["TRACE"]).open("a") as out:
                    out.write(json.dumps(sys.argv[1:]) + "\\n")
                assert sys.argv[1] == "api"
                assert len(sys.argv) == 3
                if int(os.environ["API_STATUS"]):
                    sys.exit(int(os.environ["API_STATUS"]))
                if os.environ["MALFORMED"] == "1":
                    print("{malformed")
                elif "/git/ref/pull/" in sys.argv[2]:
                    print(json.dumps({"object": {"sha": "c" * 40}}))
                else:
                    assert sys.argv[2].endswith("/git/commits/" + "c" * 40)
                    print(json.dumps({"parents": [{"sha": p} for p in json.loads(os.environ["PARENTS"])],
                                      "tree": {"sha": os.environ["TREE"]}}))
                """)
            )
            gh.chmod(0o700)
            git = root / "git"
            git.write_text(
                "#!/usr/bin/env python3\n"
                + textwrap.dedent("""
                import os, sys
                assert sys.argv[1:] == ["merge-tree", "--write-tree", "a" * 40, "b" * 40]
                print("d" * 40)
                sys.exit(int(os.environ["MERGE_STATUS"]))
                """)
            )
            git.chmod(0o700)
            watchdog = root / "timeout"
            watchdog.write_text(
                "#!/bin/bash\n"
                'test "$1" = --kill-after=5s || exit 97\n'
                'case "$2:$3" in 30s:gh|120s:git) ;; *) exit 98;; esac\n'
                'if [ "$INJECT_TIMEOUT" = 1 ]; then exit 124; fi\n'
                'shift 2\nexec "$@"\n'
            )
            watchdog.chmod(0o700)
            env = dict(
                os.environ,
                PATH=str(root) + os.pathsep + os.environ["PATH"],
                SOURCE_SHA=SOURCE,
                BASE_SHA=base,
                PR_NUMBER="1309",
                REPO="owner/repo",
                RUNNER_TEMP=str(root),
                GITHUB_ENV=str(env_file),
                TRACE=str(root / "trace"),
                PARENTS=json.dumps([BASE, SOURCE] if parents is None else parents),
                TREE=tree,
                API_STATUS=str(api_status),
                MALFORMED=str(int(malformed)),
                MERGE_STATUS=str(merge_status),
                INJECT_TIMEOUT=str(int(timeout)),
            )
            result = subprocess.run(
                ["bash", "-c", shell],
                env=env,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            receipt = json.loads(
                (
                    root / "hepta-command-records/prospective-merge-identity.json"
                ).read_text()
            )
            exports = env_file.read_text()
        self.assertEqual(receipt["exit_code"], result.returncode)
        self.assertEqual(receipt["source_sha"], SOURCE)
        self.assertEqual(receipt["base_sha"], base)
        if result.returncode:
            self.assertFalse(receipt["qualified"])
            self.assertEqual(exports, "")
        return result, receipt, exports

    def test_exact_ordered_parents_and_tree_pass(self):
        result, receipt, exports = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            receipt,
            dict(
                source_sha=SOURCE,
                base_sha=BASE,
                observed_merge_sha=MERGE,
                observed_parents=[BASE, SOURCE],
                observed_tree=TREE,
                expected_tree=TREE,
                stage="verified",
                exit_code=0,
                qualified=True,
            ),
        )
        self.assertEqual(
            exports,
            f"GITHUB_PROSPECTIVE_MERGE_SHA={MERGE}\nGITHUB_PROSPECTIVE_MERGE_TREE={TREE}\n",
        )

    def test_stale_reversed_missing_or_extra_parents_retain_discrepancy(self):
        for parents in (
            ["e" * 40, SOURCE],
            [SOURCE, BASE],
            [BASE],
            [BASE, SOURCE, MERGE],
            [],
        ):
            with self.subTest(parents=parents):
                result, receipt, _ = self.run_gate(parents=parents)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(receipt["observed_parents"], parents)
                self.assertEqual(receipt["stage"], "ordered-parents")

    def test_wrong_tree_never_qualifies(self):
        result, receipt, _ = self.run_gate(tree="e" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt["expected_tree"], TREE)
        self.assertEqual(receipt["observed_tree"], "e" * 40)

    def test_api_failure_malformed_response_and_timeout_retain_failure(self):
        for args in ({"api_status": 7}, {"malformed": True}, {"timeout": True}):
            with self.subTest(args=args):
                result, receipt, _ = self.run_gate(**args)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(receipt["stage"], "merge-ref")

    def test_conflicted_merge_does_not_export_a_candidate(self):
        result, receipt, _ = self.run_gate(merge_status=1)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt["stage"], "expected-tree")

    def test_symbolic_base_is_rejected_without_substituting_live_main(self):
        result, receipt, _ = self.run_gate(base="main")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt["stage"], "inputs")


if __name__ == "__main__":
    unittest.main()
