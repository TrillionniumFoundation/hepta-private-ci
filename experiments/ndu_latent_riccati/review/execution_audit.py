"""Independent development-only audit of training pairing and inference privacy."""

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest import mock

import torch


SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
import train
from data import make_worlds, public_inputs
from evaluate import inference, spec


def source_hashes():
    return {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest()
            for name in ("train.py", "evaluate.py", "codec.py", "control.py", "data.py",
                         "run_experiment.py", "protocol.json")}


def provenance_checks(directory):
    import run_experiment as runner

    checks = {}
    # A stale single flag must never be sufficient to label local work as cloud.
    with mock.patch.dict(os.environ, {"HEPTA_DEDICATED_RUNNER_VERIFIED": "1"}, clear=True):
        with mock.patch.object(sys, "argv", ["run_experiment.py", "--output", str(directory / "fake-cloud"),
                                              "--execution-tier", "dedicated-cloud", "--smoke"]):
            with mock.patch.object(torch, "set_num_threads", side_effect=AssertionError("Reached execution setup")):
                try:
                    runner.main()
                except RuntimeError as exc:
                    checks["stale_cloud_flag_rejected_before_execution"] = "Dedicated cloud identity" in str(exc)
                else:
                    checks["stale_cloud_flag_rejected_before_execution"] = False
    run = directory / "guard-fixture"
    seed_path = run / "seeds" / "919"
    seed_path.mkdir(parents=True)
    checkpoint = seed_path / "checkpoint.pt"
    checkpoint.write_bytes(b"original-development-fixture")
    lock = {"source_manifest": runner.sources(),
            "seeds": {"919": {"checkpoint.pt": runner.digest(checkpoint)}}}
    (run / "selection-lock.json").write_text(json.dumps(lock))
    checkpoint.write_bytes(b"changed-development-fixture")
    try:
        runner.heldout(run, {"development_only": True, "seeds": [919]})
    except RuntimeError as exc:
        checks["changed_checkpoint_rejected_before_heldout"] = (
            "changed after lock" in str(exc) and not (run / "heldout-start.json").exists())
    else:
        checks["changed_checkpoint_rejected_before_heldout"] = False
    with mock.patch.object(runner, "sources", return_value={"unregistered.py": "changed"}):
        try:
            runner.heldout(run, {"development_only": True, "seeds": [919]})
        except RuntimeError as exc:
            checks["changed_source_rejected_before_heldout"] = (
                "Source changed after validation" in str(exc) and not (run / "heldout-start.json").exists())
        else:
            checks["changed_source_rejected_before_heldout"] = False
    return checks


def audit():
    hashes = source_hashes()
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    config = json.loads((SOURCE / "protocol.json").read_text())
    config.update({"decoder_updates": 2, "foundation_updates": 2,
                   "continued_updates": 2, "batch_size": 8,
                   "training_rollout_steps": 2, "riccati_lookahead_steps": 2})
    config["free_controller_compute_match"].update({"minimum_updates": 2, "maximum_updates": 2})
    # Deliberately outside registered train/validation/heldout seed namespaces.
    worlds = make_worlds(24, 9900919)
    fm_records, rollout_records = [], []
    original_fm, original_rollout = train.flow_loss, train.rollout

    def fm_spy(flow, context, facts, style, generator, initial_facts):
        fm_records.append(tuple(value.detach().clone() for value in
                                (context, facts, style, generator.get_state(), initial_facts)))
        return original_fm(flow, context, facts, style, generator, initial_facts)

    def rollout_spy(*args, **kwargs):
        rollout_records.append((kwargs["arm"], args[3].clone()))
        return original_rollout(*args, **kwargs)

    checks = {}
    with tempfile.TemporaryDirectory(prefix="ndu-execution-audit-") as directory:
        first = Path(directory) / "first"
        first.mkdir()
        train.flow_loss, train.rollout = fm_spy, rollout_spy
        try:
            decoder, models, _ = train.train_seed(worlds, 919, config, first)
        finally:
            train.flow_loss, train.rollout = original_fm, original_rollout
        saved = torch.load(first / "checkpoint.pt", weights_only=True)
        checks["same_encoder_as_foundation_all_variants"] = all(
            torch.equal(value, saved["foundation"]["encoder"][key])
            for model in models.values() for key, value in model["encoder"].state_dict().items())
        checks["frozen_encoder_parameters_all_variants"] = all(
            not parameter.requires_grad for model in models.values()
            for parameter in model["encoder"].parameters())
        checks["paired_minibatches_contexts_facts_styles_fm_rng"] = (
            len(fm_records) == 8 and all(
                all(torch.equal(left, right) for left, right in
                    zip(fm_records[2 + index], fm_records[start + index]))
                for index in range(2) for start in (4, 6)))
        checks["paired_ndu_free_rollout_noise"] = (
            len(rollout_records) == 4
            and [item[0] for item in rollout_records] == ["ndu", "ndu", "free_joint", "free_joint"]
            and all(torch.equal(rollout_records[i][1], rollout_records[2 + i][1]) for i in range(2)))
        second = Path(directory) / "second"
        second.mkdir()
        _, repeated_models, _ = train.train_seed(worlds, 919, config, second)
        checks["equal_update_training_bitwise_deterministic"] = all(
            torch.equal(value, repeated_models[name][part].state_dict()[key])
            for name, model in models.items() for part, module in model.items()
            if module is not None for key, value in module.state_dict().items())
        loaded_decoder, loaded_models = train.load_checkpoint(first / "checkpoint.pt")
        noise = torch.randn((24 * config["draws_per_world"], 7),
                            generator=torch.Generator().manual_seed(1234))
        choice = spec("ndu_trained", "ndu", 2)
        original, state, _ = inference(decoder, models["ndu_trained"],
                                       public_inputs(worlds), noise, choice, config)
        replay, replay_state, _ = inference(loaded_decoder, loaded_models["ndu_trained"],
                                            public_inputs(worlds), noise, choice, config)
        checks["saved_checkpoint_inference_bitwise_replay"] = (
            all(torch.equal(value, replay[key]) for key, value in original.items())
            and all(torch.equal(value, replay_state[key]) for key, value in state.items()))
        poisoned = copy.deepcopy(worlds)
        poisoned["facts"].fill_(888)
        poisoned["style"].fill_(999)
        for value in poisoned["targets"].values():
            value.fill_(777)
        changed, changed_state, _ = inference(loaded_decoder, loaded_models["ndu_trained"],
                                               public_inputs(poisoned), noise, choice, config)
        checks["hidden_truth_style_targets_do_not_change_output"] = (
            all(torch.equal(value, changed[key]) for key, value in replay.items())
            and all(torch.equal(value, changed_state[key]) for key, value in replay_state.items()))
        checks.update(provenance_checks(Path(directory)))
    checks["reviewed_source_unchanged_during_audit"] = hashes == source_hashes()
    return {"schema": "ndu-continuous-latent-execution-audit-v1",
            "observed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "torch_version": torch.__version__, "source_sha256": hashes,
            "fixture": {"world_seed": 9900919, "training_seed": 919,
                        "worlds": 24, "updates_per_stage": 2},
            "checks": checks, "all_checks_pass": all(checks.values()),
            "scope": "Development fixture; no heldout efficacy or cloud execution evidence",
            "runtime_adaptive_update_count_determinism_claimed": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["all_checks_pass"] else 1)
