"""Frozen, phase-gated runtime bank, calibration, audit and confirmation CLI."""

import argparse
import json
from pathlib import Path
import platform
import sys
import time
import traceback

import numpy as np
import torch

from ..v6.neural import parameter_hash
from .assets import load_assets
from .feedback_bank import build_bank, load_bank
from .feedback_rollout import run_profile
from .learning import load_checkpoint
from .native_stream import NativeStreamBridge
from .runtime_controller import ALPHAS, REPRESENTATIONS, RFF_SEED, TRANSFORMS, fit_controllers
from .source_roles import load_corpus_roles
from .training_common import file_hash, object_hash, require, verify_freeze, write_json
from .training_run import HERE, previous_stage, require_bound, source_files as training_files


RUNTIME_FILES = ("feedback_media.py", "feedback_task.py", "feedback_bank.py", "feedback_rollout.py",
                 "native_stream.py", "native_stream.rs", "runtime_controller.py", "runtime_run.py",
                 "RUNTIME_IMPLEMENTATION.json")


def source_files():
    return {**training_files(), **{str((HERE / name).relative_to(HERE.parent)): file_hash(HERE / name)
                                  for name in RUNTIME_FILES}}


def profile_model(root, profile, seed, original, protocol, freeze):
    if profile == "frozen":
        return original
    qualification = root / "TRAINING_QUALIFICATION.json"
    require_bound(freeze, root, qualification)
    qualified = json.loads(qualification.read_text())
    require(qualified["passed"] and qualified["protocol_sha256"] == file_hash(HERE / "PROTOCOL.json"),
            "Training did not qualify this runtime model under the current protocol")
    parent = root / "final" / str(seed)
    require_bound(freeze, root, parent / "COMPLETE.json")
    previous_stage(parent)
    path = parent / profile / ("schedule-" + str(protocol["training"]["final_schedule_id"])) / "checkpoint.pt"
    require_bound(freeze, root, path)
    model, _, _ = load_checkpoint(path, original, seed, protocol)
    return model.eval().requires_grad_(False)


def read_fit(root, seed, profile, freeze):
    directory = root / "runtime" / "fit" / f"{seed}-{profile}"
    for name in ("COMPLETE.json", "READOUTS.json"):
        require_bound(freeze, root, directory / name)
    previous_stage(directory)
    data = json.loads((directory / "READOUTS.json").read_text())
    meta = data["fit_identities"]["metadata"]
    require(meta["seed"] == seed and meta["profile"] == profile, "Frozen runtime fit profile mismatch")
    require(meta["protocol_sha256"] == file_hash(HERE / "PROTOCOL.json"), "Frozen runtime fit protocol mismatch")
    return data


def policies_for(root, seed, profile, phase, fit, freeze, protocol):
    fixed = {"kind": "fixed", **fit["fixed_policy"]}
    if phase == "audit":
        return {"fixed": fixed, **{name: fit["models"][name] for name in REPRESENTATIONS}}
    permission = root / "CONFIRMATION_QUALIFICATION.json"
    require_bound(freeze, root, permission)
    record = json.loads(permission.read_text())
    require(record["passed"] and profile in record["allowed_profiles"], "Confirmation did not qualify this profile")
    require(record["protocol_sha256"] == file_hash(HERE / "PROTOCOL.json"), "Confirmation protocol mismatch")
    original_fit = read_fit(root, seed, "frozen", freeze)
    common_fixed = {"kind": "fixed", **original_fit["fixed_policy"]}
    by_profile = {
        "frozen": {"A": common_fixed, "D": fit["models"]["native"], "H": fit["models"]["history"],
                   "J": fit["models"]["current"], "K": fit["models"]["reset_native"]},
        "ordinary": {"B": common_fixed, "G": fit["models"]["native"]},
        "field": {"C": common_fixed, "E": fit["models"]["native"], "F": fit["models"]["history"],
                  "I": fit["models"]["reset_native"]},
    }
    return by_profile[profile]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("bank", "fit", "audit", "confirm"))
    parser.add_argument("--seed", type=int, required=True, choices=(17, 29, 43))
    parser.add_argument("--profile", choices=("frozen", "ordinary", "field"), required=True)
    parser.add_argument("--assets", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--freeze", required=True)
    parser.add_argument("--native", required=True)
    parser.add_argument("--role", choices=("primary", "retention"))
    args = parser.parse_args()
    root = Path(args.out).resolve()
    protocol_path = HERE / "PROTOCOL.json"
    protocol = json.loads(protocol_path.read_text())
    phase = "runtime-" + args.phase
    freeze = verify_freeze(args.freeze, protocol_path, phase, root)
    sources = source_files()
    require(all(freeze["source_files"].get(name) == digest for name, digest in sources.items()),
            "Runtime source freeze is incomplete")
    p = protocol["runtime"]
    require(p["ridges"] == list(ALPHAS) and p["transforms"] == [name for name, _ in TRANSFORMS]
            and p["representations"] == list(REPRESENTATIONS) and p["rff_seed"] == RFF_SEED,
            "Runtime candidate family differs from registration")
    require(p["charge_per_transition"] == .002 and p["initial_common_transition_charged"]
            and p["maximum_decisions"] == 3 and p["event_width"] == 16 and p["head_width"] == 88,
            "Feedback task contract differs")
    require(file_hash(HERE / "SOURCE_ALLOCATION.json") == protocol["source_allocation_sha256"],
            "Runtime source allocation changed")
    require(file_hash(args.native) == freeze["native_library_sha256"], "Native library differs from runtime freeze")
    require((args.phase == "confirm") == (args.role is not None), "Only confirmation selects primary/retention role")
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    destination = root / "runtime" / args.phase / f"{args.seed}-{args.profile}"
    if args.phase == "confirm":
        destination = destination / args.role
    destination.mkdir(parents=True, exist_ok=False)
    start = {"schema": "hepta.field-bridge.v3.runtime-phase-start.1", "phase": phase,
        "seed": args.seed, "profile": args.profile, "role": args.role,
        "registered_commit": freeze["registered_commit"], "source_files": sources,
        "freeze_sha256": file_hash(args.freeze), "protocol_sha256": file_hash(protocol_path),
        "native_library_sha256": file_hash(args.native), "started_monotonic_ns": time.monotonic_ns(),
        "environment": {"python": sys.version, "numpy": np.__version__, "torch": torch.__version__,
            "platform": platform.platform(), "torch_threads": 1, "torch_interop_threads": 1,
            "outer_data_batch_size": 32, "generator_and_observer_arithmetic_batch_size": 1}}
    write_json(destination / "START.json", start)
    try:
        with NativeStreamBridge(args.native, freeze["native_library_sha256"]) as bridge:
            metadata = {"seed": args.seed, "profile": args.profile,
                "protocol_sha256": file_hash(protocol_path), "registered_commit": freeze["registered_commit"],
                "source_manifest_sha256": protocol["source_manifest_sha256"]}
            if args.phase == "fit":
                bank_root = root / "runtime" / "bank" / f"{args.seed}-{args.profile}"
                for name in ("runtime_fit", "runtime_select"):
                    require_bound(freeze, root, bank_root / name / "COMPLETE.json")
                train, selection = (load_bank(bank_root / name, name) for name in ("runtime_fit", "runtime_select"))
                for bank, expected_pairs in ((train, p["fit_pairs"]), (selection, p["selection_pairs"])):
                    bank_meta = bank["metadata"]
                    require(bank_meta["seed"] == args.seed and bank_meta["profile"] == args.profile
                            and bank_meta["source_manifest_sha256"] == protocol["source_manifest_sha256"]
                            and bank_meta["metadata"]["protocol_sha256"] == file_hash(protocol_path)
                            and bank_meta["pairs"] == expected_pairs and bank_meta["rows"] == 4 * expected_pairs,
                            "Bank source/model scope or registered size differs")
                for key in ("model_parameter_sha256", "observer_parameter_sha256"):
                    require(train["metadata"][key] == selection["metadata"][key], "Fit/selection model identities differ")
                metadata.update(model_parameter_sha256=train["metadata"]["model_parameter_sha256"],
                    reward_observer_parameter_sha256=train["metadata"]["observer_parameter_sha256"],
                    bank_complete_sha256={name: file_hash(bank_root / name / "COMPLETE.json")
                                          for name in ("runtime_fit", "runtime_select")})
                result = fit_controllers(train, selection, bridge, metadata, destination / "features.npz")
                write_json(destination / "READOUTS.json", result)
                write_json(destination / "COMPLETE.json", {"phase": phase, "seed": args.seed, "profile": args.profile,
                    "files": {name: file_hash(destination / name) for name in ("START.json", "READOUTS.json", "features.npz")},
                    "candidate_policies": result["candidate_policies"], "stage_head_fits": result["stage_head_fits"],
                    "native_tick_calls": result["native_tick_calls"], "fit_wall_ns": result["fit_wall_ns"]})
            else:
                observer_names = ["reward"] if args.phase == "bank" else ["reward", "audit"]
                originals, observers, identities = load_assets(args.assets, [args.seed], observer_names)
                model = profile_model(root, args.profile, args.seed, originals[args.seed], protocol, freeze)
                write_json(destination / "ASSET_IDENTITIES.json", identities)
                if args.phase == "bank":
                    roles = ["runtime_fit", "runtime_select"]
                    corpus = load_corpus_roles(Path(args.assets) / "ndu-data", roles)
                    for role in roles:
                        build_bank(model, corpus, observers["reward"], args.seed, args.profile, role,
                                   protocol, destination / role, metadata)
                    write_json(destination / "COMPLETE.json", {"phase": phase, "seed": args.seed, "profile": args.profile,
                        "files": {str(path.relative_to(destination)): file_hash(path) for path in sorted(destination.rglob("*")) if path.is_file()},
                        "source_roles": roles, "source_manifest_sha256": corpus.manifest["manifest_sha256"]})
                else:
                    fit = read_fit(root, args.seed, args.profile, freeze)
                    fitted_meta = fit["fit_identities"]["metadata"]
                    require(parameter_hash(model) == fitted_meta["model_parameter_sha256"]
                            and parameter_hash(observers["reward"]) == fitted_meta["reward_observer_parameter_sha256"],
                            "Selected generator/public observer differs from the frozen fitted bank")
                    policies = policies_for(root, args.seed, args.profile, args.phase, fit, freeze, protocol)
                    role = "runtime_audit" if args.phase == "audit" else args.role
                    corpus = load_corpus_roles(Path(args.assets) / "ndu-data", [role])
                    expected = p["audit_pairs"] if role == "runtime_audit" else protocol["confirmation"][role + "_pairs"]
                    require(len(corpus.splits[role]) == 2 * expected, "Selected execution size differs from registration")
                    complete = run_profile(model, corpus, observers, policies, bridge, args.seed, args.profile, role,
                        protocol, destination / "selected", metadata)
                    write_json(destination / "COMPLETE.json", {**complete,
                        "files": {str(path.relative_to(destination)): file_hash(path) for path in sorted(destination.rglob("*")) if path.is_file()}})
            require(not bridge._sessions and bridge.library.hepta_stream_live_sessions() == 0, "Leaked native episode state")
        require(source_files() == sources, "Runtime source changed during execution")
        verify_freeze(args.freeze, protocol_path, phase, root)
    except BaseException as error:
        write_json(destination / "FAILED.json", {"phase": phase, "seed": args.seed, "profile": args.profile,
            "error": str(error), "error_type": type(error).__name__, "traceback": traceback.format_exc(),
            "partial_evidence_preserved": True, "freeze_sha256": file_hash(args.freeze)})
        raise
    print(json.dumps({"phase": phase, "seed": args.seed, "profile": args.profile,
                      "complete_sha256": file_hash(destination / "COMPLETE.json")}), flush=True)


if __name__ == "__main__":
    main()
