import argparse
import json
from pathlib import Path
import tempfile
import threading
import unittest

from locality_parallel_control import inputs, sha, trial


class ProbeConnection:
    """Concurrency assertion fixture, never used as performance evidence."""
    def __init__(self, identity, barrier):
        self.identity, self.barrier = identity, barrier
        self.sent = self.received = self.audits = 0

    def call(self, action, request_id):
        self.sent += len(json.dumps(action)); self.received += 1
        if action["kind"] == "stats":
            return {"ok":True, "audit_requests":self.audits, "failed_audit_requests":0}, 0
        if action["manifest_sha256"] != self.identity:
            raise AssertionError("incorrect shard assignment")
        # A serial implementation cannot pass this barrier; no artificial delay
        # or benchmark timing is used to manufacture a concurrency result.
        self.barrier.wait(timeout=2)
        self.audits += 1
        return {"ok":True, "summary":{"manifest_sha256":self.identity}, "compute_ns":0}, 0


class ParallelControlTests(unittest.TestCase):
    def test_both_arms_dispatch_two_independent_workers_concurrently(self):
        barrier = threading.Barrier(2)
        connections = [ProbeConnection("main", barrier), ProbeConnection("remote", barrier), ProbeConnection("remote", barrier)]
        local = trial(connections, ["main", "remote"], "parallel_local", 0)
        remote = trial(connections, ["main", "remote"], "distributed", 1)
        self.assertEqual([row["summary"] for row in local["reads"]], [row["summary"] for row in remote["reads"]])
        self.assertEqual(local["active_workers"], [0, 2]); self.assertEqual(remote["active_workers"], [0, 1])
        self.assertEqual([connection.audits for connection in connections], [2, 1, 1])

    def test_reuses_exact_prior_transfer_and_rejects_a_different_root_or_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); incoming = root / "incoming"; incoming.mkdir()
            (incoming / "source.rs").write_text("fn existing_source() {}\n")
            manifest = root / "manifest.json"; manifest.write_text('{"existing":"manifest"}')
            identity = sha(manifest)
            node = lambda name, port: {"name":name, "address":f"127.0.0.1:{port}", "instance":name,
                                      "generation":1, "artifact_sha256":"a" * 64, "runtime_job_id":"job-" + name}
            nodes = [node("main", 10001), {**node("remote", 10001), "ssh_target":"x230-ts"}]
            transfer = {"archive_sha256":"b" * 64, "archive_bytes":123, "transfer_and_extract_wall_seconds":1.2}
            deployment = {"nodes":nodes, "manifest_sha256":["c" * 64, identity],
                "central_transfer":{**transfer, "manifest":str(manifest), "local_root":str(incoming)}}
            write = lambda name, value:(root / name).write_text(json.dumps(value))
            write("deployment.json", deployment); write("transfer.json", transfer)
            result = {"schema":"hepta.source-shard-locality-result.v1", "protocol":{"deployment_sha256":sha(root / "deployment.json")},
                      "central_transfer":transfer, "verified_summaries":[{"manifest_sha256":"c" * 64}, {"manifest_sha256":identity}]}
            write("result.json", result)
            extra = {"node":node("main-second", 10002), "source_root":str(incoming), "manifest_sha256":identity,
                     "setup_receipts":[{"runtime_job_id":"job-main-second", "status":"fixture-only"}]}
            write("extra.json", extra)
            args = argparse.Namespace(prior_deployments=root / "deployment.json", prior_result=root / "result.json",
                                      prior_transfer=root / "transfer.json", additional_worker=root / "extra.json")
            before = {path:sha(path) for path in root.iterdir() if path.is_file()}
            self.assertEqual(len(inputs(args)[0]), 3)
            self.assertEqual(before, {path:sha(path) for path in before})
            extra["node"]["address"] = nodes[0]["address"]; write("extra.json", extra)
            with self.assertRaises(ValueError): inputs(args)
            extra["node"]["address"] = "127.0.0.1:10002"
            elsewhere = root / "elsewhere"; elsewhere.mkdir(); (elsewhere / "source.rs").write_text("other")
            extra["source_root"] = str(elsewhere); write("extra.json", extra)
            with self.assertRaises(ValueError): inputs(args)
            extra["source_root"] = str(incoming); write("extra.json", extra)
            write("transfer.json", {**transfer, "archive_bytes":124})
            with self.assertRaises(ValueError): inputs(args)


if __name__ == "__main__":
    unittest.main()
