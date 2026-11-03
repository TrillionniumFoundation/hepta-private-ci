"""Identity/resource-proof regressions; fixtures are not timing evidence."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import locality_parallel_rebind_control as control


class RebindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary, self.model = "b" * 64, "a" * 64
        self.central = self.root / "existing-central"
        self.central.mkdir()
        (self.central / "source.rs").write_text("fn source() {}\n")
        self.manifest = self.root / "remote-manifest.json"
        self.manifest.write_text('{"source_tree_sha256":"frozen-tree"}\n')
        self.ids = ["c" * 64, control.sha(self.manifest)]
        self.transfer = {"archive_sha256":"d" * 64, "archive_bytes":100}
        self.old = [self.node("main", "old-main", 1), self.node("x230", "old-x230", 1, remote=True)]
        self.fresh = [self.node("main", "fresh-main", 2), self.node("x230", "fresh-x230", 2, remote=True),
                      self.node("main-second", "fresh-main-second", 1, port=9021)]
        self.deployment = {"nodes":self.old, "manifest_sha256":self.ids,
            "central_transfer":{**self.transfer, "local_root":str(self.central), "manifest":str(self.manifest)}}
        self.args = SimpleNamespace(prior_deployments=self.root / "DEPLOYMENTS.json",
            prior_result=self.root / "RESULT.json", prior_transfer=self.root / "CENTRAL_TRANSFER.json",
            rebindings=self.root / "REBINDINGS.json")
        self.write(self.args.prior_deployments, self.deployment)
        self.write(self.args.prior_transfer, self.transfer)
        self.write(self.args.prior_result, {"schema":"hepta.source-shard-locality-result.v1",
            "protocol":{"deployment_sha256":control.sha(self.args.prior_deployments)},
            "central_transfer":self.transfer, "verified_summaries":[{"manifest_sha256":value} for value in self.ids]})
        self.bindings = {"schema":"hepta.source-shard-worker-rebindings.v1", "worker_sha256":self.binary,
            "central_root":str(self.central), "old_workers":[], "fresh_workers":[]}
        for index, node in enumerate(self.old):
            terminal = self.proof(f"old-{index}-terminal", {"job_id":node["runtime_job_id"], "state":"timed_out",
                "exit_code":124, "output_complete":True})
            terminal.update(job_pointer="/job_id", state_pointer="/state", terminal_state="timed_out")
            self.bindings["old_workers"].append({"runtime_terminal":terminal,
                "lifecycle_snapshot":self.proof(f"old-{index}-life", self.lifecycle(node, fresh=False))})
        for index, node in enumerate(self.fresh):
            started = self.proof(f"new-{index}-start", {"job_id":node["runtime_job_id"], "state":"running"})
            started["job_pointer"] = "/job_id"
            life = self.proof(f"new-{index}-ready", self.lifecycle(node, fresh=True))
            self.bindings["fresh_workers"].append({"node":node, "runtime_start":started,
                "lifecycle_ready_snapshot":life, "setup_receipts":[{"stage":"worker-ready", "evidence":copy.deepcopy(life)}]})
        self.commit()

    def node(self, name, job, generation, remote=False, port=9020):
        value = {"name":name, "runtime_job_id":job, "instance":"instance-" + name, "generation":generation,
                 "address":f"127.0.0.1:{port}", "artifact_sha256":self.model}
        if remote:
            value["ssh_target"] = "x230-ts"
        return value

    def lifecycle(self, node, fresh):
        ready = {key:node[key] for key in ("address", "instance", "generation", "artifact_sha256")}
        ready.update(ready=True, registered_shards=self.ids)
        raw = json.dumps(ready).encode() + b"\n"
        return {"schema":"hepta.cell-worker-lifecycle.v1", "worker_sha256":self.binary, "launch_attempts":1,
            "state":"ready" if fresh else "terminal", "complete":not fresh, "child_reaped":not fresh,
            "runtime_job_id_environment_observation":node["runtime_job_id"], "clock_ticks_per_second":100,
            "wait4_usage":None if fresh else {"user_cpu_seconds":0.1, "system_cpu_seconds":0.02, "peak_rss_kib":3000},
            "ready":{"json":ready, "raw_base64":base64.b64encode(raw).decode(),
                     "bytes":len(raw), "sha256":hashlib.sha256(raw).hexdigest(), "wrapper_start_to_ready_seconds":0.01}}

    def write(self, path, value):
        path.write_text(json.dumps(value, sort_keys=True) + "\n")

    def proof(self, name, value):
        path = self.root / (name + ".json")
        self.write(path, value)
        return {"path":str(path), "sha256":control.sha(path)}

    def commit(self):
        self.write(self.args.rebindings, self.bindings)

    def change_proof(self, spec, key, value):
        path = Path(spec["path"])
        contents = control.read(path)
        contents[key] = value
        self.write(path, contents)
        spec["sha256"] = control.sha(path)

    def test_explicit_terminal_to_fresh_binding_preserves_resource_proofs(self):
        nodes, identities, expected, transfer, observations, pins = control.inputs(self.args)
        self.assertEqual(nodes, self.fresh)
        self.assertEqual(identities, self.ids)
        self.assertEqual(transfer, self.transfer)
        self.assertEqual(observations["old"][0]["terminal"]["exit_code"], 124)
        self.assertEqual(observations["old"][0]["lifecycle"]["wait4_usage"]["peak_rss_kib"], 3000)
        self.assertEqual(len(observations["fresh"]), 3)
        self.assertIn(str(self.args.prior_result.resolve()), pins)
        self.assertEqual(expected[1]["manifest_sha256"], self.ids[1])

    def test_old_runtime_terminal_does_not_substitute_for_child_reap(self):
        spec = self.bindings["old_workers"][0]["lifecycle_snapshot"]
        self.change_proof(spec, "child_reaped", False)
        self.commit()
        with self.assertRaisesRegex(ValueError, "completed direct-child"):
            control.inputs(self.args)

    def test_wrong_runtime_job_and_nonterminal_state_are_rejected(self):
        original = copy.deepcopy(self.bindings["old_workers"][0]["runtime_terminal"])
        for key, value, message in (("job_id", "unrelated-job", "different job"), ("state", "running", "terminal observation")):
            with self.subTest(key=key):
                spec = self.bindings["old_workers"][0]["runtime_terminal"]
                self.change_proof(spec, key, value)
                self.commit()
                with self.assertRaisesRegex(ValueError, message):
                    control.inputs(self.args)
                self.write(Path(original["path"]), {"job_id":self.old[0]["runtime_job_id"], "state":"timed_out",
                    "exit_code":124, "output_complete":True})
                self.bindings["old_workers"][0]["runtime_terminal"] = copy.deepcopy(original)

    def test_reused_job_generation_model_and_empty_central_root_are_rejected(self):
        before = copy.deepcopy(self.bindings)
        for key, value in (("runtime_job_id", self.old[0]["runtime_job_id"]), ("generation", 1), ("artifact_sha256", "e" * 64)):
            with self.subTest(key=key):
                self.bindings["fresh_workers"][0]["node"][key] = value
                self.commit()
                with self.assertRaisesRegex(ValueError, "generation/job"):
                    control.inputs(self.args)
                self.bindings = copy.deepcopy(before)
        self.commit()
        (self.central / "source.rs").unlink()
        with self.assertRaisesRegex(ValueError, "populated central"):
            control.inputs(self.args)

    def test_ready_bytes_and_binary_are_bound_independently_of_claimed_node(self):
        spec = self.bindings["fresh_workers"][0]["lifecycle_ready_snapshot"]
        for key, value, message in (("worker_sha256", "e" * 64, "binary"), ("state", "terminal", "ready lifecycle")):
            with self.subTest(key=key):
                self.change_proof(spec, key, value)
                self.commit()
                with self.assertRaisesRegex(ValueError, message):
                    control.inputs(self.args)
                self.write(Path(spec["path"]), self.lifecycle(self.fresh[0], fresh=True))
                spec["sha256"] = control.sha(Path(spec["path"]))
        life = self.lifecycle(self.fresh[0], fresh=True)
        life["ready"]["json"]["generation"] = 900
        self.write(Path(spec["path"]), life)
        spec["sha256"] = control.sha(Path(spec["path"]))
        self.commit()
        with self.assertRaisesRegex(ValueError, "captured ready bytes"):
            control.inputs(self.args)

    def test_provider_envelope_uses_explicit_pointer_without_rewriting_original(self):
        raw = {"content":[{"text":json.dumps({"job_id":"actual-job", "state":"timed_out"})}]}
        spec = self.proof("envelope", raw)
        spec.update(document_pointer="/content/0/text", decode_json_string=True,
                    job_pointer="/job_id", state_pointer="/state", terminal_state="timed_out")
        pins = {}
        result = control.runtime_receipt(spec, {"runtime_job_id":"actual-job"}, pins, terminal=True)
        self.assertEqual(result["terminal_state"], "timed_out")
        self.assertEqual(control.read(Path(spec["path"])), raw)


if __name__ == "__main__":
    unittest.main()
