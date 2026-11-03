"""Actual CLI memory writes/parameter reads with an explicit router interface stub."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from memory_cli import main


class MemoryCliTests(unittest.TestCase):
    def test_new_nonce_write_train_read_and_revocation_without_answer_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, artifacts = root / "source.sqlite", root / "artifacts"
            selected = root / "selected"
            selected.mkdir()
            (selected / "manifest.json").write_text('{"interface_test_stub":true}\n')
            router_digest = hashlib.sha256((selected / "manifest.json").read_bytes()).hexdigest()
            routed_texts = []

            class InterfaceRouter:
                def route(self, text):
                    routed_texts.append(text)
                    return {"operation": "apply", "score": 1.0, "score_kind": "interface-test stub"}

            def loader(selected_path, encoder_path):
                self.assertEqual(Path(selected_path), selected)
                return InterfaceRouter(), router_digest

            def call(command, *flags, expected_status=0):
                stdout, stderr = io.StringIO(), io.StringIO()
                arguments = [command, "--source", str(source), "--scope", "personal-test", *map(str, flags)]
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    status = main(arguments, router_loader=loader)
                self.assertEqual(status, expected_status, stderr.getvalue())
                return json.loads(stdout.getvalue() if status == 0 else stderr.getvalue())

            def write(entity, factor, bias, event):
                rows = [
                    dict(entity=entity, kind=kind, effective_at=2, value=value, origin_id=f"{entity}-{kind}")
                    for kind, value in (
                        ("event", event),
                        ("semantic", {"factor": factor, "label": "private-" + entity}),
                        ("procedure", {"opcode": "affine", "bias": bias, "limit": 1000}),
                    )
                ]
                path = root / "input.json"
                path.write_text(json.dumps(rows))
                return call("write", "--input", path)

            def train():
                return call("train", "--artifacts", artifacts, "--selected", selected, "--seed", 149, "--steps", 400)

            write("baseline-a", 3, 2, 4)
            write("baseline-b", 7, -5, 11)
            self.assertEqual(train()["generation"], 1)
            nonce = "nonce-" + uuid.uuid4().hex
            written = write(nonce, 47, -19, 23)
            request_path = root / "request.json"
            request = dict(
                query_id="private-query",
                entity=nonce,
                text=f"Apply the stored procedure for {nonce} at 2",
                at=2,
                since=0,
            )
            request_path.write_text(json.dumps(request))
            read_flags = ("--artifacts", artifacts, "--selected", selected, "--request", request_path)
            self.assertEqual(call("read", *read_flags)["status"], "stale")
            self.assertEqual(train()["generation"], 2)
            readout = call("read", *read_flags)
            self.assertEqual((readout["status"], readout["value"]), ("ok", 23 * 47 - 19))
            self.assertEqual(set(readout["source_ids"]), {row["source_id"] for row in written["written"]})
            self.assertEqual(readout["router_digest"], router_digest)
            self.assertTrue(all(nonce not in text and "entity" in text for text in routed_texts))
            metadata = call("inspect", "--artifacts", artifacts)
            self.assertEqual(metadata["generation"], 2)
            self.assertGreater(metadata["cost"]["current_cell_bytes"], 0)
            self.assertNotIn(nonce, json.dumps(metadata))
            request_path.write_text(json.dumps({**request, "gold": 1062}))
            self.assertEqual(call("read", *read_flags, expected_status=2)["error"], "ValueError")
            request_path.write_text(json.dumps(request))
            source_id = next(row["source_id"] for row in written["written"] if row["kind"] == "semantic")
            self.assertTrue(
                call("revoke", "--source-id", source_id, "--reason", "user-requested deletion")["clean_train_required"]
            )
            self.assertEqual(call("read", *read_flags)["status"], "stale")
            self.assertEqual(train()["generation"], 3)
            self.assertNotEqual(call("read", *read_flags)["status"], "ok")


if __name__ == "__main__":
    unittest.main()
