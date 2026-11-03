"""SDK dependency caches must be restored before reuse and saved consistently."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from scripts.hepta_workflow_commands import load_workflow

ROOT = Path(__file__).resolve().parents[1]


class SdkCacheTests(unittest.TestCase):
    def setUp(self):
        workflow = load_workflow((ROOT / ".github/workflows/sdk.yml").read_text())
        self.steps = workflow["jobs"]["sdks"]["steps"]
        self.prepare = load_workflow(
            (ROOT / ".github/actions/prepare-bazel-ci/action.yml").read_text()
        )
        self.restore = next(
            step
            for step in self.prepare["runs"]["steps"]
            if step.get("uses", "").startswith("actions/cache/restore@")
        )
        self.save = next(
            step
            for step in self.steps
            if step.get("uses", "").startswith("actions/cache/save@")
        )

    def setup_step(self):
        matches = [
            step
            for step in self.steps
            if step.get("uses") == "./.github/actions/prepare-bazel-ci"
        ]
        self.assertEqual(len(matches), 1, "SDK must consume the cache-restoring owner")
        return matches[0]

    def resolve_output(self, expression):
        match = re.fullmatch(
            r"\$\{\{\s*steps\.([\w-]+)\.outputs\.([\w-]+)\s*\}\}", expression
        )
        self.assertIsNotNone(match)
        setup = self.setup_step()
        self.assertEqual(match[1], setup["id"])
        self.assertIn(match[2], self.prepare["outputs"])
        return self.prepare["outputs"][match[2]]["value"]

    def test_restore_owner_runs_before_sdk_build(self):
        setup = self.setup_step()
        build = next(
            step for step in self.steps if "run-bazel-ci.sh" in step.get("run", "")
        )
        self.assertLess(self.steps.index(setup), self.steps.index(build))
        self.assertEqual(setup["with"]["cache-scope"], "sdk")

    def test_restore_and_save_share_cache_path_and_exact_primary_key(self):
        for field, output in (
            ("path", "repository-cache-path"),
            ("key", "repository-cache-key"),
        ):
            self.assertEqual(
                self.resolve_output(self.save["with"][field]),
                self.restore["with"][field],
            )
            self.assertIn(output, self.save["with"][field])

    def test_hit_guard_reads_actual_restore_outcome(self):
        setup = self.setup_step()
        condition = self.save["if"]
        references = re.findall(r"steps\.([\w-]+)\.outputs\.([\w-]+)", condition)
        self.assertEqual(references, [(setup["id"], "repository-cache-hit")])
        self.assertEqual(
            self.prepare["outputs"]["repository-cache-hit"]["value"],
            "${{ steps." + self.restore["id"] + ".outputs.cache-hit }}",
        )
        # Exercise the actual conjuncts for the cache action's three output
        # states. Unknown operators require review; no eval of candidate code.
        terms = [term.strip() for term in condition.split("&&")]
        for hit, cancelled, expected in (
            ("true", False, False),
            ("false", False, True),
            ("", False, True),
            ("false", True, False),
        ):
            outcomes = []
            for term in terms:
                if re.fullmatch(r"always\(\s*\)", term):
                    outcomes.append(True)
                elif re.fullmatch(r"!\s*cancelled\(\s*\)", term):
                    outcomes.append(not cancelled)
                else:
                    match = re.fullmatch(
                        r"steps\.([\w-]+)\.outputs\.([\w-]+)\s*!=\s*'true'", term
                    )
                    self.assertIsNotNone(match, "unknown cache-save condition")
                    self.assertEqual((match[1], match[2]), references[0])
                    outcomes.append(hit != "true")
            self.assertEqual(all(outcomes), expected)

    def test_cache_failure_is_advisory_on_both_restore_and_save(self):
        self.assertEqual(self.restore["continue-on-error"], "true")
        self.assertEqual(self.save["continue-on-error"], "true")

    def test_real_key_script_namespaces_sdk_and_binds_target_and_content(self):
        setup = self.setup_step()
        key_step = next(
            step
            for step in self.prepare["runs"]["steps"]
            if step.get("id") == "cache_bazel_repository_key"
        )
        observed = []
        with tempfile.TemporaryDirectory() as directory:
            for scope, target, digest in (
                ("sdk", setup["with"]["target"], "a" * 64),
                ("test", setup["with"]["target"], "a" * 64),
                ("sdk", "other-target", "a" * 64),
                ("sdk", setup["with"]["target"], "b" * 64),
            ):
                output = Path(directory) / str(len(observed))
                environment = dict(
                    os.environ,
                    CACHE_SCOPE=scope,
                    TARGET=target,
                    CACHE_HASH=digest,
                    GITHUB_OUTPUT=str(output),
                )
                subprocess.run(
                    ["bash", "-euo", "pipefail", "-c", key_step["run"]],
                    env=environment,
                    check=True,
                    capture_output=True,
                )
                values = dict(
                    line.split("=", 1) for line in output.read_text().splitlines()
                )
                self.assertEqual(
                    values["repository-cache-key"],
                    f"bazel-cache-{scope}-{target}-{digest}",
                )
                self.assertEqual(
                    values["repository-cache-restore-key"],
                    f"bazel-cache-{scope}-{target}-",
                )
                observed.append(values["repository-cache-key"])
        self.assertEqual(len(set(observed)), 4)


if __name__ == "__main__":
    unittest.main()
