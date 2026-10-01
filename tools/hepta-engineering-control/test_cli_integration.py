from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, replace
import io
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from control_engineering_v2 import CandidateEnvelope, EngineeringStore, WorkEnvelope
from control_engineering_v2 import cli
from control_engineering_v2.control_plane import DENIED_AUTHORITIES
import test_production_readiness as readiness_test_fixtures


class CliIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database = self.root / "engineering.sqlite3"
        self.envelope = WorkEnvelope(
            "env", "a" * 40, "b" * 40, "c" * 64, "d" * 64,
            "developer-productivity", ("src",), tuple(sorted(DENIED_AUTHORITIES)),
            8, time.time_ns() + 60_000_000_000,
        )

    def write_json(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return str(path)

    def invoke(self, arguments):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = cli.main(arguments)
        result = output.getvalue() if code == 0 or output.getvalue() else errors.getvalue()
        return code, json.loads(result)

    def schedule_arguments(self, packages, generation, completed=None, envelope=None):
        arguments = [
            "schedule", "--database", str(self.database),
            "--envelope", self.write_json("envelope.json", asdict(envelope or self.envelope)),
            "--packages", self.write_json("packages.json", packages),
            "--generation-id", generation,
        ]
        if completed is not None:
            arguments.extend(("--completed", self.write_json("completed.json", completed)))
        return arguments

    def repository(self):
        repository = self.root / "repository"
        repository.mkdir()
        for arguments in (
            ("init",), ("config", "user.email", "test@example.invalid"),
            ("config", "user.name", "Test"),
        ):
            self.git(repository, *arguments)
        (repository / "src").mkdir()
        (repository / "src/base.txt").write_text("base\n", encoding="utf-8")
        self.git(repository, "add", ".")
        self.git(repository, "commit", "-m", "base")
        return repository, self.git(repository, "rev-parse", "HEAD")

    @staticmethod
    def git(repository, *arguments):
        return subprocess.run(
            ["git", "-C", str(repository), *arguments], check=True,
            capture_output=True, text=True,
        ).stdout.strip()

    def candidate_arguments(self, command, envelope, mutations):
        return [
            command, "--envelope", self.write_json("candidate-envelope.json", asdict(envelope)),
            "--mutations", self.write_json("mutations.json", mutations),
        ]

    def test_schedule_persists_actual_lease_conflict_dependency_and_replay(self):
        initial = [{"priority": 0, "package_id": "initial", "predecessors": [], "write_paths": ["src/initial"]}]
        self.assertEqual(self.invoke(self.schedule_arguments(initial, "initial"))[0], 0)
        with EngineeringStore(self.database) as store:
            store.acquire_path_lease(
                "lease", "env", "worker", ("src/occupied",), authority_epoch=1,
                expires_unix_ns=self.envelope.expires_unix_ns,
            )
        packages = [
            {"priority": 0, "package_id": "occupied", "predecessors": [], "write_paths": ["src/occupied"]},
            {"priority": 1, "package_id": "dependent", "predecessors": ["finished"], "write_paths": ["src/dependent"]},
        ]
        arguments = self.schedule_arguments(packages, "generation", ["finished"])
        code, result = self.invoke(arguments)
        self.assertEqual(code, 0)
        self.assertEqual(result["assignment"]["assigned"], ["dependent"])
        self.assertEqual(result["assignment"]["blocked"], [["occupied", "active_path_lease"]])
        self.assertEqual(result["frontier"]["sourceCommit"], self.envelope.source_commit)
        self.assertFalse(result["productOrchestrationEvidence"])
        with EngineeringStore(self.database) as store:
            anchor = store.audit_anchor()
        self.assertEqual(self.invoke(arguments), (code, result))
        with EngineeringStore(self.database) as store:
            self.assertEqual(store.audit_anchor(), anchor)

    def test_cli_rejects_malformed_bounded_input_and_preserves_business_state(self):
        cases = (
            ("duplicate", '{"envelope_id":"env","envelope_id":"other"}', "duplicate_json_field"),
            ("unknown", json.dumps({**asdict(self.envelope), "authority": True}), "invalid_input_fields"),
            ("deep", "[" * 2000 + "0" + "]" * 2000, "input_depth_limit_exceeded"),
            ("oversized", " " * (cli.MAX_INPUT_BYTES + 1), "input_byte_limit_exceeded"),
            ("overflow", json.dumps(asdict(replace(self.envelope, expires_unix_ns=2**100))), "invalid_envelope_expiry"),
        )
        for name, content, expected in cases:
            with self.subTest(name=name):
                path = self.root / f"{name}.json"
                path.write_text(content, encoding="utf-8")
                arguments = self.schedule_arguments([], name)
                arguments[arguments.index("--envelope") + 1] = str(path)
                code, result = self.invoke(arguments)
                self.assertEqual(code, 1)
                self.assertFalse(result["authorityGranted"])
                self.assertEqual(result["error"], expected)
        with EngineeringStore(self.database) as store:
            self.assertEqual(store.connection.execute("SELECT count(*) FROM work_envelopes").fetchone()[0], 0)

    def test_cli_rejects_invalid_completion_set_and_package_count(self):
        for packages, completed, expected in (
            ([], {}, "invalid_completed_set"),
            ([{}] * 4097, [], "input_record_limit_exceeded"),
        ):
            with self.subTest(expected=expected):
                self.assertEqual(
                    self.invoke(self.schedule_arguments(packages, expected, completed)),
                    (1, {"error": expected, "authorityGranted": False}),
                )
        self.assertFalse(self.database.exists())

    def test_missing_parent_and_non_sqlite_database_fail_as_json(self):
        non_sqlite = self.root / "not-sqlite.sqlite3"
        non_sqlite.write_text("invalid database", encoding="utf-8")
        for database in (self.root / "missing/engineering.sqlite3", non_sqlite):
            with self.subTest(database=database):
                arguments = self.schedule_arguments([], "database-error")
                arguments[arguments.index("--database") + 1] = str(database)
                self.assertEqual(self.invoke(arguments), (1, {"error": "invalid_input", "authorityGranted": False}))
        self.assertEqual(non_sqlite.read_text(encoding="utf-8"), "invalid database")

    def test_json_brackets_and_escaped_quotes_inside_text_do_not_consume_depth(self):
        envelope = CandidateEnvelope("candidate", "a" * 40, ("src",))
        text = "[{" * (cli.MAX_INPUT_DEPTH * 2) + r'\\" escaped quote \\ [ ] { }'
        mutations = [{"operation": "add_file", "path": "src/text.txt", "replacement_text": text}]
        code, result = self.invoke(self.candidate_arguments("candidates", envelope, mutations))
        self.assertEqual(code, 0)
        self.assertEqual(result["candidates"][1]["mutation"]["replacement_text"], text)

    def test_multibyte_json_cannot_bypass_depth_preflight(self):
        payload = '["\\\\\\\"",' + '[' * 100 + '0' + ']' * 100 + ']'
        json.loads(payload)
        for encoding in ("utf-16", "utf-16-le", "utf-32"):
            with self.subTest(encoding=encoding):
                path = self.root / f"deep-{encoding}.json"
                path.write_bytes(payload.encode(encoding))
                arguments = self.schedule_arguments([], encoding)
                arguments[arguments.index("--envelope") + 1] = str(path)
                code, result = self.invoke(arguments)
                self.assertEqual(code, 1)
                self.assertFalse(result["authorityGranted"])
                self.assertEqual(result["error"], "input_depth_limit_exceeded")
                shallow = json.dumps(asdict(replace(self.envelope, owner=r'quoted \\" [] {}')))
                path.write_bytes(shallow.encode(encoding))
                code, result = self.invoke(arguments)
                self.assertEqual(code, 0)
                self.assertEqual(result["assignment"]["assigned"], [])

    def test_candidate_group_and_portable_sandbox_check_exit_status(self):
        repository, base = self.repository()
        envelope = CandidateEnvelope("candidate", base, ("src",), require_network_isolation=False)
        mutations = [{"mutations": [
            {"operation": "add_file", "path": "src/first.txt", "replacement_text": "first\n"},
            {"operation": "add_file", "path": "src/second.txt", "replacement_text": "second\n"},
        ]}]
        code, proposals = self.invoke(self.candidate_arguments("candidates", envelope, mutations))
        self.assertEqual(code, 0)
        self.assertEqual(len(proposals["candidates"]), 2)
        candidate = proposals["candidates"][1]
        arguments = self.candidate_arguments("sandbox", envelope, mutations) + [
            "--repository", str(repository), "--candidate-id", candidate["candidate_id"],
            "--checks", self.write_json("checks.json", [["/usr/bin/python3", "-c", "from pathlib import Path; assert Path('src/first.txt').read_text() == 'first\\n'"]]),
        ]
        code, result = self.invoke(arguments)
        self.assertEqual(code, 0)
        self.assertTrue(result["receipt"]["passed"])
        self.assertFalse(result["receipt"]["filesystem_isolated"])
        self.assertTrue(result["admissionControlled"])
        self.assertFalse((repository / "src/first.txt").exists())
        self.assertEqual(self.git(repository, "status", "--porcelain"), "")
        arguments[-1] = self.write_json("checks.json", [["/usr/bin/python3", "-c", "raise SystemExit(3)"]])
        code, result = self.invoke(arguments)
        self.assertEqual(code, 1)
        self.assertFalse(result["receipt"]["passed"])

    def test_candidate_and_sandbox_reject_bad_selection_and_unavailable_strong_isolation(self):
        repository, base = self.repository()
        envelope = CandidateEnvelope("candidate", base, ("src",))
        mutation = {"operation": "add_file", "path": "src/new.txt", "replacement_text": "new"}
        proposals = self.invoke(self.candidate_arguments("candidates", envelope, [mutation]))[1]
        arguments = self.candidate_arguments("sandbox", envelope, [mutation]) + [
            "--repository", str(repository), "--candidate-id", "missing",
            "--checks", self.write_json("checks.json", [["/usr/bin/true"]]),
        ]
        self.assertEqual(self.invoke(arguments), (1, {"error": "unknown_candidate", "authorityGranted": False}))
        arguments[arguments.index("--candidate-id") + 1] = proposals["candidates"][1]["candidate_id"]
        arguments[-1] = self.write_json("checks.json", {})
        self.assertEqual(self.invoke(arguments), (1, {"error": "invalid_check", "authorityGranted": False}))
        arguments[-1] = self.write_json("checks.json", [["/usr/bin/true"]])
        with mock.patch("control_engineering_v2.candidate.shutil.which", return_value=None):
            self.assertEqual(self.invoke(arguments), (1, {"error": "network_isolation_unavailable", "authorityGranted": False}))
        self.assertFalse((repository / "src/new.txt").exists())
        for malformed in ([mutation] * 33, [{"mutations": [mutation] * 101}], [dict(mutation, merge_authority=True)]):
            code, result = self.invoke(self.candidate_arguments("candidates", envelope, malformed))
            self.assertEqual(code, 1)
            self.assertFalse(result["authorityGranted"])

    def test_readiness_json_can_only_project_and_deprecated_certification_fails_closed(self):
        facts = self.write_json("facts.json", asdict(readiness_test_fixtures.ProductionReadinessTests().facts()))
        code, result = self.invoke(["readiness-projection", "--facts", facts])
        self.assertEqual(code, 0)
        self.assertEqual(result["qualificationClass"], "projection_only")
        self.assertFalse(result["authenticated"])
        self.assertFalse(result["authorityGranted"])
        self.assertEqual(
            self.invoke(["production-readiness", "--facts", facts, "--require", "implementation"]),
            (1, {"error": "authenticated_readiness_composition_required", "authorityGranted": False}),
        )


if __name__ == "__main__":
    unittest.main()
