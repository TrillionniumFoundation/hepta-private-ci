"""Adversarial V9 lineage and phase-boundary checks without a neural fit."""
from contextlib import contextmanager, ExitStack
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch

from bridge_reader import build_reader
from grounding_campaign import train
import grounding_campaign_utils as utils
from grounding_reader import ARMS, grounding_identity, load_grounding_warmup


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def prepared_fixture(root):
    """Small but complete twelve-start filesystem; content digests remain real."""
    output, previous = root / "run", root / "v8"
    args = SimpleNamespace(output=output, previous_v8=previous)
    write(previous / "design.json", dict(prior="frozen"))
    write(previous / "training-completion.json", dict(completed=True))
    write(output / "auxiliary-targets.json", dict(bound_training_targets=True))
    runtime = {"frozen_runtime.py": "a" * 64}
    parts = dict(reader_train=tuple(SimpleNamespace(case_id="case-" + str(i)) for i in range(2)))
    panels = {}
    for seed in utils.SEEDS:
        for arm in ARMS:
            path = output / f"seed-{seed}" / arm / "initial-binding-train.json"
            write(path, dict(case_ids=[case.case_id for case in parts["reader_train"]],
                probabilities=[.2, .8], model_execution_parameter_sha256=f"initial-{seed}"))
            panels[str(path.relative_to(output))] = digest(path)
    design = dict(runtime_source_sha256=runtime, protocol_sha256="protocol",
        previous_v8_design_sha256=digest(previous / "design.json"),
        previous_v8_completion_sha256=digest(previous / "training-completion.json"),
        reused_cache_files_sha256={"metadata.json": "cache"},
        prepared_files_sha256={"auxiliary-targets.json": digest(output / "auxiliary-targets.json")})
    write(output / "design.json", design)
    write(output / "preparation-completion.json", dict(design_sha256=digest(output / "design.json"),
        exact_initial_probability_equality={str(seed): True for seed in utils.SEEDS}, initial_panels_sha256=panels))

    def file_digest(path):
        return "protocol" if Path(path).name == "GROUNDING_V9_PROTOCOL.md" else digest(Path(path))

    def initial(folder):
        seed = int(folder.parent.name.split("-")[1])
        return SimpleNamespace(test_digest=f"initial-{seed}"), dict(execution_parameter_sha256=f"initial-{seed}")

    with ExitStack() as stack:
        stack.enter_context(patch.object(utils, "old_inputs", return_value=(
            dict(extended_cache_files_sha256={"metadata.json": "cache"}), parts, {}, ())))
        stack.enter_context(patch.object(utils, "source_inventory", return_value=runtime))
        stack.enter_context(patch.object(utils, "file_digest", side_effect=file_digest))
        stack.enter_context(patch.object(utils, "load_initialization", side_effect=initial))
        stack.enter_context(patch.object(utils, "typed_digest", side_effect=lambda model: model.test_digest))
        # Prove the complete fixture passes before each adversarial modification.
        utils.checked_design(args)
        yield args, design, parts


class GroundingCampaignTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)

    def assert_training_refused(self, args, message):
        with patch("grounding_campaign.load_bank") as bank, \
                patch("grounding_campaign.continue_grounding") as fit, \
                patch("torch.optim.Adam") as optimizer:
            with self.assertRaisesRegex(ValueError, message):
                train(args)
            bank.assert_not_called()
            fit.assert_not_called()
            optimizer.assert_not_called()
        self.assertFalse((args.output / "training-start.json").exists())

    def test_changed_runtime_is_refused_before_training_marker_or_optimizer(self):
        with tempfile.TemporaryDirectory() as directory, prepared_fixture(Path(directory)) as (args, _, _):
            with patch.object(utils, "source_inventory", return_value={"frozen_runtime.py": "b" * 64}):
                self.assert_training_refused(args, "source, protocol, lineage")

    def test_changed_prepared_targets_are_refused_before_training_marker_or_optimizer(self):
        with tempfile.TemporaryDirectory() as directory, prepared_fixture(Path(directory)) as (args, _, _):
            write(args.output / "auxiliary-targets.json", dict(bound_training_targets=False))
            self.assert_training_refused(args, "prepared cases, auxiliary targets")

    def test_false_initial_probability_attestation_cannot_open_training(self):
        with tempfile.TemporaryDirectory() as directory, prepared_fixture(Path(directory)) as (args, _, _):
            path = args.output / "preparation-completion.json"
            record = json.loads(path.read_text())
            record["exact_initial_probability_equality"]["41"] = False
            write(path, record)
            self.assert_training_refused(args, "initial probability evidence")

    def test_semantically_different_initial_probabilities_fail_even_after_rehash(self):
        with tempfile.TemporaryDirectory() as directory, prepared_fixture(Path(directory)) as (args, _, _):
            name = f"seed-41/{ARMS[1]}/initial-binding-train.json"
            path = args.output / name
            panel = json.loads(path.read_text())
            panel["probabilities"][0] = .3
            write(path, panel)
            complete = args.output / "preparation-completion.json"
            record = json.loads(complete.read_text())
            record["initial_panels_sha256"][name] = digest(path)
            write(complete, record)
            self.assert_training_refused(args, "initial predictions, complete tensors or rows differ")

    def test_initial_tensor_mismatch_cannot_hide_behind_matching_panel_identity(self):
        with tempfile.TemporaryDirectory() as directory, prepared_fixture(Path(directory)) as (args, _, _):
            name = f"seed-41/{ARMS[1]}/initial-binding-train.json"
            path = args.output / name
            panel = json.loads(path.read_text())
            panel["model_execution_parameter_sha256"] = "changed-model"
            write(path, panel)
            complete = args.output / "preparation-completion.json"
            record = json.loads(complete.read_text())
            record["initial_panels_sha256"][name] = digest(path)
            write(complete, record)

            def initial(folder):
                seed = int(folder.parent.name.split("-")[1])
                value = "changed-model" if str(folder.relative_to(args.output)) == f"seed-41/{ARMS[1]}" else f"initial-{seed}"
                return SimpleNamespace(test_digest=value), dict(execution_parameter_sha256=value)
            with patch.object(utils, "load_initialization", side_effect=initial):
                self.assert_training_refused(args, "initial predictions, complete tensors or rows differ")

    def test_missing_initial_panel_cannot_open_training(self):
        with tempfile.TemporaryDirectory() as directory, prepared_fixture(Path(directory)) as (args, _, _):
            path = args.output / "preparation-completion.json"
            record = json.loads(path.read_text())
            record["initial_panels_sha256"].pop(next(iter(record["initial_panels_sha256"])))
            write(path, record)
            self.assert_training_refused(args, "initial probability evidence")

    def test_repeated_training_is_rejected_before_encoder_loading(self):
        with tempfile.TemporaryDirectory() as directory, prepared_fixture(Path(directory)) as (args, _, _):
            write(args.output / "training-start.json", dict(existing_attempt=True))
            with patch("grounding_campaign.load_bank") as bank, patch("grounding_campaign.continue_grounding") as fit:
                with self.assertRaises(FileExistsError):
                    train(args)
                bank.assert_not_called()
                fit.assert_not_called()

    def test_incomplete_twelve_model_freeze_blocks_fresh_encoder_loading(self):
        from grounding_evaluation import evaluate
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = SimpleNamespace(output=root)
            design = dict(runtime_source_sha256={"runtime": "a" * 64})
            manifests = {f"seed-{seed}/{arm}/final-model.json": "x" for seed in utils.SEEDS for arm in ARMS}
            manifests.pop(next(iter(manifests)))
            write(root / "all-models-frozen.json", dict(manifests=manifests, runtime_source_sha256=design["runtime_source_sha256"]))
            write(root / "training-completion.json", dict(actual_optimizer_updates=18000, actual_training_exposures=288000))
            with patch("grounding_evaluation.checked_design", return_value=(design, {}, {}, ())), \
                    patch("grounding_evaluation.load_bank") as bank, patch.object(utils, "load_model") as model:
                with self.assertRaisesRegex(ValueError, "all twelve fixed V9 models"):
                    evaluate(args)
                bank.assert_not_called()
                model.assert_not_called()
            self.assertFalse((root / "evaluation-start.json").exists())

    def test_frozen_manifest_tampering_is_rejected_before_checkpoint_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = SimpleNamespace(output=root)
            design = dict(runtime_source_sha256={"runtime": "a" * 64})
            manifests = {}
            for seed in utils.SEEDS:
                for arm in ARMS:
                    name = f"seed-{seed}/{arm}/final-model.json"
                    write(root / name, dict(seed=seed, arm=arm))
                    manifests[name] = digest(root / name)
            write(root / "all-models-frozen.json", dict(manifests=manifests, runtime_source_sha256=design["runtime_source_sha256"]))
            write(root / "training-completion.json", dict(actual_optimizer_updates=18000, actual_training_exposures=288000))
            with patch.object(utils, "load_model") as model:
                utils.frozen_selections(args, design)
                self.assertEqual(model.call_count, 12)
                model.reset_mock()
                first_saved_name = next(iter(json.loads((root / "all-models-frozen.json").read_text())["manifests"]))
                write(root / first_saved_name, dict(changed_selection=True))
                with self.assertRaisesRegex(ValueError, "frozen model selection changed"):
                    utils.frozen_selections(args, design)
                model.assert_not_called()

    def test_real_checkpoint_roundtrip_preserves_new_architecture_and_old_core(self):
        core = build_reader("bridge", 41).eval().requires_grad_(False)
        core.training_source_groups = ("fixture-source",)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for arm in ARMS:
                model = load_grounding_warmup(core, arm, seed=41)
                folder = root / arm
                initial = utils.save_initialization(folder, model, core, 41)
                restored, _ = utils.load_initialization(folder)
                self.assertEqual(grounding_identity(restored), grounding_identity(model))
                utils.save_model(folder, model, dict(fixture=True), seed=41,
                                 initial_digest=initial["execution_parameter_sha256"])
                final, _ = utils.load_model(folder)
                self.assertEqual(grounding_identity(final), grounding_identity(model))
                for name, value in core.state_dict().items():
                    self.assertEqual(final.state_dict()[name].numpy().tobytes(), value.numpy().tobytes())
            changed = load_grounding_warmup(core, ARMS[0], seed=41)
            with torch.no_grad():
                changed.project.weight[0, 0] += .01
            with self.assertRaisesRegex(ValueError, "warmup tensor must be copied"):
                utils.save_initialization(root / "changed-common", changed, core, 41)
            self.assertFalse((root / "changed-common").exists())


if __name__ == "__main__":
    unittest.main()
