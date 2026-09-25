"""Real control-pipe subprocesses, external fixture signatures and owner restart."""

from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import selectors
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

from control_engineering_v2 import (
    CompletionReceipt, HmacTrustStore, IntegrationStageReceipt,
    IntegrationTerminalReceipt, WorkerHeartbeatReceipt, WorkerRegistrationReceipt,
    WorkerResultReceipt, WorkEnvelope,
)
from control_engineering_v2.control_plane import DENIED_AUTHORITIES

KEYS = {
    ("engineering_worker_identity", "identity-key"): b"identity-fixture",
    ("worker-a", "worker-key"): b"worker-fixture",
    ("ci_executor", "ci-key"): b"ci-fixture",
    ("engineering_evidence_binder", "candidate-key"): b"candidate-fixture",
    ("github_review_observer", "review-key"): b"review-fixture",
    ("integration_terminal_observer", "terminal-key"): b"terminal-fixture",
}


@unittest.skipUnless(os.name == "posix", "POSIX control pipe adapter")
class ProductServiceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="hepta-product-service-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        for args in (("init", "-q"), ("config", "user.name", "Product fixture"),
                     ("config", "user.email", "fixture@example.invalid"),
                     ("remote", "add", "origin", "https://github.com/TrillionniumFoundation/hepta-private-ci.git")):
            self.git(*args)
        (self.repo / "src").mkdir()
        (self.repo / "src/a").write_text("fixture\n")
        self.git("add", ".")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "fixture base")
        self.head, self.tree = self.git("rev-parse", "HEAD"), self.git("rev-parse", "HEAD^{tree}")
        self.database = self.root / "owner.sqlite3"
        self.trust = HmacTrustStore(KEYS)
        # Only the host verifier is configured here; all lifecycle transitions
        # below go through the installed CLI and the durable native owner.
        (self.root / "host_fixture.py").write_text(
            "from control_engineering_v2 import HmacTrustStore\n"
            "def create():\n    return HmacTrustStore(" + repr(KEYS) + ")\n"
        )
        self.processes = []
        self.addCleanup(self.close_all)
        self.sequence = 0

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.PIPE, text=True).strip()

    def close_all(self):
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()

    def start(self, factory="host_fixture:create"):
        process = subprocess.Popen(
            [sys.executable, "-B", "-m", "control_engineering_v2", "serve",
             "--database", str(self.database), "--repository", str(self.repo),
             "--repository-full-name", "TrillionniumFoundation/hepta-private-ci",
             "--verifier-factory", factory, "--scan-interval-seconds", "0.02"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                 "PYTHONPATH": os.pathsep.join((str(Path(__file__).resolve().parent), str(self.root)))},
            bufsize=0,
        )
        self.processes.append(process)
        return process

    def read(self, process):
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            self.assertTrue(selector.select(15), "product response deadline")
        line = process.stdout.readline()
        self.assertTrue(line, "product exited before response")
        return json.loads(line)

    def request(self, process, operation, **params):
        self.sequence += 1
        process.stdin.write(json.dumps({"id": f"request-{self.sequence}", "operation": operation, "params": params}).encode() + b"\n")
        return self.read(process)

    def result(self, process, operation, **params):
        response = self.request(process, operation, **params)
        self.assertNotIn("error", response, response)
        self.assertFalse(response["authorityGranted"])
        return response["result"]

    def signed(self, value):
        issuer = getattr(value, "issuer", getattr(value, "worker_id", None))
        identity = getattr(value, "signing_identity", getattr(value, "worker_signing_identity", None))
        return replace(value, signature=self.trust.sign(value, issuer, identity))

    def prepare_claim(self, process, ttl=10_000_000_000):
        now = time.time_ns()
        envelope = WorkEnvelope("env", self.head, self.tree, "c" * 64, "d" * 64,
                                "developer-productivity", ("src",), tuple(sorted(DENIED_AUTHORITIES)), 1, now + 600_000_000_000)
        self.result(process, "admit", envelope=asdict(envelope))
        registration = WorkerRegistrationReceipt("worker-a", "worker-key", ("engineering",), 1, ("src",),
                                                 "engineering_worker_identity", "identity-key", now, envelope.expires_unix_ns)
        self.result(process, "register", receipt=asdict(self.signed(registration)))
        plan = self.result(process, "plan", envelope=asdict(envelope),
                           packages=[{"priority": 0, "package_id": "package-a", "predecessors": [], "write_paths": ["src/a"], "required_skills": ["engineering"]}],
                           workers=[{"worker_id": "worker-a", "skills": ["engineering"], "capacity_units": 1, "allowed_paths": ["src"]}],
                           completion_receipts=[], capacity={"ci_units": 1, "review": []}, generation_id="generation-a")
        self.result(process, "lease", lease_id="lease-a", envelope_id="env", holder="worker-a", paths=["src/a"], authority_epoch=1, expires_unix_ns=envelope.expires_unix_ns)
        claim = self.result(process, "claim", generation_id="generation-a", package_id="package-a", worker_id="worker-a", lease_id="lease-a", heartbeat_ttl_ns=ttl)
        return plan, claim

    def test_real_process_ack_loss_reopen_completion_and_terminal_observation(self):
        process = self.start()
        self.assertTrue(self.read(process)["ready"])
        plan, claim = self.prepare_claim(process)
        now = time.time_ns()
        heartbeat = self.signed(WorkerHeartbeatReceipt("worker-a", "worker-key", claim["claim_id"], claim["claim_fence"], claim["revision"], now, now + 60_000_000_000))
        running = self.result(process, "heartbeat", receipt=asdict(heartbeat), heartbeat_ttl_ns=10_000_000_000)
        now = time.time_ns()
        result = self.signed(WorkerResultReceipt("worker-a", "worker-key", claim["claim_id"], claim["claim_fence"], running["revision"], "e" * 64, "success", now, now + 60_000_000_000))
        # Do not consume the result acknowledgement. Observe its durable commit
        # independently, then kill only this test-owned process.
        process.stdin.write(json.dumps({"id": "lost-ack", "operation": "result", "params": {"receipt": asdict(result)}}).encode() + b"\n")
        deadline = time.monotonic() + 15
        state = None
        while time.monotonic() < deadline:
            with sqlite3.connect(f"file:{self.database}?mode=ro", uri=True) as observer:
                state = observer.execute("SELECT state FROM worker_claims WHERE claim_id=?", (claim["claim_id"],)).fetchone()[0]
            if state == "result_submitted":
                break
            time.sleep(0.01)
        self.assertEqual(state, "result_submitted")
        process.kill(); process.wait(timeout=10)
        reopened = self.start()
        self.assertIn(claim["claim_id"], self.read(reopened)["recovery"]["awaiting_completion_claims"])
        self.assertEqual(self.result(reopened, "plan_state", generation_id="generation-a"), plan)
        self.result(reopened, "result", receipt=asdict(result))
        now = time.time_ns()
        completion = self.signed(CompletionReceipt("package-a", self.head, self.tree, "generation-a", plan["base_schedule_digest"], "e" * 64, "ci_executor", "ci-key", now, now + 60_000_000_000, True))
        completed = self.result(reopened, "completion", claim_id=claim["claim_id"], receipt=asdict(completion))
        self.assertEqual(completed["state"], "completed_observed")
        self.result(reopened, "publish", generation_id="generation-a", queue_generation_id="queue-a", base_commit=self.head, base_tree=self.tree)
        context = self.result(reopened, "context", queue_generation_id="queue-a", package_id="package-a")
        for index, (stage, issuer, identity) in enumerate((("candidate", "engineering_evidence_binder", "candidate-key"), ("review", "github_review_observer", "review-key"), ("ci", "ci_executor", "ci-key")), 1):
            now = time.time_ns()
            receipt = self.signed(IntegrationStageReceipt("queue-a", "package-a", stage, str(index) * 64, True, issuer, identity, now, now + 60_000_000_000, **context))
            item = self.result(reopened, "stage", queue_generation_id="queue-a", package_id="package-a", current_base_commit=self.head, current_base_tree=self.tree, receipt=asdict(receipt))
        self.assertEqual(item["state"], "ready_external_merge")
        now = time.time_ns()
        terminal = self.signed(IntegrationTerminalReceipt("queue-a", "package-a", item["candidate_digest"], item["review_digest"], item["ci_digest"], "merged_observed", "integration_terminal_observer", "terminal-key", now, now + 60_000_000_000, **context))
        params = dict(queue_generation_id="queue-a", package_id="package-a", current_base_commit=self.head, current_base_tree=self.tree, receipt=asdict(terminal))
        self.assertEqual(self.result(reopened, "terminal", **params)["state"], "terminal_merged")
        anchor = self.result(reopened, "audit")
        self.result(reopened, "terminal", **params)
        self.assertEqual(self.result(reopened, "audit"), anchor)
        reopened.stdin.close()
        self.assertEqual(reopened.wait(timeout=15), 0)
        final = self.start()
        self.assertTrue(self.read(final)["ready"])
        self.assertEqual(self.result(final, "terminal", **params)["state"], "terminal_merged")
        self.assertEqual(self.result(final, "audit"), anchor)

    def test_partial_input_does_not_stop_idle_expiration_and_capacity_recovery(self):
        process = self.start(); self.assertTrue(self.read(process)["ready"])
        _plan, claim = self.prepare_claim(process, ttl=100_000_000)
        process.stdin.write(b'{"id":')
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with sqlite3.connect(f"file:{self.database}?mode=ro", uri=True) as observer:
                state = observer.execute("SELECT state FROM worker_claims WHERE claim_id=?", (claim["claim_id"],)).fetchone()[0]
                active = observer.execute("SELECT COUNT(*) FROM worker_capacity_reservations WHERE state='active'").fetchone()[0]
            if state == "retryable" and active == 0:
                break
            time.sleep(0.02)
        self.assertEqual((state, active), ("retryable", 0))
        process.stdin.write(b'"inspect","operation":"claim_state","params":{"claim_id":"' + claim["claim_id"].encode() + b'"}}\n')
        self.assertEqual(self.read(process)["result"]["state"], "retryable")
        retried = self.result(process, "claim", generation_id="generation-a", package_id="package-a", worker_id="worker-a", lease_id="lease-a", heartbeat_ttl_ns=10_000_000_000)
        self.assertEqual((retried["attempt"], retried["state"]), (2, "claimed"))
        self.assertNotEqual(retried["claim_id"], claim["claim_id"])

    def test_missing_verifier_fails_closed_before_database_creation(self):
        process = self.start("host_fixture:missing")
        stdout, stderr = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(stdout, b"")
        self.assertIn(b"verifier_configuration_failed", stderr)
        self.assertFalse(self.database.exists())

    def test_unknown_fields_duplicate_json_and_unsigned_observations_reject(self):
        process = self.start(); self.assertTrue(self.read(process)["ready"])
        response = self.request(process, "recover", now_ns=0)
        self.assertEqual(response["error"], "invalid_product_parameters")
        process.stdin.write(b'{"id":"a","id":"b","operation":"recover","params":{}}\n')
        self.assertEqual(self.read(process)["error"], "duplicate_json_field")
        self.assertIn("error", self.request(process, "register", receipt={}))
        self.assertNotIn("error", self.request(process, "audit"))


if __name__ == "__main__":
    unittest.main()
