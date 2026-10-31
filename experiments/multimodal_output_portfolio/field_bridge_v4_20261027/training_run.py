"""Frozen, two-phase V4 qualification CLI. No V3 phase gate is invoked."""
import argparse
import json
from pathlib import Path
import re
import time
import traceback

from ..field_bridge_v3_20261027.training_common import file_hash, object_hash, require, write_json
from .training_qualification import (ADAPTATION_ROLES, ENDPOINT_ROLES, OLD_PROTOCOL_SHA, SCHEMA, SEEDS,
    evaluate_seed, policies, seal_training, settings, train_seed, verify_files, verify_seal)

HERE = Path(__file__).resolve().parent
PORTFOLIO = HERE.parent
PHASES = ("train", "seal-training", "evaluate", "qualify")


def source_files():
    paths = [HERE / name for name in ("PROTOCOL.json", "SOURCE_ALLOCATION.json", "SOURCE_IDENTITIES.json.gz",
                                      "source_roles.py", "training_qualification.py", "training_run.py")]
    paths.extend(HERE.glob("*.py"))
    paths.append(PORTFOLIO / "field_bridge_v4_20261027_review/training_panel_origin.py")
    legacy = PORTFOLIO / "field_bridge_v3_20261027"
    paths.extend(legacy / name for name in ("__init__.py", "PROTOCOL.json", "training_common.py", "assets.py",
                                          "learning.py", "training_features.py", "training_bank.py", "training_policy.py", "source_roles.py"))
    for directory in ("field_bridge_20261027", "v6"):
        paths.extend((PORTFOLIO / directory).glob("*.py"))
    paths.append(PORTFOLIO / "field_bridge_20261027/PROTOCOL.json")
    return {str(path.relative_to(PORTFOLIO)): file_hash(path) for path in sorted(set(paths))}


def verify_freeze(freeze_path, protocol_path, phase, root, old_root):
    root, old_root = Path(root).resolve(), Path(old_root).resolve()
    protocol = json.loads(Path(protocol_path).read_text())
    settings(protocol)
    old_protocol_path = PORTFOLIO / "field_bridge_v3_20261027/PROTOCOL.json"
    require(file_hash(old_protocol_path) == OLD_PROTOCOL_SHA
            and protocol["training"] == json.loads(old_protocol_path.read_text())["training"],
            "Frozen V3 numerical training choices were modified")
    freeze = json.loads(Path(freeze_path).read_text())
    require(freeze.get("study_id") == protocol["study_id"] and phase in freeze["allowed_phases"]
            and re.fullmatch(r"[0-9a-f]{40}", freeze["registered_commit"]), "Invalid study/phase/commit freeze")
    require(freeze["protocol_sha256"] == file_hash(protocol_path), "Protocol SHA differs from freeze")
    required = source_files()
    require(all(freeze["source_files"].get(name) == identity for name, identity in required.items()),
            "A required dependency is missing or changed in the source freeze")
    verify_files(PORTFOLIO, freeze["source_files"])
    allocation_path = HERE / "SOURCE_ALLOCATION.json"
    allocation = json.loads(allocation_path.read_text())
    require(file_hash(allocation_path) == protocol["source_allocation_sha256"]
            and allocation["manifest_sha256"] == protocol["source_manifest_sha256"], "Source register differs")
    from .source_roles import verify_registry
    registry, manifest = verify_registry(allocation_path)
    require(manifest["manifest_sha256"] == protocol["source_manifest_sha256"]
            and set(registry["roles"]) == set((*ADAPTATION_ROLES, *ENDPOINT_ROLES)), "Source-role register mismatch")
    old_required = ["DEVELOPMENT_SELECTION.json"]
    for seed in SEEDS:
        old_required += [f"bank/{seed}/BANK.json", f"bank/{seed}/COMPLETE.json",
                         f"fit/{seed}/CONTROLLERS.json", f"fit/{seed}/COMPLETE.json",
                         f"reference/{seed}/REFERENCE.json", f"reference/{seed}/COMPLETE.json"]
    require(all(freeze.get("old_artifacts", {}).get(name) == file_hash(old_root / name) for name in old_required),
            "Frozen old bank/head/comparator dependencies are missing or changed")
    verify_files(old_root, freeze["old_artifacts"])
    require(set(protocol["frozen_v3_learning_artifacts"]) == {str(seed) for seed in SEEDS}, "Frozen seed dependencies missing")
    for seed in SEEDS:
        expected_names = {f"bank/{seed}/BANK.json", f"fit/{seed}/CONTROLLERS.json", f"reference/{seed}/REFERENCE.json"}
        fixed = protocol["frozen_v3_learning_artifacts"][str(seed)]
        require(set(fixed) == expected_names, "Incomplete protocol-pinned historical dependencies")
        for name, identity in fixed.items():
            path = (old_root / name).resolve()
            require(path.is_relative_to(old_root) and path.stat().st_size == identity["bytes"]
                    and file_hash(path) == freeze["old_artifacts"].get(name) == identity["sha256"],
                    "Original protocol-pinned artifact identity differs: " + name)
    selection = json.loads((old_root / "DEVELOPMENT_SELECTION.json").read_text())
    require(selection["passed"] is False and selection["ordinary_action_indices"] == protocol["qualification"]["ordinary_action_indices"]
            and selection["selected_adaptive"] == "richer", "The failed old gate or fixed comparator was changed")
    if freeze.get("artifacts"):
        verify_files(root, freeze["artifacts"])
    if phase in {"evaluate", "qualify"}:
        seal = verify_seal(root, protocol)
        required_artifacts = {"TRAINING_SEAL.json": file_hash(root / "TRAINING_SEAL.json"), **seal["files"]}
        require(all(freeze.get("artifacts", {}).get(name) == identity for name, identity in required_artifacts.items()),
                "Endpoint phase requires external freeze binding the seal and every training artifact")
    return protocol, freeze, required


def run_scope(protocol_path, freeze_path, protocol, freeze, required):
    return {"study_id": protocol["study_id"], "protocol_sha256": file_hash(protocol_path),
        "source_allocation_sha256": protocol["source_allocation_sha256"],
        "source_manifest_sha256": protocol["source_manifest_sha256"],
        "source_files_sha256": object_hash(required), "registered_commit": freeze["registered_commit"],
        "freeze_sha256": file_hash(freeze_path), "old_training_protocol_sha256": OLD_PROTOCOL_SHA}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=PHASES)
    parser.add_argument("--assets")
    parser.add_argument("--out", required=True)
    parser.add_argument("--v3-run-root", required=True)
    parser.add_argument("--seed", type=int, choices=SEEDS)
    parser.add_argument("--protocol", default=str(HERE / "PROTOCOL.json"))
    parser.add_argument("--freeze", required=True)
    args = parser.parse_args()
    phase_started, phase_cpu = time.perf_counter_ns(), time.process_time_ns()
    root, old_root, protocol_path = Path(args.out).resolve(), Path(args.v3_run_root).resolve(), Path(args.protocol).resolve()
    protocol, freeze, required = verify_freeze(args.freeze, protocol_path, args.phase, root, old_root)
    preflight_wall, preflight_cpu = time.perf_counter_ns() - phase_started, time.process_time_ns() - phase_cpu
    require((args.seed in SEEDS) == (args.phase in {"train", "evaluate"}), "Seed is required only for train/evaluate")
    require(args.phase not in {"train", "evaluate"} or args.assets is not None, "Scientific phase requires pinned assets")
    scope = run_scope(protocol_path, args.freeze, protocol, freeze, required)
    if args.phase == "train":
        bank_path = old_root / "bank" / str(args.seed) / "BANK.json"
        controller_path = old_root / "fit" / str(args.seed) / "CONTROLLERS.json"
        scope.update(bank_sha256=file_hash(bank_path), controller_file_sha256=file_hash(controller_path),
                     reference_file_sha256=file_hash(old_root / "reference" / str(args.seed) / "REFERENCE.json"))
        bank, fitted = json.loads(bank_path.read_text()), json.loads(controller_path.read_text())
        policies(fitted, bank, protocol, scope)
        require(not (root / "TRAINING_SEAL.json").exists() and not (root / "evaluate").exists(),
                "Training cannot resume after the all-path seal or endpoint opening")
    destination = root / args.phase / str(args.seed) if args.phase in {"train", "evaluate"} else root / args.phase
    destination.mkdir(parents=True, exist_ok=False)
    roles = list(ADAPTATION_ROLES if args.phase == "train" else ENDPOINT_ROLES) if args.phase in {"train", "evaluate"} else []
    observers = ["reward"] if args.phase == "train" else (["reward", "audit"] if args.phase == "evaluate" else [])
    start = {"schema": SCHEMA + ".phase-start.1", "study_id": protocol["study_id"], "phase": args.phase,
        "seed": args.seed, "scope": scope, "source_files": required, "requested_roles": roles,
        "loaded_observer_names": observers, "started_unix_ns": time.time_ns(),
        "preflight_verification_wall_ns": preflight_wall, "preflight_verification_cpu_ns": preflight_cpu,
        "training_seal_sha256": file_hash(root / "TRAINING_SEAL.json") if args.phase in {"evaluate", "qualify"} else None}
    write_json(destination / "START.json", start)
    try:
        if args.phase == "seal-training":
            result = seal_training(root, protocol, scope)
            complete_path = root / "TRAINING_SEAL.json"
        elif args.phase == "qualify":
            from .qualification_analysis import qualify
            result = qualify(root, protocol)
            complete_path = root / "QUALIFICATION.json"
        else:
            import torch
            from ..field_bridge_v3_20261027.assets import load_assets
            from .source_roles import load_corpus_roles
            torch.set_num_threads(2)
            torch.set_num_interop_threads(1)
            torch.use_deterministic_algorithms(True)
            originals, loaded_observers, identities = load_assets(args.assets, [args.seed], observers)
            require(list(loaded_observers) == observers, "Unrequested observer was loaded")
            corpus = load_corpus_roles(Path(args.assets) / "ndu-data", roles,
                                      phase="adaptation" if args.phase == "train" else "endpoints")
            require(corpus.manifest["manifest_sha256"] == protocol["source_manifest_sha256"]
                    and list(corpus.splits) == roles, "Loaded data role identity differs")
            write_json(destination / "ASSET_IDENTITIES.json", {"schema": SCHEMA + ".asset-identities.1",
                        "study_id": protocol["study_id"], "identities": identities})
            if args.phase == "train":
                from ..field_bridge_v3_20261027.learning import make_context
                context = make_context(originals[args.seed], corpus, loaded_observers, args.seed, "qualification", protocol)
                result = train_seed(context, fitted, bank, scope, destination)
            else:
                result = evaluate_seed(originals[args.seed], corpus, loaded_observers, args.seed, protocol, root, destination, scope)
            complete_path = destination / "COMPLETE.json"
        postflight_started, postflight_cpu = time.perf_counter_ns(), time.process_time_ns()
        require(source_files() == required, "Frozen scientific source changed during execution")
        verify_freeze(args.freeze, protocol_path, args.phase, root, old_root)
        phase_receipt = {"schema": SCHEMA + ".phase-cost-receipt.1", "study_id": protocol["study_id"],
            "phase": args.phase, "seed": args.seed, "scope": scope, "complete_sha256": file_hash(complete_path),
            "preflight_verification_wall_ns": preflight_wall, "preflight_verification_cpu_ns": preflight_cpu,
            "postflight_verification_wall_ns": time.perf_counter_ns() - postflight_started,
            "postflight_verification_cpu_ns": time.process_time_ns() - postflight_cpu,
            "phase_wall_ns": time.perf_counter_ns() - phase_started, "phase_cpu_ns": time.process_time_ns() - phase_cpu,
            "timing_scope": "argument parsing through postflight verification; excludes interpreter startup and this receipt write"}
        write_json(root / "PHASE_RECEIPTS" / (args.phase + "-" + (str(args.seed) if args.seed else "all") + ".json"), phase_receipt)
    except BaseException as error:
        write_json(destination / "FAILED.json", {"schema": SCHEMA + ".phase-failed.1", "study_id": protocol["study_id"],
            "phase": args.phase, "seed": args.seed, "error_type": type(error).__name__, "error": str(error),
            "traceback": traceback.format_exc(), "scope": scope, "all_prior_records_preserved": True})
        raise
    print(json.dumps({"phase": args.phase, "study_id": protocol["study_id"], "seed": args.seed,
                      "complete_sha256": file_hash(complete_path), "passed": result.get("passed")}), flush=True)


if __name__ == "__main__":
    main()
