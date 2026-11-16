"""CPU transport controls only: synthetic installed files, zero provider calls.

The subprocess boundary is replaced in every Adapter test. No credential,
installed release, account, kernel, task dataset or model is accessed.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import kaggle_provider as provider


class KaggleProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cpu-provider-control-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pins, records = {}, {}
        for label in provider.INSTALLED_SHA256:
            path = self.root / (label + ".fixture")
            raw = ("SYNTHETIC_NONEXECUTABLE_TRANSPORT_" + label).encode()
            path.write_bytes(raw)
            self.pins[label] = hashlib.sha256(raw).hexdigest()
            records[label] = dict(path=str(path), sha256=self.pins[label])
        self.config = dict(provider=dict(installed_sources=records,
            entrypoint=records["entrypoint"]["path"], account_selector="fixture_account",
            accelerator="cpu", timeout_seconds=3000, internet=False,
            is_private=True, mode="batch"))
        pin_patch = patch.object(provider, "INSTALLED_SHA256", self.pins)
        pin_patch.start(); self.addCleanup(pin_patch.stop)

    def completed(self, result, returncode=0, ok=True):
        return types.SimpleNamespace(returncode=returncode,
            stdout=provider.canonical(dict(ok=ok, result=result)), stderr=b"fixture-stderr\n")

    def records(self):
        return [json.loads(path.read_bytes()) for path in
                sorted((self.root / "native" / "adapter-calls").glob("*.json"))]

    def test_complete_installed_map_and_explicit_cpu_policy(self):
        provider.validate_installed(self.config["provider"])
        for key, value in (("accelerator", "NvidiaTeslaT4"), ("internet", True),
                           ("timeout_seconds", 2999), ("is_private", False),
                           ("account_selector", "other/implicit")):
            changed = copy.deepcopy(self.config["provider"]); changed[key] = value
            with self.subTest(key=key), self.assertRaises(provider.ProviderError):
                provider.validate_installed(changed)
        changed = copy.deepcopy(self.config["provider"])
        del changed["installed_sources"]["transport"]
        with self.assertRaises(provider.ProviderError):
            provider.validate_installed(changed)

    def test_exact_installed_bytes_not_self_reported_sha(self):
        adapter = provider.Adapter(self.config, self.root / "native")
        Path(self.config["provider"]["installed_sources"]["jobs"]["path"]).write_bytes(b"changed")
        with patch.object(provider.subprocess, "run") as execute:
            with self.assertRaises(provider.ProviderError):
                adapter.call("resume", ["--request-id", "fixture-one"])
            execute.assert_not_called()

    def test_initial_ack_is_not_mistaken_for_remote_effect_unknown(self):
        # Status shape observed in actual CPU feasibility ACK 0c6c1394...;
        # all object identities here are synthetic and cannot be submitted.
        ack = dict(schema="hepta-kaggle-job-v1", request_id="fixture-one",
            submission_state="ACCEPTED", remote_submission_state="ACKNOWLEDGED",
            remote_state="UNKNOWN", identity_verified=False, remote_effect_unknown=False)
        adapter = provider.Adapter(self.config, self.root / "native")
        with patch.object(provider.subprocess, "run", return_value=self.completed(ack)) as execute:
            self.assertEqual(adapter.call("submit", ["--request-id", "fixture-one"]), ack)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(execute.call_args.args[0][-3:], ["submit", "--request-id", "fixture-one"])
        record, = self.records()
        self.assertEqual(record["returncode"], 0)
        self.assertFalse(record["submission_is_replayed"])
        self.assertEqual(Path(record["stdout_path"]).read_bytes(), execute.return_value.stdout)

    def test_same_request_resume_is_observation_and_does_not_submit(self):
        observed = dict(request_id="fixture-one", identity_verified=True,
            remote_submission_replayed=False, remote_effect_unknown=False, remote_state="RUNNING")
        adapter = provider.Adapter(self.config, self.root / "native")
        with patch.object(provider.subprocess, "run", return_value=self.completed(observed)) as execute:
            self.assertEqual(adapter.call("resume", ["--request-id", "fixture-one"]), observed)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(execute.call_args.args[0], [self.config["provider"]["entrypoint"],
            "fixture_account", "batch", "resume", "--request-id", "fixture-one"])
        self.assertEqual(self.records()[0]["operation"], "resume")

    def test_submit_timeout_keeps_partial_output_and_never_replays(self):
        adapter = provider.Adapter(self.config, self.root / "native")
        error = subprocess.TimeoutExpired("synthetic", 1, output=b"partial-ack", stderr=b"partial-error")
        with patch.object(provider.subprocess, "run", side_effect=error) as execute:
            with self.assertRaisesRegex(provider.ProviderError, "never replay"):
                adapter.call("submit", ["--request-id", "fixture-one"], timeout=1)
        self.assertEqual(execute.call_count, 1)
        record, = self.records()
        self.assertTrue(record["remote_effect_unknown"])
        self.assertEqual(record["error_type"], "TimeoutExpired")
        self.assertEqual(record["partial_stdout_sha256"], hashlib.sha256(b"partial-ack").hexdigest())
        self.assertTrue(any((self.root / "native" / "adapter-calls").glob("*.partial-stdout.bin")))

    def test_error_exit_or_malformed_json_is_retained_not_success(self):
        for index, result in enumerate((self.completed({}, returncode=2, ok=False),
                types.SimpleNamespace(returncode=0, stdout=b'{"ok":true,"ok":false}', stderr=b""))):
            adapter = provider.Adapter(self.config, self.root / ("case-" + str(index)))
            with patch.object(provider.subprocess, "run", return_value=result) as execute:
                with self.assertRaises(provider.ProviderError):
                    adapter.call("submit", ["--request-id", "fixture-one"])
                self.assertEqual(execute.call_count, 1)
            records = list((self.root / ("case-" + str(index)) / "adapter-calls").glob("*.json"))
            self.assertEqual(len(records), 1)
            self.assertTrue(list(records[0].parent.glob("*.stdout.bin")))

    def test_unsupported_mutation_never_reaches_installed_command(self):
        adapter = provider.Adapter(self.config, self.root / "native")
        with patch.object(provider.subprocess, "run") as execute:
            for operation in ("delete", "cancel", "bind", "retry"):
                with self.subTest(operation=operation), self.assertRaises(provider.ProviderError):
                    adapter.call(operation, [])
            execute.assert_not_called()

    def test_source_reads_ignore_atime_but_reject_symlink_and_hardlink(self):
        path = Path(self.config["provider"]["installed_sources"]["jobs"]["path"])
        raw = path.read_bytes(); before = path.stat()
        os.utime(path, ns=(1, before.st_mtime_ns))
        self.assertEqual(provider.file_bytes(path), raw)
        link = self.root / "alias"; link.symlink_to(path)
        with self.assertRaises(provider.ProviderError): provider.file_bytes(link)
        os.link(path, self.root / "hardlink")
        with self.assertRaises(provider.ProviderError): provider.file_bytes(path)


if __name__ == "__main__":
    unittest.main()
