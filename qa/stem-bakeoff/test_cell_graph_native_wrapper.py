"""Local fixture tests. Constants are patched to temporary roots; no host calls."""

import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import cell_graph_native_wrapper as wrapper


def encoded(data):
    return {"base64": base64.b64encode(data).decode(), "sha256": hashlib.sha256(data).hexdigest()}


class WrapperTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()
        self.dispatch = self.evidence / "requests-v1" / "dispatch.json"
        self.dispatch.parent.mkdir()
        plan = {"schema": "hepta.fixed-cell-graph.dispatch.v1", "protocol_sha256": wrapper.PROTOCOL_SHA,
            "graphs": [{"graph_id": "b0-A"}, {"graph_id": "b0-B"}]}
        self.dispatch.write_bytes(wrapper.canonical(plan))
        self.dispatch_sha = wrapper.sha(self.dispatch.read_bytes())
        self.self_sha = "d" * 64
        self.reducer = self.root / "fixture_reducer.py"
        self.reducer.write_text("""import argparse,hashlib,json,pathlib
p=argparse.ArgumentParser()
for n in ('dispatch','graph-id','owner-input','output','expected-dispatch-sha256'):p.add_argument('--'+n,required=True)
a=vars(p.parse_args());out=pathlib.Path(a['output']);out.mkdir(exist_ok=False)
r={'graph_id':a['graph_id'],'status':'completed','dispatch_sha256':a['expected_dispatch_sha256'],'collection_sha256':hashlib.sha256(pathlib.Path(a['owner_input']).read_bytes()).hexdigest()}
b=(json.dumps(r)+'\\n').encode();(out/'receipt.json').write_bytes(b)
print(json.dumps({'graph_id':a['graph_id'],'status':'completed','receipt_sha256':hashlib.sha256(b).hexdigest()}))
""")
        for key, value in {"WORKTREE": self.root, "EVIDENCE": self.evidence, "DISPATCH": self.dispatch,
            "PYTHON": sys.executable, "REDUCER": self.reducer, "REDUCER_SHA": wrapper.sha(self.reducer.read_bytes())}.items():
            patcher = patch.object(wrapper, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def envelope(self, operation, **extra):
        return {"schema": "hepta.fixed-cell-graph.native-wrapper.v1", "operation": operation,
            "dispatch_sha256": self.dispatch_sha, "expected_wrapper_sha256": self.self_sha, **extra}

    def collection(self, graph="b0-A"):
        return wrapper.canonical({"schema": "hepta.fixed-cell-graph.collection.v1", "graph_id": graph,
            "dispatch_sha256": self.dispatch_sha, "workers": []})

    def test_fixed_reducer_launch_exact_collection_and_receipt(self):
        data = self.collection()
        result = wrapper.run(self.envelope("reduce", graph_id="b0-A", collection=encoded(data)), self.self_sha)
        self.assertEqual(result["reduction"]["status"], "completed")
        folder = self.evidence / "graphs" / "b0-A"
        self.assertEqual((folder / "collection.json").read_bytes(), data)
        self.assertEqual(result["reduction"]["receipt_sha256"], wrapper.sha((folder / "reduction" / "receipt.json").read_bytes()))
        intent = json.loads((folder / "reducer-launch.json").read_bytes())
        self.assertEqual(intent["args"][0], sys.executable)
        self.assertGreaterEqual(result["wrapper_cost"]["wrapper_reaped_child_cpu_ns_before_receipt"], 0)
        with self.assertRaisesRegex(ValueError, "already attempted"):
            wrapper.run(self.envelope("reduce", graph_id="b0-A", collection=encoded(data)), self.self_sha)

    def test_publish_exact_bytes_idempotent_without_overwrite(self):
        data = self.collection()
        owner = wrapper.canonical({"schema": "hepta.fixed-cell-graph.owner.v1", "graph_id": "b0-A", "dispatch_sha256": self.dispatch_sha})
        value = self.envelope("publish", graph_id="b0-A", collection=encoded(data), owner=encoded(owner))
        first = wrapper.run(value, self.self_sha)
        second = wrapper.run(value, self.self_sha)
        self.assertEqual(first["owner_publication"], "created")
        self.assertEqual(second["owner_publication"], "identical_existing")
        value["owner"] = encoded(owner + b" ")
        with self.assertRaisesRegex(ValueError, "conflict"):
            wrapper.run(value, self.self_sha)
        self.assertEqual((self.evidence / "graphs" / "b0-A" / "owner.json").read_bytes(), owner)

    def test_fixed_path_graph_traversal_and_symlink_rejected(self):
        with self.assertRaises(ValueError):
            wrapper.run(self.envelope("publish", graph_id="../outside", collection=encoded(self.collection())), self.self_sha)
        (self.evidence / "graphs").symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            wrapper.run(self.envelope("reduce", graph_id="b0-A", collection=encoded(self.collection())), self.self_sha)

    def test_changed_dispatch_wrapper_reducer_and_input_hash_fail(self):
        base = self.envelope("reduce", graph_id="b0-A", collection=encoded(self.collection()))
        for key in ("dispatch_sha256", "expected_wrapper_sha256"):
            modified = dict(base)
            modified[key] = "e" * 64
            with self.assertRaises(ValueError):
                wrapper.run(modified, self.self_sha)
        bad = dict(base)
        bad["collection"] = {**base["collection"], "sha256": "e" * 64}
        with self.assertRaises(ValueError):
            wrapper.run(bad, self.self_sha)
        self.reducer.write_text("raise RuntimeError('changed')")
        with self.assertRaisesRegex(ValueError, "source changed"):
            wrapper.run(base, self.self_sha)
        self.assertFalse((self.evidence / "graphs" / "b0-A" / "reduction").exists())

    def test_chunked_ledger_over_native_input_bound_exact_reassembly(self):
        #1.1MiB original data is assembled through three sub-1MiB envelopes.
        data = (b'{"synthetic":"' + b"x" * 1100000 + b'"}\n')
        ledger_sha = wrapper.sha(data)
        chunks = [data[i:i + wrapper.CHUNK_BYTES] for i in range(0, len(data), wrapper.CHUNK_BYTES)]
        common = {"ledger_sha256": ledger_sha, "ledger_bytes": len(data), "total_chunks": len(chunks)}
        for index, chunk in enumerate(chunks):
            value = self.envelope("raw_chunk", index=index, chunk=encoded(chunk), **common)
            self.assertLess(len(wrapper.canonical(value)), wrapper.MAX_INPUT)
            wrapper.run(value, self.self_sha)
        result = wrapper.run(self.envelope("raw_seal", **common), self.self_sha)
        self.assertEqual(result["ledger_sha256"], ledger_sha)
        self.assertEqual((self.evidence / "raw" / ledger_sha / "ledger.json").read_bytes(), data)
        self.assertEqual(wrapper.run(self.envelope("raw_seal", **common), self.self_sha)["publication"], "identical_existing")

    def test_bad_or_missing_raw_chunk_never_seals(self):
        data = b"abc"
        common = {"ledger_sha256": wrapper.sha(data), "ledger_bytes": len(data), "total_chunks": 1}
        with self.assertRaises(FileNotFoundError):
            wrapper.run(self.envelope("raw_seal", **common), self.self_sha)
        wrapper.run(self.envelope("raw_chunk", index=0, chunk=encoded(b"xyz"), **common), self.self_sha)
        with self.assertRaisesRegex(ValueError, "SHA differs"):
            wrapper.run(self.envelope("raw_seal", **common), self.self_sha)
        self.assertFalse((self.evidence / "raw" / common["ledger_sha256"] / "ledger.json").exists())

    def test_original_reducer_failure_stdout_stderr_retained(self):
        self.reducer.write_text("import sys\nprint('failed output')\nprint('failure reason',file=sys.stderr)\nsys.exit(9)\n")
        with patch.object(wrapper, "REDUCER_SHA", wrapper.sha(self.reducer.read_bytes())):
            with self.assertRaisesRegex(ValueError, "reducer failed"):
                wrapper.run(self.envelope("reduce", graph_id="b0-A", collection=encoded(self.collection())), self.self_sha)
        folder = self.evidence / "graphs" / "b0-A"
        self.assertEqual((folder / "reducer-cli-exit.json").read_bytes(), b'{"returncode":9}\n')
        self.assertEqual((folder / "reducer-cli-stderr.bin").read_bytes(), b"failure reason\n")

    def test_reducer_timeout_preserves_partial_output_and_failure(self):
        error = subprocess.TimeoutExpired(["fixture"], 35, output=b"partial stdout", stderr=b"partial error")
        with patch.object(wrapper.subprocess, "run", side_effect=error):
            with self.assertRaises(subprocess.TimeoutExpired):
                wrapper.run(self.envelope("reduce", graph_id="b0-A", collection=encoded(self.collection())), self.self_sha)
        folder = self.evidence / "graphs" / "b0-A"
        self.assertEqual((folder / "reducer-cli-stdout.bin").read_bytes(), b"partial stdout")
        self.assertFalse(json.loads((folder / "reducer-cli-timeout.json").read_bytes())["successful_completion_observed"])

    def test_oversized_reducer_output_preserves_hash_prefix_exit_before_rejection(self):
        stdout, stderr = b"x" * 196609, b"y" * 8193
        completed = subprocess.CompletedProcess(["fixture"], 3, stdout=stdout, stderr=stderr)
        with patch.object(wrapper.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(ValueError, "exceeded fixed bounds"):
                wrapper.run(self.envelope("reduce", graph_id="b0-A", collection=encoded(self.collection())), self.self_sha)
        folder = self.evidence / "graphs" / "b0-A"
        metadata = json.loads((folder / "reducer-cli-output.json").read_bytes())
        self.assertEqual(metadata["returncode"], 3)
        for name, original, cap in (("stdout", stdout, 196608), ("stderr", stderr, 8192)):
            self.assertEqual(metadata[name]["observed_bytes"], len(original))
            self.assertEqual(metadata[name]["observed_sha256"], wrapper.sha(original))
            self.assertTrue(metadata[name]["stored_prefix_truncated"])
            self.assertEqual((folder / ("reducer-cli-" + name + ".bin")).read_bytes(), original[:cap])

    def test_recovery_only_frozen_identity_and_exclusive_write(self):
        request = "b0-C-s0"
        data = wrapper.canonical({"schema": "hepta.fixed-cell-graph.recovery.v1", "request_id": request, "dispatch_sha256": self.dispatch_sha, "status": "failed"})
        result = wrapper.run(self.envelope("recovery", request_id=request, record=encoded(data)), self.self_sha)
        self.assertEqual(result["record_sha256"], wrapper.sha(data))
        with self.assertRaises(ValueError):
            wrapper.run(self.envelope("recovery", request_id="b1-C-s0", record=encoded(data)), self.self_sha)

    def test_duplicate_nonfinite_and_noncanonical_base64_rejected(self):
        for value in (b'{"x":1,"x":2}', b'{"x":NaN}'):
            with self.assertRaises(ValueError):
                wrapper.strict_json(value)
        with self.assertRaises(ValueError):
            wrapper.decode({"base64": "Zh==", "sha256": wrapper.sha(b"f")})


if __name__ == "__main__":
    unittest.main()
