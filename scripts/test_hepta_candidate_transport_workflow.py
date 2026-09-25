"""Exercise the read-only repository-permission observation in architecture CI.

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
STEP = "      - name: Observe candidate repository push denial without mutating repository state\n"


class CandidateTransportWorkflowTests(unittest.TestCase):
    @staticmethod
    def denied_payload():
        return {
            "full_name": "TrillionniumFoundation/hepta-private-ci",
            "id": 1,
            "permissions": {
                "admin": False,
                "maintain": False,
                "push": False,
                "triage": False,
                "pull": True,
            },
        }

    def test_permission_failure_does_not_prevent_behavior_execution_or_turn_green(self):
        workflow = (ROOT / ".github/workflows/hepta-architecture-convergence.yml").read_text()
        probe = workflow.index(STEP)
        for name in (
            "Inference owner recovery, writer exclusion and journal bounds",
            "Module lifecycle generations and migration rollback",
            "Selected-artifact adoption and explicit rollback",
        ):
            self.assertLess(workflow.index("      - name: " + name), probe)
        block = workflow[probe:].split("      - name:", 2)[1]
        self.assertIn("!cancelled()", block)
        self.assertIn("steps.scope.outcome == 'success'", block)
        self.assertNotIn("continue-on-error", workflow)
        self.assertIn("needs: qualification", workflow)
        self.assertIn('test "$RESULT" = success', workflow)

    def test_inference_commands_name_current_source_tests_not_speculative_scale(self):
        workflow = (ROOT / ".github/workflows/hepta-architecture-convergence.yml").read_text()
        maintenance = (ROOT / ".github/workflows/hepta-inference-maintenance.yml").read_text()
        source = "\n".join(
            path.read_text()
            for path in (ROOT / "codex-rs/hepta-infer-core/src").glob("*.rs")
        )
        for name in (
            "reopens_exact_committed_state",
            "one_writer_is_held_until_owner_drop",
            "journal_byte_budget_rejects_before_append_and_replay_checks_actual_bytes",
        ):
            self.assertIn(f"fn {name}(", source)
            self.assertIn(name, workflow)
        self.assertIn(
            "journal_byte_budget_rejects_before_append_and_replay_checks_actual_bytes",
            maintenance,
        )
        for stale in (
            "history_growth_emits_update_recovery_memory_and_disk_curve",
            "alternating_writers_replay_only_peer_deltas",
            "post_compaction_multi_generation_curve",
        ):
            self.assertNotIn(stale, workflow)
            self.assertNotIn(stale, maintenance)

    def test_prerequisites_and_lock_check_precede_native_builds(self):
        workflow = (ROOT / ".github/workflows/hepta-architecture-convergence.yml").read_text()
        first_native = workflow.index(
            "      - name: Inference owner recovery, writer exclusion and journal bounds"
        )
        for name in (
            "Prepare native prerequisites",
            "Resolve verified V8 artifacts",
            "Verify Cargo lock resolution and print exact resolver drift",
        ):
            self.assertLess(workflow.index("      - name: " + name), first_native)

    def run_step(self, status: int = 200, payload=None, *, timeout: bool = False):
        workflow = (ROOT / ".github/workflows/hepta-architecture-convergence.yml").read_text()
        block = workflow.split(STEP, 1)[1].split("      - name:", 1)[0]
        shell = textwrap.dedent(block.split("        run: |\n", 1)[1])
        self.assertNotIn(
            "PATCH",
            "\n".join(line for line in shell.splitlines() if not line.lstrip().startswith("#")),
        )
        if payload is None:
            payload = self.denied_payload()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "hepta-command-records").mkdir()
            gh = root / "gh"
            gh.write_text("#!/bin/sh\necho unexpected-gh-call >&2\nexit 93\n")
            gh.chmod(0o700)
            (root / "fixture_permission.py").write_text(
                textwrap.dedent(
                    '''
                    import json
                    import os
                    from pathlib import Path
                    import hepta_repository_controls as c
                    trace = Path(os.environ["TRACE"])
                    def record(value):
                        with trace.open("a") as f:
                            f.write(json.dumps(value) + "\\n")
                    class Response:
                        status = int(os.environ["HTTP_STATUS"])
                        def read(self, limit):
                            record(["read", limit])
                            return os.environ["HTTP_BODY"].encode()
                    class Connection:
                        def __init__(self, host, **kwargs):
                            assert host == "api.github.com"
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
                    c.http.client.HTTPSConnection = Connection
                    '''
                )
            )
            python = root / "python3"
            python.write_text(
                f"#!{sys.executable}\nimport sys\nimport fixture_permission\n"
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
                HTTP_BODY=json.dumps(payload),
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
                json.loads(line) for line in (root / "trace.jsonl").read_text().splitlines()
            ]
            retained = (
                root / "hepta-command-records/candidate-permission.json"
            ).read_text()
        self.assertNotIn(env["GH_TOKEN"], result.stdout + result.stderr + retained)
        self.assertEqual(
            trace[0],
            ["request", "GET", "/repos/TrillionniumFoundation/hepta-private-ci"],
        )
        self.assertEqual(trace[-1], ["close"])
        return result, retained

    def test_exact_role_denial_is_retained_without_claiming_other_permissions(self):
        result, retained = self.run_step()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, retained)
        self.assertEqual(
            json.loads(retained),
            {
                "repository_push_permission_denied": True,
                "activation_authorized": False,
                "credential_separation_proven": False,
                "admin_denial_proven": False,
                "pull_request_write_denial_proven": False,
            },
        )

    def test_unknown_or_allowed_permission_cannot_pass_through_tee(self):
        cases = [
            (401, self.denied_payload()),
            (403, self.denied_payload()),
            (404, self.denied_payload()),
            (500, self.denied_payload()),
            (200, {**self.denied_payload(), "permissions": {"push": True}}),
            (200, {"full_name": "TrillionniumFoundation/hepta-private-ci", "id": 1}),
        ]
        for status, payload in cases:
            with self.subTest(status=status, payload=payload):
                result, retained = self.run_step(status, payload)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(retained, "")

    def test_timeout_is_unknown_not_a_permission_denial(self):
        result, retained = self.run_step(timeout=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(retained, "")


if __name__ == "__main__":
    unittest.main()
