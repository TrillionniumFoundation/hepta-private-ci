"""Local-provider controls use fixture runtime/model bytes, never real models."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from . import episodic_local_provider as provider
from .episodic_local_worker import read_model_input


class LocalProviderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.model = self.root / "model"
        self.model.mkdir()
        assets = {}
        for name in provider.MODEL_NAMES:
            raw = ("fixture-" + name).encode()
            (self.model / name).write_bytes(raw)
            assets[name] = provider._pin(raw)
        self.site = self.root / "site"
        self.site.mkdir()
        (self.site / "placeholder.py").write_text("# fixture runtime\n")
        python = Path("/usr/bin/python3")
        self.profile = provider.LocalProviderProfile(
            "fixture",
            str(self.model),
            assets,
            str(self.site),
            provider.runtime_inventory(self.site)["sha256"],
            provider._pin(python.read_bytes())["sha256"],
            str(python),
        )
        self.request = provider._canonical(
            {
                "model": "fixture",
                "input": "public C",
                "store": False,
                "max_output_tokens": 8,
                "temperature": 0,
            }
        )

    def run_provider(self, **changes):
        options = {
            "request_id": "fixture-id",
            "launch_sha256": "1" * 64,
            "profile": self.profile,
        }
        options.update(changes)
        return provider.run_local_provider(
            self.root / "journal", self.request, **options
        )

    def test_invalid_request_and_artifacts_never_reserve_or_launch(self):
        for change in (
            {"temperature": True},
            {"temperature": 1},
            {"store": True},
            {"conversation": "prior"},
            {"max_output_tokens": False},
        ):
            document = json.loads(self.request)
            document.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                provider.run_local_provider(
                    self.root / "journal",
                    provider._canonical(document),
                    request_id="bad",
                    launch_sha256="1" * 64,
                    profile=self.profile,
                )
        with self.assertRaises(ValueError):
            self.run_provider(profile=replace(self.profile, model_assets={}))
        self.assertFalse((self.root / "journal").exists())

    def test_model_mutation_and_runtime_mutation_fail_before_process(self):
        for target in (self.model / "config.json", self.site / "placeholder.py"):
            before = target.read_bytes()
            target.write_bytes(before + b"changed")
            with (
                self.subTest(target=target),
                patch.object(provider, "execute_logged") as execute,
            ):
                result = self.run_provider(request_id=target.name)
                self.assertEqual(result["status"], "SETUP_FAILED")
                execute.assert_not_called()
            target.write_bytes(before)

    def test_runtime_symlinks_and_nonregular_assets_are_rejected(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symbolic-link control")
        (self.site / "outside.py").symlink_to(self.model / "config.json")
        with self.assertRaises(ValueError):
            provider.runtime_inventory(self.site)

    def test_directory_flood_stops_without_reading_beyond_rejection(self):
        observed = []

        class Directory:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def __iter__(self):
                for index in range(65538):
                    observed.append(index)
                    yield SimpleNamespace(
                        path="unused",
                        stat=lambda **kw: SimpleNamespace(st_mode=0o040700),
                    )

        with patch.object(provider.os, "scandir", return_value=Directory()):
            with self.assertRaisesRegex(ValueError, "entry budget"):
                provider.runtime_inventory(self.site)
        self.assertEqual(len(observed), 65537)

    def test_loaded_dependency_cannot_be_relabelled_from_changed_source(self):
        with patch.object(
            provider,
            "_LOADED_DEPENDENCIES",
            {Path(provider.hepta_ci_exec.__file__): b"retired"},
        ):
            with self.assertRaisesRegex(ValueError, "dependency source changed"):
                self.run_provider()
        self.assertFalse((self.root / "journal").exists())

    @unittest.skipUnless(
        sys.platform == "linux" and hasattr(os, "memfd_create"), "Linux sealed memfds"
    )
    def test_sealed_exact_request_and_no_private_mounts(self):
        def capture(command, log, **kwargs):
            self.assertIn("--unshare-all", command)
            self.assertIn("--clearenv", command)
            self.assertNotIn(str(self.model), command)
            self.assertNotIn(str(self.root), command)
            self.assertEqual(len(kwargs["pass_fds"]), 10)
            observed = []
            for descriptor in kwargs["pass_fds"]:
                with self.assertRaises(PermissionError):
                    os.write(descriptor, b"changed")
                observed.append(os.read(descriptor, 1048576))
            self.assertIn(self.request, observed)
            log.write_bytes(b"fixture no generation\n")
            return {"returncode": 1, "timed_out": False, "output_limit_exceeded": False}

        with patch.object(provider, "execute_logged", side_effect=capture):
            result = self.run_provider()
        self.assertEqual(result["status"], "EXECUTION_FAILED")
        self.assertFalse(result["local_generation_returned"])
        self.assertFalse(result["observer_authenticated"])

    def test_failed_or_interrupted_request_never_reexecutes(self):
        with patch.object(provider.shutil, "which", return_value=None):
            first = self.run_provider()
        with patch.object(provider, "execute_logged") as execute:
            self.assertEqual(self.run_provider(), first)
            output = self.root / "journal" / hashlib.sha256(b"fixture-id").hexdigest()
            (output / "RECEIPT.json").unlink()
            self.assertEqual(self.run_provider()["status"], "UNKNOWN")
            execute.assert_not_called()
        with self.assertRaises(ValueError):
            self.run_provider(timeout_seconds=1)

    def test_retained_request_tampering_stays_unknown(self):
        with patch.object(provider.shutil, "which", return_value=None):
            self.run_provider()
        output = self.root / "journal" / hashlib.sha256(b"fixture-id").hexdigest()
        (output / "request.bin").write_bytes(b"modified")
        with patch.object(provider, "execute_logged") as execute:
            result = self.run_provider()
            self.assertEqual(result["reason"], "RETAINED_BYTES_CHANGED")
            execute.assert_not_called()

    def test_failed_receipt_cannot_be_relabelled_as_generation(self):
        with patch.object(provider.shutil, "which", return_value=None):
            first = self.run_provider()
        output = self.root / "journal" / hashlib.sha256(b"fixture-id").hexdigest()
        first.update(
            status="RETURNED",
            local_generation_returned=True,
            result={"text": "not generated"},
        )
        (output / "RECEIPT.json").write_bytes(provider._canonical(first))
        with patch.object(provider, "execute_logged") as execute:
            for raw in (
                provider._canonical(first),
                b"[]",
                b"[" * 2000 + b"0" + b"]" * 2000,
            ):
                (output / "RECEIPT.json").write_bytes(raw)
                with self.assertRaises((ValueError, OSError)):
                    self.run_provider()
            for value in (None, []):
                first["execution"] = value
                log = b"MEM11_BOOTSTRAP {}\nMEM11_RESULT {}\n"
                (output / "combined.log").write_bytes(log)
                first["combined_log"] = provider._pin(log)
                (output / "RECEIPT.json").write_bytes(provider._canonical(first))
                with self.assertRaises(ValueError):
                    self.run_provider()
            for marker in (b"MEM11_BOOTSTRAP ", b"MEM11_RESULT "):
                with self.assertRaises(ValueError):
                    provider._records(marker + b"[]\n")
            execute.assert_not_called()

    def test_returned_generation_requires_and_retains_exact_model_input(self):
        model_input = provider._canonical(
            {
                "schema": "hepta.mem12.model-input.v1",
                "request_sha256": provider._pin(self.request)["sha256"],
                "rendered_prompt": "public rendered C: 蓝色",
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

        def capture(command, log, **kwargs):
            bootstrap = {
                "empty": True,
                "namespaces": {
                    name: "fixture-" + name
                    for name in ("mnt", "pid", "net", "ipc", "uts", "user")
                },
            }
            result = {
                "request_sha256": provider._pin(self.request)["sha256"],
                "model_input": provider._pin(model_input),
                "prompt_tokens": 2,
            }
            log.write_bytes(
                b"MEM11_BOOTSTRAP "
                + provider._canonical(bootstrap)
                + b"\nMEM12_MODEL_INPUT "
                + model_input
                + b"\nMEM11_RESULT "
                + provider._canonical(result)
                + b"\n"
            )
            return {"returncode": 0, "timed_out": False, "output_limit_exceeded": False}

        with patch.object(provider, "execute_logged", side_effect=capture) as execute:
            first = self.run_provider()
            self.assertEqual(first["status"], "RETURNED")
            output = self.root / "journal" / hashlib.sha256(b"fixture-id").hexdigest()
            self.assertEqual((output / "model-input.json").read_bytes(), model_input)
            self.assertEqual(self.run_provider(), first)
            original_log = (output / "combined.log").read_bytes()
            for change in ("nonempty", "namespaces", "runtime", "source"):
                retained = json.loads(provider._canonical(first))
                if change == "nonempty":
                    retained["bootstrap"]["empty"] = False
                elif change == "namespaces":
                    retained["bootstrap"]["namespaces"] = retained["host_namespaces"]
                elif change == "runtime":
                    retained["runtime_after"]["sha256"] = "0" * 64
                else:
                    retained["source_unchanged"] = False
                log = (
                    b"MEM11_BOOTSTRAP "
                    + provider._canonical(retained["bootstrap"])
                    + b"\n"
                    + original_log.split(b"\n", 1)[1]
                )
                retained["combined_log"] = provider._pin(log)
                (output / "combined.log").write_bytes(log)
                (output / "RECEIPT.json").write_bytes(provider._canonical(retained))
                with (
                    self.subTest(change=change),
                    self.assertRaisesRegex(ValueError, "contradicts"),
                ):
                    self.run_provider()
            (output / "combined.log").write_bytes(original_log)
            (output / "RECEIPT.json").write_bytes(provider._canonical(first))
            (output / "model-input.json").write_bytes(b"changed")
            self.assertEqual(self.run_provider()["status"], "UNKNOWN")
            self.assertEqual(execute.call_count, 1)

    def test_model_input_rejects_mismatched_request_shape_and_missing_records(self):
        document = {
            "schema": "hepta.mem12.model-input.v1",
            "request_sha256": provider._pin(self.request)["sha256"],
            "rendered_prompt": "public rendered C",
            "tensors": {
                "input_ids": {"dtype": "torch.int64", "shape": [1, 1], "values": [[8]]},
                "attention_mask": {
                    "dtype": "torch.int64",
                    "shape": [1, 1],
                    "values": [[1]],
                },
            },
        }
        for change in ("request", "shape", "boolean", "mask", "missing", "duplicate"):
            altered = json.loads(provider._canonical(document))
            if change == "request":
                altered["request_sha256"] = "0" * 64
            elif change == "shape":
                altered["tensors"]["input_ids"]["shape"] = [1, 2]
            elif change == "boolean":
                altered["tensors"]["input_ids"]["values"] = [[True]]
            elif change == "mask":
                altered["tensors"]["attention_mask"]["values"] = [[2]]
            raw = provider._canonical(altered)
            log = b"MEM12_MODEL_INPUT " + raw + b"\n"
            if change == "missing":
                log = b"no model input\n"
            elif change == "duplicate":
                log *= 2
            result = {"model_input": provider._pin(raw), "prompt_tokens": 1}
            with self.subTest(change=change), self.assertRaises(ValueError):
                read_model_input(log, provider._pin(self.request), result)

    def test_supervisor_preserves_only_explicit_descriptor(self):
        read, write = os.pipe()
        os.write(write, b"fixture-allowed-fd")
        os.close(write)
        try:
            result = provider.execute_logged(
                [
                    "/usr/bin/python3",
                    "-I",
                    "-S",
                    "-c",
                    "import os; print(os.read(" + str(read) + ",128).decode())",
                ],
                self.root / "fd.log",
                pass_fds=(read,),
                timeout_seconds=5,
            )
        finally:
            os.close(read)
        self.assertEqual(result["returncode"], 0)
        self.assertEqual((self.root / "fd.log").read_bytes(), b"fixture-allowed-fd\n")


if __name__ == "__main__":
    unittest.main()
