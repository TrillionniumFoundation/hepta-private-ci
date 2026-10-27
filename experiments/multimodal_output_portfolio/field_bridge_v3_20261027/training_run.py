"""Phase-gated V3 training CLI; fresh role labels require an external source freeze."""

import argparse
import json
from pathlib import Path
import time
import traceback

from .training_common import configuration, file_hash, require, verify_freeze, write_json


HERE = Path(__file__).parent
TRAINING_FILES = ("__init__.py", "PROTOCOL.json", "SOURCE_ALLOCATION.json", "SOURCE_IDENTITIES.json.gz",
                  "source_roles.py", "training_common.py", "assets.py", "learning.py", "training_features.py",
                  "training_bank.py", "training_policy.py", "training_stages.py", "training_run.py")


def source_files():
    """Exact training dependency inventory; runtime implementation can freeze later."""
    paths = [HERE / name for name in TRAINING_FILES]
    for directory in ("field_bridge_20261027", "v6"):
        paths.extend((HERE.parent / directory).glob("*.py"))
    paths.append(HERE.parent / "field_bridge_20261027/PROTOCOL.json")
    return {str(path.relative_to(HERE.parent)): file_hash(path) for path in sorted(set(paths))}


def previous_stage(path):
    path = Path(path)
    complete = json.loads((path / "COMPLETE.json").read_text())
    for name, identity in complete["files"].items():
        candidate = (path / name).resolve()
        require(candidate.is_relative_to(path.resolve()) and file_hash(candidate) == identity,
                f"Previous stage evidence changed: {name}")
    return complete


def require_bound(freeze, root, path):
    path = Path(path).resolve()
    require(path.is_relative_to(Path(root).resolve()), "Prior-stage artifact must be inside the registered run")
    name = str(path.relative_to(Path(root).resolve()))
    require(freeze.get("artifacts", {}).get(name) == file_hash(path), f"Artifact is not in the pre-outcome freeze: {name}")


def phase_roles(phase):
    if phase in {"fit", "select-development"}:
        return []
    group = "fit" if phase in {"reference", "bank", "final"} else phase
    roles = [group + suffix for suffix in ("_gradient", "_rehearsal", "_probe", "_guard")]
    if phase == "reference":
        roles += ["reference_task", "reference_clean"]
    elif phase in {"development", "audit"}:
        roles += [phase + "_task", phase + "_clean"]
    return roles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("reference", "bank", "fit", "development", "select-development", "audit", "final"))
    parser.add_argument("--assets")
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", type=int, choices=(17, 29, 43))
    parser.add_argument("--protocol", default=str(HERE / "PROTOCOL.json"))
    parser.add_argument("--freeze", required=True)
    parser.add_argument("--qualification")
    args = parser.parse_args()
    protocol_path, root = Path(args.protocol).resolve(), Path(args.out).resolve()
    protocol = json.loads(protocol_path.read_text())
    configuration(protocol)
    freeze = verify_freeze(args.freeze, protocol_path, args.phase, root)
    required = source_files()
    require(all(freeze["source_files"].get(name) == identity for name, identity in required.items()),
            "Source freeze omitted or changed a required training dependency")
    require(file_hash(HERE / "SOURCE_ALLOCATION.json") == protocol["source_allocation_sha256"],
            "Source allocation file differs from protocol")
    allocation = json.loads((HERE / "SOURCE_ALLOCATION.json").read_text())
    require(allocation["manifest_sha256"] == protocol["source_manifest_sha256"], "Source allocation content digest differs")
    require(args.phase == "select-development" or args.seed in protocol["seeds"], "A registered model seed is required")
    selected, controller_path = None, root / "fit" / str(args.seed) / "CONTROLLERS.json"
    if args.phase == "bank":
        prior = root / "reference" / str(args.seed)
        previous_stage(prior)
        for name in ("REFERENCE.json", "COMPLETE.json"):
            require_bound(freeze, root, prior / name)
    if args.phase == "fit":
        previous_stage(root / "bank" / str(args.seed))
    if args.phase in {"development", "audit", "final"}:
        previous_stage(controller_path.parent)
    if args.phase in {"audit", "final"}:
        selection_path = root / "DEVELOPMENT_SELECTION.json"
        for path in (selection_path, controller_path, controller_path.parent / "COMPLETE.json"):
            require_bound(freeze, root, path)
        selected = json.loads(selection_path.read_text())
        require(selected["passed"] and not selected["field_family_selection"], "Development did not qualify the fixed field treatment")
        for seed in protocol["seeds"]:
            previous_stage(root / "development" / str(seed))
            require(file_hash(root / "development" / str(seed) / "ENDPOINTS.npz") == selected["endpoint_file_sha256"][str(seed)],
                    "Development selection inputs changed")
    if args.phase == "final":
        require(args.qualification is not None, "Final training requires an independently audited qualification receipt")
        require_bound(freeze, root, args.qualification)
        qualification = json.loads(Path(args.qualification).read_text())
        require(qualification["passed"], "Independent complete-rollout audit did not qualify training")
    if args.phase == "select-development":
        for seed in protocol["seeds"]:
            previous_stage(root / "development" / str(seed))
        from .training_stages import select_development
        result = select_development(root, protocol)
        require(source_files() == required, "Training source changed during selection")
        print(json.dumps({"phase": args.phase, "passed": result["passed"], "selected_adaptive": result["selected_adaptive"]}), flush=True)
        return
    destination = root / args.phase / str(args.seed)
    destination.mkdir(parents=True, exist_ok=False)
    start = {"schema": "hepta.field-bridge.v3.training-phase-start.1", "phase": args.phase, "seed": args.seed,
        "registered_commit": freeze["registered_commit"], "freeze_sha256": file_hash(args.freeze),
        "protocol_sha256": file_hash(protocol_path), "source_files": required,
        "requested_roles": phase_roles(args.phase), "started_monotonic_ns": time.monotonic_ns()}
    write_json(destination / "START.json", start)
    try:
        if args.phase == "fit":
            from .training_policy import fit_bank
            fit_bank(root / "bank" / str(args.seed) / "BANK.json", destination, protocol)
        else:
            require(args.assets is not None, "This phase requires the pinned original assets")
            import torch
            from .assets import load_assets
            from .source_roles import load_corpus_roles
            from .learning import make_context
            torch.set_num_threads(2)
            torch.set_num_interop_threads(1)
            torch.use_deterministic_algorithms(True)
            observer_names = ["reward", "audit"] if args.phase in {"development", "audit"} else ["reward"]
            originals, observers, identities = load_assets(args.assets, [args.seed], observer_names)
            corpus = load_corpus_roles(Path(args.assets) / "ndu-data", phase_roles(args.phase))
            require(corpus.manifest["manifest_sha256"] == protocol["source_manifest_sha256"], "Loaded source role registry changed")
            write_json(destination / "ASSET_IDENTITIES.json", identities)
            group = "fit" if args.phase in {"reference", "bank", "final"} else args.phase
            context = make_context(originals[args.seed], corpus, observers, args.seed, group, protocol)
            if args.phase == "reference":
                from .training_bank import run_reference
                run_reference(context, destination)
            elif args.phase == "bank":
                from .training_bank import build_bank
                build_bank(context, root / "reference" / str(args.seed) / "REFERENCE.json", destination)
            else:
                from .training_stages import run_stage
                run_stage(context, controller_path, destination, args.phase, selected)
        require(source_files() == required, "Training source changed during execution")
        verify_freeze(args.freeze, protocol_path, args.phase, root)
    except BaseException as error:
        write_json(destination / "FAILED.json", {"phase": args.phase, "seed": args.seed, "error_type": type(error).__name__,
            "error": str(error), "traceback": traceback.format_exc(), "all_prior_records_preserved": True,
            "freeze_sha256": start["freeze_sha256"]})
        raise
    print(json.dumps({"phase": args.phase, "seed": args.seed, "complete_sha256": file_hash(destination / "COMPLETE.json")}), flush=True)


if __name__ == "__main__":
    main()
