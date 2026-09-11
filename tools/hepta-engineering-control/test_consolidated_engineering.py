"""Behavioral regressions across the recovered Lane G branches."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

from control_engineering_v2 import (
    EngineeringError,
    EngineeringStore,
    WorkEnvelope,
    WorkPackage,
    bind_candidate_evidence,
    semantic_digest,
)
from control_engineering_v2.control_plane import DENIED_AUTHORITIES
import test_candidate_sandbox_hardening as sandbox_fixtures
import test_lane_g_seal as seal_fixtures


class OwnerTransactionTests(unittest.TestCase):
    def envelope(self):
        return WorkEnvelope(
            "work",
            "a" * 40,
            "b" * 40,
            "c" * 64,
            "d" * 64,
            "owner",
            ("src",),
            tuple(sorted(DENIED_AUTHORITIES)),
            4,
            time.time_ns() + 60_000_000_000,
        )

    def test_deep_dependency_graph_and_deep_cycle(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "owner.sqlite3") as store:
                store.issue_work_envelope(self.envelope())
                packages = [
                    WorkPackage(0, f"p{i}", (f"p{i - 1}",) if i else (), ("src/a",))
                    for i in range(1500)
                ]
                receipt = store.schedule_ready_packages(
                    "work", packages, (), generation_id="deep"
                )
                self.assertEqual(receipt.assigned, ("p0",))
                packages[0] = replace(packages[0], predecessors=("p1499",))
                with self.assertRaisesRegex(EngineeringError, "dependency_cycle"):
                    store.schedule_ready_packages(
                        "work", packages, (), generation_id="cycle"
                    )

    def test_active_lease_capacity_rejects_and_release_recovers(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "owner.sqlite3") as store:
                envelope = self.envelope()
                store.issue_work_envelope(envelope)
                with patch("control_engineering_v2.control_plane.MAX_ACTIVE_LEASES", 2):

                    def acquire(index):
                        return store.acquire_path_lease(
                            f"lease{index}",
                            "work",
                            "holder",
                            (f"src/{index}",),
                            authority_epoch=1,
                            expires_unix_ns=envelope.expires_unix_ns,
                        )

                    first = acquire(1)
                    acquire(2)
                    before = store.audit_projection()
                    with self.assertRaisesRegex(
                        EngineeringError, "active_lease_limit_exceeded"
                    ):
                        acquire(3)
                    self.assertEqual(store.audit_projection(), before)
                    store.transition_path_lease(
                        first.lease_id,
                        disposition="release",
                        expected_revision=first.revision,
                        authority_epoch=1,
                    )
                    self.assertEqual(acquire(3).state, "active")

    def test_future_schema_is_rejected_without_modifying_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "owner.sqlite3"
            with sqlite3.connect(path) as connection:
                connection.execute("PRAGMA user_version=99")
                connection.execute("CREATE TABLE future_data(value TEXT)")
                connection.execute("INSERT INTO future_data VALUES('keep')")
            before = path.read_bytes()
            with self.assertRaisesRegex(
                EngineeringError, "unsupported_future_store_schema"
            ):
                EngineeringStore(path)
            self.assertEqual(path.read_bytes(), before)

    def test_schema_v3_migrates_without_losing_owner_facts(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "owner.sqlite3"
            envelope = self.envelope()
            with EngineeringStore(path) as store:
                store.issue_work_envelope(envelope)
                before = store.audit_projection()
            with sqlite3.connect(path) as connection:
                connection.execute("DROP TABLE integration_decision_seals")
                connection.execute("DROP TABLE integration_decision_bindings")
                connection.execute("PRAGMA user_version=3")
                connection.execute(
                    "UPDATE engineering_schema_meta SET schema_version=3"
                )
            with EngineeringStore(path) as store:
                self.assertEqual(store.audit_projection(), before)
                self.assertEqual(
                    store.connection.execute("PRAGMA user_version").fetchone()[0], 5
                )
                self.assertEqual(
                    store.connection.execute(
                        "SELECT owner FROM work_envelopes"
                    ).fetchone()[0],
                    "owner",
                )

    def test_scheduler_failure_rolls_back_frontier_assignment_and_audit(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "owner.sqlite3") as store:
                store.issue_work_envelope(self.envelope())
                before = store.audit_projection()
                original = store._append_audit

                def fail(*args):
                    raise OSError("injected audit write failure")

                store._append_audit = fail
                with self.assertRaises(OSError):
                    store.schedule_ready_packages(
                        "work",
                        [WorkPackage(0, "p", (), ("src/a",))],
                        (),
                        generation_id="g",
                    )
                store._append_audit = original
                for table in (
                    "assignment_generation_frontiers",
                    "assignment_generations",
                ):
                    self.assertEqual(
                        store.connection.execute(
                            f"SELECT COUNT(*) FROM {table}"
                        ).fetchone()[0],
                        0,
                    )
                self.assertEqual(store.audit_projection(), before)

    def test_two_connections_cannot_acquire_overlapping_leases(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "owner.sqlite3"
            envelope = self.envelope()
            with EngineeringStore(path) as store:
                store.issue_work_envelope(envelope)

            def acquire(name):
                with EngineeringStore(path) as store:
                    try:
                        store.acquire_path_lease(
                            name,
                            "work",
                            name,
                            ("src/a",),
                            authority_epoch=1,
                            expires_unix_ns=envelope.expires_unix_ns,
                        )
                        return "acquired"
                    except EngineeringError as error:
                        return error.code

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(acquire, ("worker-a", "worker-b")))
            self.assertEqual(sorted(results), ["acquired", "active_path_conflict"])
            with EngineeringStore(path) as store:
                self.assertEqual(
                    store.connection.execute(
                        "SELECT COUNT(*) FROM path_leases WHERE state='active'"
                    ).fetchone()[0],
                    1,
                )
                store.verify_audit_chain()


class ConsolidatedEvidenceTests(unittest.TestCase):
    def test_signed_binding_cannot_upgrade_incomplete_sandbox(self):
        fixture = seal_fixtures.SealedEvidenceBoundaryTests()
        fixture.setUp()
        sandbox = replace(fixture.sandbox, filesystem_isolated=False)
        digest = semantic_digest(asdict(sandbox))
        candidate = replace(fixture.candidate, sandbox_receipt_digest=digest)
        binding = replace(fixture.binding, sandbox_receipt_digest=digest, signature="")
        binding = replace(
            binding,
            signature=fixture.trust.sign(
                binding, binding.issuer, binding.signing_identity
            ),
        )
        with self.assertRaisesRegex(
            EngineeringError, "sandbox_isolation_evidence_required"
        ):
            bind_candidate_evidence(
                candidate,
                sandbox,
                fixture.evidence,
                fixture.source,
                fixture.merge,
                binding,
                fixture.trust,
                seal_signing_identity="binder-key",
                now_ns=fixture.now,
            )

    def test_signed_binding_still_requires_successful_signed_execution(self):
        for invalid in ("failed", "unsigned"):
            with self.subTest(invalid=invalid):
                fixture = seal_fixtures.SealedEvidenceBoundaryTests()
                fixture.setUp()
                source = replace(
                    fixture.source, passed=invalid != "failed", signature=""
                )
                if invalid == "failed":
                    source = replace(
                        source,
                        signature=fixture.trust.sign(
                            source, source.issuer, source.signing_identity
                        ),
                    )
                binding = replace(
                    fixture.binding,
                    source_execution_digest=semantic_digest(asdict(source)),
                    signature="",
                )
                binding = replace(
                    binding,
                    signature=fixture.trust.sign(
                        binding, binding.issuer, binding.signing_identity
                    ),
                )
                with self.assertRaisesRegex(
                    EngineeringError, "execution_evidence_(invalid|signature)"
                ):
                    bind_candidate_evidence(
                        fixture.candidate,
                        fixture.sandbox,
                        fixture.evidence,
                        source,
                        fixture.merge,
                        binding,
                        fixture.trust,
                        seal_signing_identity="binder-key",
                        now_ns=fixture.now,
                    )

    def test_direct_facade_cannot_bypass_seal(self):
        from control_engineering_v2 import (
            facade,
            BoundEvidenceDecision,
            hardened_request_independent_review,
        )

        fixture = seal_fixtures.SealedEvidenceBoundaryTests()
        fixture.setUp()
        forged = BoundEvidenceDecision(
            True,
            (),
            "e" * 64,
            fixture.candidate.candidate_id,
            fixture.candidate.semantic_digest,
            fixture.sandbox_digest,
            "f" * 64,
        )
        for entrypoint in (
            facade.request_independent_review,
            hardened_request_independent_review,
        ):
            with self.subTest(entrypoint=entrypoint.__module__):
                with self.assertRaisesRegex(
                    EngineeringError, "sealed_evidence_required"
                ):
                    entrypoint(
                        fixture.candidate,
                        forged,
                        "independent_evaluator",
                        trust_store=fixture.trust,
                        now_ns=fixture.now,
                    )


class CandidateSequenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = sandbox_fixtures.CandidateSandboxFixture()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def test_check_mutation_cannot_be_hidden_by_later_check(self):
        from control_engineering_v2 import generate_candidates, sandbox_candidate

        envelope = self.fixture.envelope()
        candidate = generate_candidates(envelope, ())[0]
        relative = "tools/hepta-engineering-control/base file.txt"
        change = self.fixture.success_check(
            f"from pathlib import Path; Path({relative!r}).write_text('changed')"
        )
        restore = self.fixture.success_check(
            f"from pathlib import Path; Path({relative!r}).write_text('base\\n')"
        )
        with self.assertRaisesRegex(EngineeringError, "source_tree_mutated"):
            sandbox_candidate(self.fixture.root, envelope, candidate, (change, restore))

    def test_source_ref_mutation_is_detected_even_when_head_is_unchanged(self):
        from control_engineering_v2 import generate_candidates, sandbox_candidate

        envelope = self.fixture.envelope()
        candidate = generate_candidates(envelope, ())[0]
        command = self.fixture.success_check(
            "import subprocess; subprocess.run("
            + repr(
                [
                    "git",
                    "-C",
                    str(self.fixture.root),
                    "update-ref",
                    "refs/heads/unexpected",
                    "HEAD",
                ]
            )
            + ", check=True)"
        )
        with self.assertRaisesRegex(EngineeringError, "source_tree_mutated"):
            sandbox_candidate(self.fixture.root, envelope, candidate, (command,))


class EngineeringCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.tool_root = Path(__file__).resolve().parent

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value))
        return str(path)

    def command(self, *arguments):
        return subprocess.run(
            [sys.executable, "-m", "control_engineering_v2", *arguments],
            cwd=self.tool_root,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_schedule_persists_and_replays_an_identical_generation(self):
        value = OwnerTransactionTests().envelope()
        envelope = self.write("envelope.json", asdict(value))
        packages = self.write(
            "packages.json",
            [
                asdict(WorkPackage(0, "a", (), ("src/a",))),
                asdict(WorkPackage(1, "b", ("a",), ("src/b",))),
            ],
        )
        args = (
            "schedule",
            "--database",
            str(self.root / "store.sqlite3"),
            "--envelope",
            envelope,
            "--packages",
            packages,
            "--generation-id",
            "first",
        )
        first, second = self.command(*args), self.command(*args)
        self.assertEqual(
            (first.returncode, second.returncode), (0, 0), first.stderr + second.stderr
        )
        self.assertEqual(json.loads(first.stdout), json.loads(second.stdout))
        result = json.loads(first.stdout)["assignment"]
        self.assertEqual(result["assigned"], ["a"])
        self.assertEqual(result["blocked"], [["b", "missing_predecessor:a"]])

    def test_duplicate_json_fields_are_rejected(self):
        path = self.root / "duplicate.json"
        path.write_text('{"envelope_id":"first","envelope_id":"second"}')
        result = self.command(
            "candidates",
            "--envelope",
            str(path),
            "--mutations",
            self.write("mutations.json", []),
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stderr)["error"], "duplicate_json_field")

    def test_candidate_cli_roundtrip_preserves_fixture_maturity(self):
        fixture = sandbox_fixtures.CandidateSandboxFixture()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        envelope = self.write("candidate-envelope.json", asdict(fixture.envelope()))
        mutations = self.write("mutations.json", [])
        proposed = self.command(
            "candidates", "--envelope", envelope, "--mutations", mutations
        )
        self.assertEqual(proposed.returncode, 0, proposed.stderr)
        candidate = json.loads(proposed.stdout)["candidates"][0]
        checks = self.write(
            "checks.json", [[sys.executable, "-I", "-c", "print('verified')"]]
        )
        result = self.command(
            "sandbox",
            "--repository",
            str(fixture.root),
            "--envelope",
            envelope,
            "--mutations",
            mutations,
            "--candidate-id",
            candidate["candidate_id"],
            "--checks",
            checks,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["candidate"]["state"], "fixture_tested")
        self.assertFalse(receipt["receipt"]["filesystem_isolated"])
        self.assertTrue(receipt["receipt"]["passed"])
