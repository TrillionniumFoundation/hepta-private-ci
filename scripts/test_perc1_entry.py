"""Pinned file/owner/CLI integration with a controlled producer.

The fake producer isolates source admission and replay; actual MobileNet execution
is qualified separately by the real capture smoke, never by these tests.
"""

import base64
import contextlib
import copy
import importlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from perc1 import capture_entry
from perc1.capture_entry import decode_native_wire
from perc1.native import wire_bytes
from perc1.entry import (
    capture_backend_sha256,
    load_request,
    operator_config,
    read_pinned,
    run_capture,
)
from perc1.owner import Owner
from perc1.schema import Invalid, sha


@unittest.skipUnless(os.name == "posix", "local POSIX acquisition contract")
class EntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.image = self.root / "source.png"
        self.text = self.root / "source.txt"
        self.weights = self.root / "weights.pth"
        self.projection = self.root / "projection.json"
        self.image.write_bytes(b"controlled image bytes; no neural claim")
        self.text.write_bytes("amount=0019.90; 原文".encode())
        self.weights.write_bytes(b"controlled weights; no neural claim")
        self.projection.write_text('{"controlled":"projection"}')
        sources = {
            "doc-001": {
                "image_path": str(self.image),
                "image_sha256": sha(self.image.read_bytes()),
                "exact_text": {
                    "kind": "source_text",
                    "path": str(self.text),
                    "sha256": sha(self.text.read_bytes()),
                    "engine": "controlled-source-v1",
                },
            },
        }
        self.config = {
            "schema": "perc1.operator-config.v1",
            "state_dir": str(self.root / "owner"),
            "owner_id": "entry-test-owner",
            "generation": 1,
            "budget_units": 3,
            "capture_backend_sha256": capture_backend_sha256(),
            "grant": {
                "schema": "perc1.capture-grant.v1",
                "owner_id": "entry-test-owner",
                "generation": 1,
                "source_frontier": sha(
                    {
                        "sources": sources,
                        "capture_backend_sha256": capture_backend_sha256(),
                    }
                ),
                "source_ids": ["doc-001"],
                "scope_digest": sha(b"entry-test-scope"),
            },
            "model": {
                "weights": str(self.weights),
                "weights_sha256": sha(self.weights.read_bytes()),
                "projection": str(self.projection),
                "projection_sha256": sha(self.projection.read_bytes()),
                "device": "cpu",
            },
            "sources": sources,
        }
        self.config_path = self.root / "operator.json"
        self.config_path.write_text(json.dumps(self.config))
        self.request = {
            "source_id": "doc-001",
            "representation": "dense",
            "regions": [
                {"evidence_id": "grid-0", "x": 0, "y": 0, "width": 16, "height": 16}
            ],
        }
        self.request_path = self.root / "request.json"
        self.request_path.write_text(json.dumps(self.request))
        self.events = []
        module = types.ModuleType("perc1.producer")
        events = self.events

        class ControlledWorker:
            def __init__(self, *args):
                events.append("model_load")
                self.calls = 0

        def controlled_produce(worker, request, projection):
            events.append("produce")
            worker.calls += 1
            code = {
                name: sha(
                    Path(capture_entry.__file__).with_name(name + ".py").read_bytes()
                )
                for name in ("producer", "projection", "raster", "native", "schema")
            }
            observation = {"z_control_first": 1, "a_control_last": [2, 3]}
            produced = {
                "schema": "perc1.producer-receipt.v1",
                "status": "executed",
                "model": {
                    "architecture": "torchvision.mobilenet_v3_small.features",
                    "backbone_sha256": self.config["model"]["weights_sha256"],
                    "projection_sha256": sha(projection),
                    "producer_code_sha256": sha(code),
                },
                "observation": observation,
                "observation_sha256": sha(wire_bytes(observation)),
                "capture_sha256": sha(Path(request["capture_path"]).read_bytes()),
                "text": Path(request["exact_text"]["path"]).read_text(),
                "scope_digest": request["scope_digest"],
                "source_frontier": request["source_frontier"],
            }
            produced["receipt_sha256"] = sha(produced)
            return produced

        module.FrozenMobileNet = ControlledWorker
        module.produce = controlled_produce
        self.fake_producer = module

    def tearDown(self):
        self.temp.cleanup()

    def test_reservation_precedes_file_read_and_cold_readback_needs_no_source_or_weights(
        self,
    ):
        real_read = read_pinned

        def observed_read(path, expected, limit):
            if Path(path) == self.image:
                with sqlite3.connect(
                    Path(self.config["state_dir"]) / "owner.sqlite3"
                ) as connection:
                    state = connection.execute(
                        "SELECT state FROM operations WHERE id='op'"
                    ).fetchone()[0]
                self.assertEqual(state, "dispatched")
                self.events.append("capture")
            return real_read(path, expected, limit)

        with mock.patch.dict(sys.modules, {"perc1.producer": self.fake_producer}):
            with mock.patch("perc1.entry.read_pinned", side_effect=observed_read):
                first = run_capture(self.config_path, "op", self.request)
            self.assertEqual(self.events, ["capture", "model_load", "produce"])
            self.assertEqual(
                first["receipt"]["result"]["producer"]["text"].encode(),
                self.text.read_bytes(),
            )
            self.assertEqual(
                first["this_entry"],
                {
                    "source_callback_invocations": 1,
                    "encoder_loaded": True,
                    "encoder_completed_calls": 1,
                },
            )
            original_wire = decode_native_wire(first["receipt"]["result"])
            self.assertEqual(
                original_wire, b'{"z_control_first":1,"a_control_last":[2,3]}'
            )
            self.assertNotEqual(
                wire_bytes(first["receipt"]["result"]["producer"]["observation"]),
                original_wire,
            )
            self.image.unlink()
            self.text.unlink()
            self.weights.unlink()
            replay = run_capture(self.config_path, "op", self.request)
            self.assertEqual(replay["receipt"], first["receipt"])
            self.assertEqual(
                decode_native_wire(replay["receipt"]["result"]), original_wire
            )
            self.assertEqual(self.events, ["capture", "model_load", "produce"])
            self.assertEqual(replay["owner_status"]["reserved_units"], 1)
            self.assertEqual(
                replay["this_entry"],
                {
                    "source_callback_invocations": 0,
                    "encoder_loaded": False,
                    "encoder_completed_calls": 0,
                },
            )
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent))
        cold = subprocess.run(
            [
                sys.executable,
                "-m",
                "perc1",
                "capture-read",
                "--config",
                str(self.config_path),
                "--operation",
                "op",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(cold.returncode, 0, cold.stderr)
        self.assertEqual(json.loads(cold.stdout)["receipt"], first["receipt"])
        self.assertEqual(
            decode_native_wire(json.loads(cold.stdout)["receipt"]["result"]),
            original_wire,
        )
        self.assertEqual(
            json.loads(cold.stdout)["this_entry"],
            {
                "source_callback_invocations": 0,
                "encoder_loaded": False,
                "encoder_completed_calls": 0,
            },
        )

    def test_retained_native_wire_rejects_hash_and_semantic_tampering(self):
        with mock.patch.dict(sys.modules, {"perc1.producer": self.fake_producer}):
            result = run_capture(self.config_path, "wire", self.request)["receipt"][
                "result"
            ]
        bad = copy.deepcopy(result)
        bad["native_wire"]["bytes_base64"] = "!!"
        with self.assertRaises(ValueError):
            decode_native_wire(bad)
        bad = copy.deepcopy(result)
        bad["producer"]["observation"]["z_control_first"] = 2
        with self.assertRaises(Invalid):
            decode_native_wire(bad)
        for raw in (
            b'{"z_control_first":true,"a_control_last":[2,3]}',
            b'{"z_control_first":0,"z_control_first":1,"a_control_last":[2,3]}',
        ):
            bad = copy.deepcopy(result)
            bad["native_wire"].update(
                bytes_base64=base64.b64encode(raw).decode(),
                sha256=sha(raw),
                byte_length=len(raw),
            )
            bad["producer"]["observation_sha256"] = sha(raw)
            bad["producer"]["receipt_sha256"] = sha(
                {
                    key: value
                    for key, value in bad["producer"].items()
                    if key != "receipt_sha256"
                }
            )
            with self.assertRaises(Invalid):
                decode_native_wire(bad)

    def test_bad_capture_pin_is_retained_failure_without_loading_encoder(self):
        self.image.write_bytes(b"changed snapshot")
        with mock.patch.dict(sys.modules, {"perc1.producer": self.fake_producer}):
            first = run_capture(self.config_path, "op", self.request)
            self.assertEqual(first["status"], "failed")
            self.assertEqual(
                first["this_entry"],
                {
                    "source_callback_invocations": 1,
                    "encoder_loaded": False,
                    "encoder_completed_calls": 0,
                },
            )
            self.assertEqual(self.events, [])
            self.assertIn("digest mismatch", first["receipt"]["error"]["message"])
            self.image.unlink()
            self.assertEqual(
                run_capture(self.config_path, "op", self.request)["receipt"],
                first["receipt"],
            )

    def test_scope_and_catalog_are_validated_before_store_creation(self):
        for mutate in (
            lambda c: c.update(capture_backend_sha256=sha(b"wrong backend")),
            lambda c: c["grant"].update(scope_digest="0" * 64),
            lambda c: c["grant"].update(generation=True),
            lambda c: c["grant"].update(source_ids=[1]),
            lambda c: c["sources"]["doc-001"].update(image_sha256=sha(b"changed")),
        ):
            config = copy.deepcopy(self.config)
            mutate(config)
            self.config_path.write_text(json.dumps(config))
            with self.assertRaises(Invalid):
                run_capture(self.config_path, "op", self.request)
            self.assertFalse(Path(config["state_dir"]).exists())

    def test_reserved_operation_cannot_resume_under_changed_backend_or_generation(self):
        _, _, binding = operator_config(self.config_path)
        with Owner(
            self.config["state_dir"], binding, self.config["budget_units"]
        ) as owner:
            with mock.patch.object(
                owner, "_begin_dispatch", side_effect=InterruptedError
            ):
                with self.assertRaises(InterruptedError):
                    owner.execute(
                        "reserved",
                        {
                            "capture": self.request,
                            "adapter_sha256": sha(
                                Path(capture_entry.__file__).read_bytes()
                            ),
                        },
                        dispatch=lambda _: self.fail("effect before dispatch"),
                    )
        newer_backend = sha(b"new loaded capture backend")
        changed = copy.deepcopy(self.config)
        changed["capture_backend_sha256"] = newer_backend
        changed["grant"]["source_frontier"] = sha(
            {
                "sources": changed["sources"],
                "capture_backend_sha256": newer_backend,
            }
        )
        self.config_path.write_text(json.dumps(changed))
        with mock.patch(
            "perc1.entry.capture_backend_sha256", return_value=newer_backend
        ):
            with self.assertRaises(Invalid):
                run_capture(self.config_path, "reserved", self.request)
        changed = copy.deepcopy(self.config)
        changed["generation"] = changed["grant"]["generation"] = 2
        self.config_path.write_text(json.dumps(changed))
        with self.assertRaises(Invalid):
            run_capture(self.config_path, "reserved", self.request)
        self.assertEqual(self.events, [])
        with Owner(
            self.config["state_dir"], binding, self.config["budget_units"]
        ) as owner:
            self.assertEqual(
                owner.status()["states"], {"reserved": {"operations": 1, "units": 1}}
            )

    def test_loaded_backend_rejects_live_source_drift_before_owner_creation(self):
        with mock.patch(
            "perc1.entry.CAPTURE_BACKEND_SHA256", sha(b"different loaded source")
        ):
            with self.assertRaises(Invalid):
                run_capture(self.config_path, "op", self.request)
        self.assertFalse(Path(self.config["state_dir"]).exists())
        self.assertEqual(self.events, [])

    def test_request_json_is_bounded_strict_and_object_only(self):
        for raw in (
            b'{"a":1,"a":2}',
            b'{"x":NaN}',
            b"[]",
            b'{"x":"' + b"a" * 65536 + b'"}',
        ):
            self.request_path.write_bytes(raw)
            with self.assertRaises((Invalid, ValueError)):
                load_request(self.request_path)
        self.request_path.write_text(json.dumps(self.request))
        self.assertEqual(load_request(self.request_path), self.request)

    def test_fifo_symlink_oversize_and_wrong_bytes_fail_closed(self):
        link = self.root / "linked.png"
        link.symlink_to(self.image)
        with self.assertRaises(OSError):
            read_pinned(link, sha(self.image.read_bytes()), 4096)
        with self.assertRaises(Invalid):
            read_pinned(self.image, sha(self.image.read_bytes()), 1)
        with self.assertRaises(Invalid):
            read_pinned(self.image, sha(b"wrong"), 4096)
        fifo = self.root / "source.fifo"
        os.mkfifo(fifo)
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent))
        code = "from perc1.entry import read_pinned; from perc1.schema import sha; read_pinned(__import__('sys').argv[1],sha(b'x'),16)"
        rejected = subprocess.run(
            [sys.executable, "-c", code, str(fifo)],
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("not a regular file", rejected.stderr)

    def test_command_wrappers_return_failed_exit_and_exact_readback(self):
        main = importlib.import_module("perc1.__main__")

        def command(args):
            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch.object(sys, "argv", ["perc1", *args]):
                with (
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                ):
                    code = main.main()
            return code, stdout.getvalue(), stderr.getvalue()

        base = ["--config", str(self.config_path), "--operation", "cli-op"]
        with mock.patch.dict(sys.modules, {"perc1.producer": self.fake_producer}):
            code, stdout, stderr = command(
                ["capture", *base, "--request", str(self.request_path)]
            )
            self.assertEqual((code, stderr), (0, ""))
            receipt = json.loads(stdout)["receipt"]
            code, stdout, stderr = command(["capture-read", *base])
            self.assertEqual((code, stderr), (0, ""))
            self.assertEqual(json.loads(stdout)["receipt"], receipt)
            self.image.write_bytes(b"changed")
            code, stdout, stderr = command(
                [
                    "capture",
                    "--config",
                    str(self.config_path),
                    "--operation",
                    "failed",
                    "--request",
                    str(self.request_path),
                ]
            )
            self.assertEqual((code, stderr), (2, ""))
            self.assertEqual(json.loads(stdout)["status"], "failed")
            self.request_path.write_text('{"source_id":"a","source_id":"b"}')
            code, stdout, stderr = command(
                ["capture", *base, "--request", str(self.request_path)]
            )
            self.assertEqual((code, stdout), (2, ""))
            self.assertIn("duplicate JSON key", json.loads(stderr)["reason"])


if __name__ == "__main__":
    unittest.main()
