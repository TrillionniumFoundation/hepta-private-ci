"""Execute the candidate permission step with fake transports, never real writes.

These tests cover shell exit propagation and the exact current observer. They
are not observations of live GitHub permissions or independent key custody.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
STEP = "      - name: Retain advisory candidate Git transport observation\n"


class CandidateTransportWorkflowTests(unittest.TestCase):
    def test_advisory_observation_follows_behavior_and_does_not_replace_required_native_result(
        self,
    ):
        workflow = (
            ROOT / ".github/workflows/hepta-architecture-convergence.yml"
        ).read_text()
        probe = workflow.index(STEP)
        for name in (
            "Inference owner regressions and streaming digest",
            "Module lifecycle generations and migration rollback",
            "Selected-artifact adoption and explicit rollback",
        ):
            self.assertLess(workflow.index("      - name: " + name), probe)
        block = workflow[probe:].split("      - name:", 2)[1]
        self.assertIn("!cancelled()", block)
        self.assertIn("steps.scope.outcome == 'success'", block)
        self.assertNotIn("continue-on-error", workflow)
        # Rustfmt is a separate fail-closed prerequisite, not a reason to
        # omit the original native qualification or its source/merge lanes.
        self.assertIn("    needs: p0_rustfmt", workflow)
        self.assertIn("    needs: [p0_rustfmt, qualification]", workflow)
        self.assertIn('test "$FORMAT_RESULT" = success', workflow)
        self.assertIn('test "$RESULT" = success', workflow)

    def test_prerequisites_and_lock_check_precede_native_builds(self):
        workflow = (
            ROOT / ".github/workflows/hepta-architecture-convergence.yml"
        ).read_text()
        first_native = workflow.index(
            "      - name: Inference owner regressions and streaming digest"
        )
        for name in (
            "Prepare native prerequisites",
            "Resolve verified V8 artifacts",
            "Verify Cargo lock resolution and print exact resolver drift",
        ):
            self.assertLess(workflow.index("      - name: " + name), first_native)

    def test_unavailable_prospective_merge_ref_retains_conflict_diagnostics(self):
        """A missing GitHub merge ref is a failed gate with retained evidence."""
        workflow = (
            ROOT / ".github/workflows/hepta-architecture-convergence.yml"
        ).read_text()
        section = workflow.split(
            "      - name: Verify GitHub prospective merge ref matches this exact candidate\n",
            1,
        )[1].split("      - name:", 1)[0]
        shell = textwrap.dedent(section.split("        run: |\n", 1)[1])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "bin"
            tools.mkdir()
            gh = tools / "gh"
            gh.write_text("#!/bin/sh\nexit 22\n")
            gh.chmod(0o700)
            git = tools / "git"
            git.write_text(
                "#!/bin/sh\necho 'CONFLICT (content): Merge conflict in codex-rs/hepta-neuron/src/runtime.rs'\nexit 1\n"
            )
            git.chmod(0o700)
            env = dict(
                os.environ,
                PR_NUMBER="1468",
                REPO="TrillionniumFoundation/hepta-private-ci",
                SOURCE_SHA="a" * 40,
                BASE_SHA="b" * 40,
                RUNNER_TEMP=directory,
                GH_TOKEN="fixture-secret-must-not-appear",
                PATH=str(tools) + os.pathsep + os.environ["PATH"],
            )
            result = subprocess.run(
                ["bash", "-c", shell],
                env=env,
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Prospective merge conflict", result.stdout)
            self.assertNotIn(env["GH_TOKEN"], result.stdout + result.stderr)
            records = root / "hepta-command-records"
            frozen = (records / "prospective-merge-candidate.txt").read_text()
            conflict = (records / "prospective-merge-tree.txt").read_text()
            self.assertIn("expected_base=" + "b" * 40, frozen)
            self.assertIn("expected_head=" + "a" * 40, frozen)
            self.assertIn("CONFLICT (content)", conflict)

    def run_step(self, status: int, body: str, *, timeout: bool = False):
        workflow = (
            ROOT / ".github/workflows/hepta-architecture-convergence.yml"
        ).read_text()
        block = workflow.split(STEP, 1)[1].split("      - name:", 1)[0]
        shell = textwrap.dedent(block.split("        run: |\n", 1)[1])
        self.assertNotIn(
            "PATCH",
            "\n".join(
                line for line in shell.splitlines() if not line.lstrip().startswith("#")
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "hepta-command-records").mkdir()
            # Load the repository observer itself, patch only its external I/O.
            # A sentinel gh fails any accidental CLI write or unpatched access.
            gh = root / "gh"
            gh.write_text("#!/bin/sh\necho unexpected-gh-call >&2\nexit 93\n")
            gh.chmod(0o700)
            (root / "fixture_transport.py").write_text(
                textwrap.dedent("""
                import json
                import os
                from pathlib import Path
                import hepta_repository_controls as c
                trace = Path(os.environ["TRACE"])
                def record(value):
                    with trace.open("a") as f:
                        f.write(json.dumps(value) + "\\n")
                def api(path):
                    record(["api", path])
                    assert path == "repos/TrillionniumFoundation/hepta-private-ci"
                    return {"full_name": "TrillionniumFoundation/hepta-private-ci", "id": 1}
                class Response:
                    status = int(os.environ["HTTP_STATUS"])
                    def read(self, limit):
                        record(["read", limit])
                        return os.environ["HTTP_BODY"].encode()
                class Connection:
                    def __init__(self, host, **kwargs):
                        assert host == "github.com"
                        assert kwargs["timeout"] > 0 and kwargs["context"] is not None
                    def request(self, method, path, **kwargs):
                        record(["request", method, path])
                        assert method == "GET" and kwargs.get("body") is None
                    def getresponse(self):
                        if os.environ["INJECT_TIMEOUT"] == "1":
                            raise TimeoutError("fixture timeout")
                        return Response()
                    def close(self):
                        record(["close"])
                c.api = api
                c.http.client.HTTPSConnection = Connection
            """)
            )
            python = root / "python3"
            python.write_text(
                f"#!{sys.executable}\nimport sys\nimport fixture_transport\n"
                "assert sys.argv[1:] == ['-']\n"
                "exec(compile(sys.stdin.read(), '<workflow-step>', 'exec'))\n"
            )
            python.chmod(0o700)
            env = dict(
                os.environ,
                REPO="TrillionniumFoundation/hepta-private-ci",
                GH_TOKEN="fixture-not-a-secret",
                RUNNER_TEMP=directory,
                HTTP_STATUS=str(status),
                HTTP_BODY=body,
                INJECT_TIMEOUT=str(int(timeout)),
                TRACE=str(root / "trace.jsonl"),
                PYTHONDONTWRITEBYTECODE="1",
                PYTHONPATH=os.pathsep.join([directory, str(ROOT / "scripts")]),
                PATH=directory + os.pathsep + os.environ["PATH"],
            )
            result = subprocess.run(
                ["bash", "-c", shell],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertTrue(
                (root / "trace.jsonl").exists(), result.stderr + result.stdout + shell
            )
            trace = [
                json.loads(line)
                for line in (root / "trace.jsonl").read_text().splitlines()
            ]
            retained = (
                root / "hepta-command-records/candidate-transport.json"
            ).read_text()
        self.assertNotIn(env["GH_TOKEN"], result.stdout + result.stderr + retained)
        self.assertEqual(
            trace[0], ["api", "repos/TrillionniumFoundation/hepta-private-ci"]
        )
        self.assertEqual(
            trace[1],
            [
                "request",
                "GET",
                "/TrillionniumFoundation/hepta-private-ci.git/info/refs?service=git-receive-pack",
            ],
        )
        self.assertEqual(trace[-1], ["close"])
        return result, retained

    def test_explicit_denial_is_retained_without_claiming_other_permissions(self):
        result, retained = self.run_step(
            403, "Write access to repository not granted.\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, retained)
        self.assertEqual(
            json.loads(retained),
            {
                "write_transport_denied": True,
                "observation_status": "denied",
                "advisory": True,
                "http_status": 403,
                "activation_authorized": False,
                "credential_separation_proven": False,
                "admin_denial_proven": False,
                "pull_request_write_denial_proven": False,
            },
        )

    def test_unknown_transport_is_retained_without_claiming_write_denial(self):
        for status, body in (
            (200, "Write access to repository not granted."),
            (401, "Bad credentials"),
            (403, "Rate limit exceeded"),
            (404, "Not found"),
            (302, "Redirect"),
            (500, "Server error"),
        ):
            with self.subTest(status=status, body=body):
                result, retained = self.run_step(status, body)
                self.assertEqual(result.returncode, 0, result.stderr)
                observation = json.loads(retained)
                self.assertEqual(observation["observation_status"], "unknown")
                self.assertIsNone(observation["write_transport_denied"])
                self.assertIs(observation["activation_authorized"], False)

    def test_timeout_is_unknown_not_a_permission_denial(self):
        result, retained = self.run_step(403, "", timeout=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        observation = json.loads(retained)
        self.assertEqual(observation["observation_status"], "unknown")
        self.assertIsNone(observation["write_transport_denied"])


if __name__ == "__main__":
    unittest.main()
