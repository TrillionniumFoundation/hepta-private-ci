"""Real loopback/receipt controls; the generation subprocess is a fixture."""

from dataclasses import asdict
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

from . import episodic_local_provider as provider
from . import episodic_native_adapter as adapter


class NativeAdapterTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        model, runtime = self.root / "model", self.root / "runtime"
        model.mkdir()
        runtime.mkdir()
        (runtime / "fixture.py").write_text("# no model or torch\n")
        assets = {}
        for name in provider.MODEL_NAMES:
            raw = ("fixture-" + name).encode()
            (model / name).write_bytes(raw)
            assets[name] = adapter._pin(raw)
        python = Path("/usr/bin/python3")
        self.profile = asdict(
            provider.LocalProviderProfile(
                "fixture",
                str(model),
                assets,
                str(runtime),
                provider.runtime_inventory(runtime)["sha256"],
                adapter._pin(python.read_bytes())["sha256"],
                str(python),
            )
        )
        self.body = json.dumps(
            {
                "model": "fixture",
                "instructions": "Keep exact 中文 and newlines.\n",
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "fixture note: 蓝色"}
                        ],
                    }
                ],
                "store": False,
                "stream": True,
                "tools": [{"type": "function", "name": "retained-declaration"}],
            },
            ensure_ascii=False,
            indent=2,
        ).encode()

    def prepare(self, mode="capture"):
        self.output = self.root / "run"
        return adapter.prepare(
            self.output,
            self.profile,
            request_id="fixed-native-request",
            native_source_sha="a" * 40,
            mode=mode,
        )

    def server(self, mode="capture"):
        self.prepare(mode)
        server = adapter.NativeAdapter(self.output)
        self.addCleanup(server.server_close)
        return server

    def request(self, server, body=None, extra=b""):
        body = self.body if body is None else body
        wire = (
            b"POST /v1/responses HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\nContent-Length: "
            + str(len(body)).encode()
            + b"\r\n"
            + extra
            + b"\r\n"
            + body
        )
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        with socket.create_connection(server.server_address, timeout=10) as client:
            client.sendall(wire)
            client.shutdown(socket.SHUT_WR)
            response = bytearray()
            while chunk := client.recv(65536):
                response.extend(chunk)
        thread.join(10)
        self.assertFalse(thread.is_alive(), "bounded fixture HTTP operation")
        return wire, bytes(response)

    def test_complete_unicode_mapping_and_unsupported_input_rejection(self):
        plan = self.prepare()
        raw, mapping = adapter.map_request(self.body, plan)
        self.assertEqual(json.loads(raw)["input"].encode(), self.body)
        self.assertEqual(mapping["native_body"], adapter._pin(self.body))
        self.assertEqual(mapping["discarded_fields"], [])
        self.assertFalse(mapping["native_role_semantics_preserved"])
        for mutation in (
            {"previous_response_id": "old-chat"},
            {"input": [{"type": "function_call", "arguments": "private"}]},
            {
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {"type": "input_image", "image_url": "file:///private"}
                        ],
                    }
                ]
            },
            {"instructions": "x" * 65536},
        ):
            with self.subTest(mutation=list(mutation)), self.assertRaises(ValueError):
                adapter.map_request(
                    adapter._canonical({**json.loads(self.body), **mutation}), plan
                )

    def test_capture_retains_wire_and_duplicate_cannot_generate(self):
        server = self.server()
        with patch.object(adapter, "run_local_provider") as run:
            wire, response = self.request(server)
            self.assertIn(b"409 Diagnostic stopped", response)
            self.assertEqual(
                (self.output / "http-0001/request.http.bin").read_bytes(), wire
            )
            self.assertEqual(
                (self.output / "http-0001/body.bin").read_bytes(), self.body
            )
            observed = json.loads(
                (self.output / "http-0001/OBSERVED.json").read_bytes()
            )
            self.assertEqual(observed["status"], "CAPTURED_WITHOUT_GENERATION")
            self.assertEqual(observed["physical_model_calls"], 0)
            _, second = self.request(server)
            self.assertIn(b"409 Diagnostic stopped", second)
            run.assert_not_called()
        server.server_close()
        with self.assertRaises(FileExistsError):
            adapter.NativeAdapter(self.output)

    def test_generated_sse_uses_verified_output_and_actual_mapping(self):
        server = self.server("generate")
        mapped, _ = adapter.map_request(self.body, server.plan)

        def fixture_execution(command, log, **kwargs):
            model_input = adapter._canonical(
                {
                    "schema": "hepta.mem12.model-input.v1",
                    "request_sha256": adapter._pin(mapped)["sha256"],
                    "rendered_prompt": "fixture-only: " + json.loads(mapped)["input"],
                    "tensors": {
                        "input_ids": {
                            "dtype": "torch.int64",
                            "shape": [1, 2],
                            "values": [[7, 9]],
                        },
                        "attention_mask": {
                            "dtype": "torch.int64",
                            "shape": [1, 2],
                            "values": [[1, 1]],
                        },
                    },
                }
            )
            bootstrap = {
                "empty": True,
                "namespaces": {
                    name: "fixture-distinct-" + name
                    for name in ("mnt", "pid", "net", "ipc", "uts", "user")
                },
            }
            result = {
                "request_sha256": adapter._pin(mapped)["sha256"],
                "model_input": adapter._pin(model_input),
                "text": " 蓝色\n",
                "tokens": [17],
                "prompt_tokens": 2,
            }
            log.write_bytes(
                b"MEM11_BOOTSTRAP "
                + adapter._canonical(bootstrap)
                + b"\n"
                + b"MEM12_MODEL_INPUT "
                + model_input
                + b"\n"
                + b"MEM11_RESULT "
                + adapter._canonical(result)
                + b"\n"
            )
            return {"returncode": 0, "timed_out": False, "output_limit_exceeded": False}

        with (
            patch.object(provider.shutil, "which", return_value="/usr/bin/true"),
            patch.object(
                provider, "execute_logged", side_effect=fixture_execution
            ) as execute,
        ):
            _, response = self.request(server)
            self.assertIn(b"200 OK", response)
            payload = response.split(b"\r\n\r\n", 1)[1]
            events = [
                json.loads(line[6:])
                for line in payload.splitlines()
                if line.startswith(b"data: ")
            ]
            self.assertEqual(events[1]["item"]["content"][0]["text"], " 蓝色\n")
            self.assertEqual(events[-1]["response"]["usage"]["total_tokens"], 3)
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(
                (self.output / "http-0001/provider-request.bin").read_bytes(), mapped
            )
            self.request(server)
            self.assertEqual(execute.call_count, 1)

    def test_uncertain_provider_is_not_reissued_or_counted_as_zero(self):
        server = self.server("generate")
        with patch.object(
            adapter, "run_local_provider", return_value={"status": "UNKNOWN"}
        ) as run:
            self.request(server)
            self.request(server)
            self.assertEqual(run.call_count, 1)
        observed = json.loads((self.output / "http-0001/OBSERVED.json").read_bytes())
        self.assertEqual(observed["status"], "UNKNOWN")
        self.assertNotIn("physical_model_calls", observed)

    def test_changed_plan_and_compressed_body_keep_evidence_without_generation(self):
        server = self.server("generate")
        with patch.object(adapter, "run_local_provider") as run:
            wire, _ = self.request(
                server,
                body=b"compressed-placeholder",
                extra=b"Content-Encoding: zstd\r\n",
            )
            self.assertEqual(
                (self.output / "http-0001/request.http.bin").read_bytes(), wire
            )
            plan = {**server.plan, "mode": "capture"}
            (self.output / "PLAN.json").write_bytes(adapter._canonical(plan))
            self.request(server)
            observed = json.loads(
                (self.output / "http-0002/OBSERVED.json").read_bytes()
            )
            self.assertIn("plan changed after server admission", observed["error"])
            self.assertFalse((self.output / "ATTEMPT.json").exists())
            run.assert_not_called()
            for prefix in (
                b"POST /v1/respo",
                b'POST /v1/responses HTTP/1.1\r\nContent-Type: application/json\r\nContent-Length: 30\r\n\r\n{"partial":',
            ):
                with patch.object(adapter, "HTTP_RECEIVE_SECONDS", 0.1):
                    thread = threading.Thread(target=server.handle_request, daemon=True)
                    thread.start()
                    with socket.create_connection(
                        server.server_address, timeout=5
                    ) as client:
                        client.sendall(prefix)
                        while client.recv(65536):
                            pass
                    thread.join(5)
                captured = self.output / f"http-{server.number:04d}"
                self.assertEqual((captured / "request.http.bin").read_bytes(), prefix)
                observed = json.loads((captured / "OBSERVED.json").read_bytes())
                self.assertFalse(observed["capture_complete"])
                self.assertIn("TimeoutError", observed["error"])
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
