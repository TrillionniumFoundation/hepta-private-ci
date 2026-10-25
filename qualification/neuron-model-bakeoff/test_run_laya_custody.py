"""Actual CLI-entry custody regressions with mocked SDKs, not model evidence.

The real dataset/calibration readers, checksums, isolation loader, prediction
orchestration and JSONL writer run on tiny invented files. Laya, torch and psutil
are mocked; an optional fsync fault is injected after a real file write.
"""
from contextlib import ExitStack, redirect_stderr
import builtins
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import bakeoff
import run_laya
from test_laya_isolation import fixture


class RunLayaCustodyTests(unittest.TestCase):
    def exercise(self, *, stage=None, changed=None, error=None, device="cpu",
                 decoy=False, fallback=None, invalid_probs=False):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        snapshot = fixture(root)
        (snapshot / "tokenizer" / "tokenizer_config.json").write_text(
            '{"tokenizer_class":"PreTrainedTokenizerFast"}')
        (snapshot / "tokenizer" / "added_tokens.json").write_text("{}")
        weights = snapshot / "model.safetensors"
        if decoy:
            weights = snapshot / "decoy.weights"
            weights.write_bytes(b"not-the-loaded-model")
        digest = hashlib.sha256(weights.read_bytes()).hexdigest()
        original = {str(p.relative_to(snapshot)): p.read_bytes()
                    for p in snapshot.rglob("*") if p.is_file()}
        rows = [dict(case_id=f"{split}-{i}", group_id=f"group-{split}-{i}", split=split,
                     label="a", labels=["a", "b"], language="en", task_family="fixture",
                     ood=False, state=f"input-{i}", question="Choose a fixture label")
                for split in bakeoff.SPLITS for i in range(2)]
        dataset = root / "dataset.jsonl"
        dataset.write_text("".join(json.dumps(row) + "\n" for row in rows))
        calibration = root / "calibration.json"
        calibration.write_text(json.dumps({
            "schema": "hepta.neuron-bakeoff.laya-calibration.v1",
            "weights_sha256": digest, "temperature": 1., "threshold": .7,
            "calibration_split_sha256": bakeoff.sha_bytes(bakeoff.canonical(
                [r for r in rows if r["split"] == "calibration"]))}))
        witness = SimpleNamespace(snapshot=snapshot, original=original, private=[],
                                  forwards=0, output=root / "output.jsonl", cfg={},
                                  stderr=io.StringIO(), gpu_calls=[], digest=digest)

        def event(where):
            if where == stage:
                if changed is not None:
                    (snapshot / changed).write_bytes(b'{"changed":true}')
                if error is not None:
                    raise error

        class Agent:
            def __init__(self, path, device):
                witness.private.append(Path(path))
                event("constructor")
                self.device = SimpleNamespace(type="wrong" if fallback == "load" else device)
                self.cfg = witness.cfg

            def predict(self, state, question):
                if witness.private[-1].exists():
                    raise AssertionError("private tokenizer view must be gone before predict")
                witness.forwards += 1
                event("forward")
                if fallback == "forward":
                    self.device.type = "wrong"
                probabilities = {"a": float("nan") if invalid_probs else .8, "b": .2}
                return {"answers": {"decision": {"probabilities": probabilities}}}

        class Process:
            def __init__(self, pid):
                event("process")

            def memory_info(self):
                event("rss")
                return SimpleNamespace(rss=12345)

        def synchronize():
            witness.gpu_calls.append("sync")
            event("synchronize")

        laya, torch, psutil = (ModuleType(name) for name in ("laya", "torch", "psutil"))
        laya.load = Agent
        psutil.Process = Process
        torch.cuda = SimpleNamespace(synchronize=synchronize,
            reset_peak_memory_stats=lambda: witness.gpu_calls.append("reset"),
            max_memory_allocated=lambda: 42)
        argv = ["run_laya.py", "--dataset", str(dataset), "--checkpoint-dir", str(snapshot),
                "--weights-file", str(weights), "--weights-sha256", digest,
                "--calibration-file", str(calibration), "--host-id", "mock-host",
                "--device", device, "--confidence-min", ".7", "--max-len", "128",
                "--head-max-len", "64", "--output", str(witness.output)]
        real_fsync = run_laya.os.fsync
        real_import = builtins.__import__

        def fsync(fd):
            event("fsync")
            real_fsync(fd)

        def import_module(name, *args, **kwargs):
            if name == "laya":
                event("import")
            return real_import(name, *args, **kwargs)

        def call():
            with ExitStack() as stack:
                stack.enter_context(patch.dict(sys.modules, {"laya": laya, "torch": torch,
                                                             "psutil": psutil}))
                stack.enter_context(patch.object(sys, "argv", argv))
                stack.enter_context(patch.dict(run_laya.os.environ, {}))
                stack.enter_context(redirect_stderr(witness.stderr))
                if stage == "fsync":
                    stack.enter_context(patch.object(run_laya.os, "fsync", side_effect=fsync))
                if stage == "import":
                    stack.enter_context(patch.object(builtins, "__import__", side_effect=import_module))
                return run_laya.main()

        return call, witness

    def assert_custody_blocked(self, call, witness):
        try:
            result = call()
        except BaseException as exc:
            self.fail(f"custody failure escaped the BLOCKED CLI path: {type(exc).__name__}: {exc}")
        self.assertEqual(result, 2)
        self.assertIn("original", witness.stderr.getvalue())
        self.assertEqual(len(witness.private), 1)
        self.assertFalse(witness.private[0].exists())

    def test_constructor_mutation_and_failure_report_custody_loss(self):
        call, witness = self.exercise(stage="constructor", changed="encoder/config.json",
                                      error=RuntimeError("constructor failed"))
        self.assert_custody_blocked(call, witness)
        self.assertEqual(witness.forwards, 0)
        self.assertFalse(witness.output.exists())

    def test_forward_failure_cannot_skip_original_inventory(self):
        for asset in ("tokenizer/tokenizer_config.json", "tokenizer/added_tokens.json",
                      "tokenizer/tokenizer.json", "encoder/config.json",
                      "rl_agent_config.json", "model.safetensors"):
            with self.subTest(asset=asset):
                call, witness = self.exercise(stage="forward", changed=asset,
                                              error=RuntimeError("forward failed"))
                self.assert_custody_blocked(call, witness)
                self.assertNotEqual((witness.snapshot / asset).read_bytes(), witness.original[asset])

    def test_successful_forward_drift_denies_success_even_with_output_rows(self):
        call, witness = self.exercise(stage="forward", changed="tokenizer/added_tokens.json")
        self.assert_custody_blocked(call, witness)
        # Existing CLI streams rows, not an atomic success artifact; failure does not erase them.
        self.assertEqual(len(witness.output.read_text().splitlines()), 4)

    def test_clean_runtime_failures_keep_existing_blocked_cli_behavior(self):
        for stage in ("constructor", "process", "forward", "rss", "fsync"):
            with self.subTest(stage=stage):
                call, witness = self.exercise(stage=stage, error=RuntimeError(f"{stage} failed"))
                self.assertEqual(call(), 2)
                self.assertEqual(witness.stderr.getvalue(), f"BLOCKED: {stage} failed\n")
                self.assertFalse(witness.private[0].exists())

    def test_output_failure_and_resource_inspection_still_check_custody(self):
        for stage in ("process", "rss", "fsync"):
            with self.subTest(stage=stage):
                call, witness = self.exercise(stage=stage, changed="tokenizer/added_tokens.json",
                                              error=OSError(f"{stage} failed"))
                self.assert_custody_blocked(call, witness)

    def test_invalid_probability_and_device_fallback_still_check_custody(self):
        for options in ({"invalid_probs": True}, {"fallback": "forward"}):
            with self.subTest(options=options):
                call, witness = self.exercise(stage="forward", changed="tokenizer/added_tokens.json",
                                              **options)
                self.assert_custody_blocked(call, witness)

    def test_clean_device_fallback_is_not_silently_admitted(self):
        for fallback in ("load", "forward"):
            with self.subTest(fallback=fallback):
                call, witness = self.exercise(fallback=fallback)
                self.assertEqual(call(), 2)
                self.assertIn("device", witness.stderr.getvalue())

    def test_cuda_sync_failure_still_checks_custody(self):
        call, witness = self.exercise(device="cuda", stage="synchronize",
                                      changed="tokenizer/added_tokens.json", error=RuntimeError("sync failed"))
        self.assert_custody_blocked(call, witness)

    def test_sdk_import_failure_still_checks_custody(self):
        call, witness = self.exercise(stage="import", changed="tokenizer/added_tokens.json",
                                      error=ImportError("SDK import failed"))
        self.assertEqual(call(), 2)
        self.assertIn("original", witness.stderr.getvalue())
        self.assertEqual(witness.private, [])
        self.assertEqual(witness.forwards, 0)
        self.assertFalse(witness.output.exists())

    def test_interrupt_identity_preserved_unless_custody_also_fails(self):
        for cls in (KeyboardInterrupt, SystemExit):
            for changed in (None, "tokenizer/added_tokens.json"):
                with self.subTest(cls=cls, changed=changed):
                    error = cls("interrupted")
                    call, witness = self.exercise(stage="forward", changed=changed, error=error)
                    if changed:
                        self.assert_custody_blocked(call, witness)
                    else:
                        with self.assertRaises(cls) as caught:
                            call()
                        self.assertIs(caught.exception, error)

    def test_selected_weight_identity_must_be_the_actual_loaded_weight(self):
        call, witness = self.exercise(decoy=True)
        self.assertEqual(call(), 2)
        self.assertIn("loaded Laya weight identity", witness.stderr.getvalue())
        self.assertEqual(witness.forwards, 0)
        self.assertFalse(witness.output.exists())

    def test_all_existing_devices_and_context_budgets_remain_supported(self):
        for device in ("cpu", "cuda", "mps", "xpu"):
            with self.subTest(device=device):
                call, witness = self.exercise(device=device)
                self.assertEqual(call(), 0)
                self.assertEqual(witness.stderr.getvalue(), "")
                self.assertEqual(witness.cfg, {"max_len": 128, "head_max_len": 64})
                output = [json.loads(line) for line in witness.output.read_text().splitlines()]
                self.assertEqual([r["case_id"] for r in output], ["test-0", "test-1", "future-0", "future-1"])
                self.assertTrue(all(r["device"] == device and r["model_weights_sha256"] == witness.digest
                                    for r in output))
                self.assertFalse(witness.private[0].exists())
                self.assertEqual({str(p.relative_to(witness.snapshot)): p.read_bytes()
                                  for p in witness.snapshot.rglob("*") if p.is_file()}, witness.original)


if __name__ == "__main__":
    unittest.main()
