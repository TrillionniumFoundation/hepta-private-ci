"""Mocked physical.run control-flow regressions, NOT real-model evidence.

Only the external torch/Laya modules and source/data acquisition are mocked.
The actual registry validation, checkpoint hashing, isolation loader, forward orchestration,
hook cleanup and per-row scorer run against tiny disposable fixture files.
"""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import replacement_physical as physical
from test_replacement_laya_view import fixture


class PhysicalRunCustodyTests(unittest.TestCase):
    def exercise(self, *, stage=None, changed=None, error=None, count_hook=True,
                 invalid_probability=False, cleanup_error=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        snapshot = fixture(root)
        config = snapshot / "tokenizer" / "tokenizer_config.json"
        config.write_text(json.dumps({"tokenizer_class": "PreTrainedTokenizerFast"}))
        (snapshot / "tokenizer" / "added_tokens.json").write_text("{}")
        original = {path.relative_to(snapshot).as_posix(): path.read_bytes()
                    for path in snapshot.rglob("*") if path.is_file()}
        weight = hashlib.sha256(original["model.safetensors"]).hexdigest()
        registry = dict(schema="hepta.neuron.replacement-pins.v1", mode="SHADOW_ONLY",
                        authority="DENY_ALL", production_activation_allowed=False,
                        models={name: dict(repository="fixture/not-real-model", revision="a" * 40,
                            weight_file="model.safetensors", weight_sha256=weight,
                            role="full_policy" if name.startswith("laya_") else "encoder_plus_new_head",
                            license="mit", parameter_class="fixture") for name in physical.EXPECTED})
        rows = {split: [dict(source_id=f"{split}-{i}", source_group_id=f"group-{split}-{i}",
                            source_row_sha256="b" * 64, timestamp_ms=i,
                            text=f"fixture {i}", label=i % 4) for i in range(8)]
                for split in physical.SPLITS}
        witness = SimpleNamespace(snapshot=snapshot, original=original, private=[],
                                  removed=0, forwards=0, hooks=0)

        def event(where):
            if where == "cleanup" and cleanup_error is not None:
                raise cleanup_error
            if stage == where:
                if changed is not None:
                    (snapshot / changed).write_bytes(b'{"changed":true}')
                if error is not None:
                    raise error

        class Handle:
            def remove(self):
                witness.removed += 1
                event("cleanup")

        class Model:
            def register_forward_hook(self, callback):
                event("register")
                self.callback = callback
                witness.hooks += 1
                return Handle()

            def parameters(self):
                event("parameters")
                return [SimpleNamespace(numel=lambda: 1)]

        class Agent:
            def __init__(self, path, device):
                witness.private.append(Path(path))
                event("constructor")
                self.device = SimpleNamespace(type=device)
                self.model = Model()

            def system_one(self, text, question):
                # The actual loader must delete its private view before forward.
                if witness.private[-1].exists():
                    raise AssertionError("private view survived into forward")
                witness.forwards += 1
                if count_hook:
                    self.model.callback()
                event("forward")
                probs = dict.fromkeys(physical.CATEGORIES, .25)
                if invalid_probability:
                    probs[physical.CATEGORIES[0]] = float("nan")
                return {"answers": {"category": {"probabilities": probs}}}

        torch = ModuleType("torch")
        torch.__version__ = "MOCK-NOT-A-MODEL-RUNTIME"
        torch.set_num_threads = lambda count: None
        torch.nn = ModuleType("torch.nn")
        torch.nn.functional = ModuleType("torch.nn.functional")
        laya = ModuleType("laya")
        laya.agent = ModuleType("laya.agent")
        laya.agent.Agent = Agent
        modules = {"torch": torch, "torch.nn": torch.nn,
                   "torch.nn.functional": torch.nn.functional,
                   "laya": laya, "laya.agent": laya.agent}

        def call():
            with ExitStack() as stack:
                stack.enter_context(patch.dict(sys.modules, modules))
                stack.enter_context(patch.object(sys, "path", list(sys.path)))
                stack.enter_context(patch.object(physical, "verify_laya_source"))
                stack.enter_context(patch.object(physical, "load_cohorts",
                    return_value=({"source_archive_sha256": "c" * 64}, rows)))
                return physical.run("laya_english_421m", registry, snapshot,
                                    root / "cohorts", root / "archive", root / "source", 8)

        return call, witness

    def assert_private_deleted(self, witness):
        self.assertEqual(len(witness.private), 1)
        self.assertFalse(witness.private[0].exists())

    def test_constructor_mutation_and_error_are_both_observable(self):
        error = RuntimeError("constructor failed")
        call, witness = self.exercise(stage="constructor", changed="encoder/config.json", error=error)
        with self.assertRaisesRegex(ValueError, "original") as caught:
            call()
        # Both the standalone loader guard and the physical guard observe drift.
        inner = caught.exception.__cause__
        self.assertIsInstance(inner, ValueError)
        self.assertIs(inner.__cause__, error)
        self.assert_private_deleted(witness)
        self.assertEqual(witness.forwards, 0)

    def test_forward_exception_cannot_skip_any_tokenizer_asset(self):
        for asset in ("tokenizer/tokenizer_config.json", "tokenizer/added_tokens.json",
                      "tokenizer/tokenizer.json", "model.safetensors",
                      "rl_agent_config.json", "encoder/config.json"):
            with self.subTest(asset=asset):
                error = RuntimeError("forward failed")
                call, witness = self.exercise(stage="forward", changed=asset, error=error)
                with self.assertRaisesRegex(ValueError, "original") as caught:
                    call()
                self.assertIs(caught.exception.__cause__, error)
                self.assertEqual(witness.removed, 1)
                self.assert_private_deleted(witness)
                # Detection is not prevention or rollback: the fixture remains changed.
                self.assertNotEqual((witness.snapshot / asset).read_bytes(), witness.original[asset])

    def test_successful_forward_cannot_hide_noncore_tokenizer_drift(self):
        call, witness = self.exercise(stage="forward", changed="tokenizer/added_tokens.json")
        with self.assertRaisesRegex(ValueError, "original"):
            call()
        self.assertEqual(witness.forwards, 40)
        self.assertEqual(witness.removed, 1)

    def test_clean_errors_keep_the_original_exception_object(self):
        for stage in ("constructor", "register", "forward", "cleanup", "parameters"):
            with self.subTest(stage=stage):
                error = RuntimeError(stage)
                call, witness = self.exercise(stage=stage, error=error)
                with self.assertRaises(RuntimeError) as caught:
                    call()
                self.assertIs(caught.exception, error)
                self.assert_private_deleted(witness)

    def test_cleanup_error_cannot_mask_original_custody_loss(self):
        error = RuntimeError("cleanup failed")
        call, witness = self.exercise(stage="cleanup", changed="tokenizer/added_tokens.json", error=error)
        with self.assertRaisesRegex(ValueError, "original") as caught:
            call()
        self.assertIs(caught.exception.__cause__, error)
        self.assertEqual(witness.removed, 1)

    def test_registration_and_parameter_read_errors_are_inside_custody_guard(self):
        for stage in ("register", "parameters"):
            with self.subTest(stage=stage):
                error = RuntimeError(stage)
                call, _ = self.exercise(stage=stage, changed="tokenizer/added_tokens.json", error=error)
                with self.assertRaisesRegex(ValueError, "original") as caught:
                    call()
                self.assertIs(caught.exception.__cause__, error)

    def test_forward_and_cleanup_failures_remain_in_the_exception_chain(self):
        forward_error = RuntimeError("forward failed")
        cleanup_error = RuntimeError("cleanup failed too")
        call, witness = self.exercise(stage="forward", changed="tokenizer/added_tokens.json",
                                      error=forward_error, cleanup_error=cleanup_error)
        with self.assertRaisesRegex(ValueError, "original") as caught:
            call()
        self.assertIs(caught.exception.__cause__, cleanup_error)
        self.assertIs(cleanup_error.__context__, forward_error)
        # This proves cleanup was attempted, not that the failing removal succeeded.
        self.assertEqual(witness.removed, 1)

    def test_forward_count_failure_still_checks_custody(self):
        call, witness = self.exercise(stage="forward", changed="tokenizer/added_tokens.json", count_hook=False)
        with self.assertRaisesRegex(ValueError, "original") as caught:
            call()
        self.assertRegex(str(caught.exception.__cause__), "exactly one")
        self.assertEqual(witness.removed, 1)

    def test_invalid_distribution_still_checks_custody(self):
        call, witness = self.exercise(stage="forward", changed="tokenizer/added_tokens.json", invalid_probability=True)
        with self.assertRaisesRegex(ValueError, "original") as caught:
            call()
        self.assertRegex(str(caught.exception.__cause__), "distribution")
        self.assertEqual(witness.removed, 1)

    def test_interrupts_are_checked_and_clean_interrupt_identity_is_preserved(self):
        for cls in (KeyboardInterrupt, SystemExit):
            for changed in (None, "tokenizer/added_tokens.json"):
                with self.subTest(cls=cls.__name__, changed=changed):
                    error = cls("interrupted")
                    call, witness = self.exercise(stage="forward", changed=changed, error=error)
                    with self.assertRaises(BaseException) as caught:
                        call()
                    self.assertIsInstance(caught.exception, ValueError if changed else cls)
                    self.assertIs(caught.exception.__cause__ if changed else caught.exception, error)
                    self.assertEqual(witness.removed, 1)

    def test_success_retains_shadow_only_output_and_original_fixture_bytes(self):
        call, witness = self.exercise()
        result = call()
        self.assertEqual((result["mode"], result["authority"], result["production_activation_allowed"]),
                         ("SHADOW_ONLY", "DENY_ALL", False))
        self.assertEqual((result["observed_forward_calls"], witness.removed), (40, 1))
        self.assertEqual({p.relative_to(witness.snapshot).as_posix(): p.read_bytes()
                          for p in witness.snapshot.rglob("*") if p.is_file()}, witness.original)
        self.assert_private_deleted(witness)


if __name__ == "__main__":
    unittest.main()
