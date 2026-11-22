"""Reproduce saved P4 KEEP/selected scores only; no fitting, gradients or test.

CPU FP64, one thread. Identical config/state/input triples share a verification
cache. Every cost here is post-hoc verification, excluded from training claims.
Run after validate_flow_study.py with the same STUDY_ROOT and --source-root.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch

from validate_flow_details import (
    Checks,
    array_digest,
    close,
    digest,
    load_checkpoint,
    read,
    tensor_digest,
)
from validate_flow_study import SOURCE_SHA


def replay(root, source_root, output):
    began, cpu_began = time.perf_counter(), time.process_time()
    checks = Checks()
    launch = read(root / "LAUNCH.json")
    if launch.get("state") != "completed" or "active_trial" in launch:
        raise RuntimeError("only a completed study may be replayed")
    verification_path = root / "POSTHOC" / "verification.json"
    prior = read(verification_path)
    if not prior["passed"] or prior["launch_sha256"] != digest(root / "LAUNCH.json"):
        raise RuntimeError(
            "a matching successful post-hoc artifact verification is required"
        )
    manifest = read(root / "SOURCE_MANIFEST.json")
    if digest(root / "SOURCE_MANIFEST.json") != SOURCE_SHA:
        raise RuntimeError("unexpected frozen source manifest")
    for item in manifest["files"]:
        relative = Path(item["path"])
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or digest(source_root / relative) != item["sha256"]
        ):
            raise RuntimeError(
                "source changed before selected-model replay: " + str(relative)
            )
    sys.path.insert(0, str(source_root))
    from qualification.hcsn_scale.model import ModelConfig, SequenceModel

    costs = {
        "source_and_precheck_seconds": time.perf_counter() - began,
        "checkpoint_io_seconds": 0.0,
        "model_reconstruction_seconds": 0.0,
        "forward_seconds": 0.0,
        "forward_calls": 0,
        "sensor_transition_rows": 0,
        "cache_hits": 0,
        "backward_evaluations": 0,
        "conditional_solves": 0,
        "test_queries": 0,
    }
    cache, rows = {}, []
    plan = read(root / "ADAPTATION_PLAN.json")
    summary = read(root / "POSTHOC" / "summary.json")

    def evaluate(config, state, state_sha, x, dt):
        state_key = (
            json.dumps(config, sort_keys=True),
            state_sha,
            array_digest({"x": x, "dt": dt}),
        )
        if state_key in cache:
            costs["cache_hits"] += 1
            return cache[state_key]
        tick = time.perf_counter()
        model = SequenceModel(ModelConfig(**config)).cpu().double().eval()
        model.load_state_dict(state, strict=True)
        if tensor_digest(model.state_dict()) != state_sha:
            raise RuntimeError("reconstructed model differs from saved state")
        costs["model_reconstruction_seconds"] += time.perf_counter() - tick
        windows, intervals = torch.from_numpy(x), torch.from_numpy(dt)
        tick = time.perf_counter()
        with torch.no_grad():
            features = model.encode_batch(windows[:, :-1], intervals[:, :-1]).flatten(
                0, 1
            )
            targets = windows[:, 1:].flatten(0, 1)
            loss = float((model.predictor(features) - targets).square().mean())
        costs["forward_seconds"] += time.perf_counter() - tick
        costs["forward_calls"] += 1
        costs["sensor_transition_rows"] += len(targets)
        cache[state_key] = loss
        return loss

    for entry in (row for row in launch["trials"] if row["study"] == "adaptation"):
        arm, seed = entry["arm"], entry["seed"]
        label = f"{arm}/{seed}"
        start_check = len(checks.rows)
        try:
            tick = time.perf_counter()
            directory = root / "adaptation" / f"{arm}-{seed}"
            study = read(directory / "STUDY.json")
            if (
                digest(directory / "prepared_inputs.npz")
                != study["prepared_inputs_sha256"]
            ):
                raise RuntimeError("prepared data artifact changed")
            with np.load(
                directory / "prepared_inputs.npz", allow_pickle=False
            ) as artifact:
                arrays = {name: artifact[name] for name in artifact.files}
            result_dir = directory / f"seed_{seed}" / arm
            result = read(result_dir / "RESULT.json")
            if (
                digest(result_dir / "candidates.pt")
                != result["candidate_artifact_sha256"]
            ):
                raise RuntimeError("candidate artifact changed")
            payload = load_checkpoint(result_dir / "candidates.pt")
            ledger = result["ledger"]
            config = payload["model_identity"]["config"]
            checks.check(
                ledger == payload["ledger"] and config["dtype"] == "float64",
                label + "/bound_fp64_model",
            )
            costs["checkpoint_io_seconds"] += time.perf_counter() - tick
            scores = {}
            for role, candidate in (
                ("keep", ledger["candidates"][0]),
                ("selected", ledger["candidates"][ledger["selected_index"]]),
            ):
                sha = candidate["state_digest"]
                state = (
                    payload["states_by_digest"][sha]
                    if role == "keep"
                    else payload["selected_state_dict"]
                )
                checks.check(
                    tensor_digest(state) == sha, label + "/" + role + "_state_hash"
                )
                scores[role] = {}
                for split in ("dev", "preservation"):
                    measured = evaluate(
                        config, state, sha, arrays[split + "_x"], arrays[split + "_dt"]
                    )
                    expected = candidate[
                        "dev_mse" if split == "dev" else "preservation_mse"
                    ]
                    checks.check(
                        close(measured, expected),
                        label + "/" + role + "_" + split + "_score",
                        {
                            "saved": expected,
                            "replayed": measured,
                            "absolute_difference": abs(measured - expected),
                        },
                    )
                    scores[role][split] = measured
            allowance = plan["adaptation"]["preservation_tolerance"]
            # Report the numerical tolerance explicitly; original gate remains unchanged.
            numeric = 1e-12 + 1e-10 * abs(scores["keep"]["preservation"])
            checks.check(
                scores["selected"]["preservation"]
                <= scores["keep"]["preservation"] + allowance + numeric,
                label + "/replayed_preservation_bound",
            )
            checks.check(
                ledger["selected_index"] == 0
                or scores["selected"]["dev"]
                < scores["keep"]["dev"]
                - plan["adaptation"]["min_dev_improvement"]
                + numeric,
                label + "/replayed_improvement_or_keep",
            )
            rows.append(
                {
                    "arm": arm,
                    "seed": seed,
                    "selected_index": ledger["selected_index"],
                    "selected_state_digest": ledger["selected_state_digest"],
                    "scores": scores,
                    "preservation_delta": scores["selected"]["preservation"]
                    - scores["keep"]["preservation"],
                    "verified": all(row["passed"] for row in checks.rows[start_check:]),
                }
            )
        except Exception as error:
            checks.check(
                False, label + "/replay_error", type(error).__name__ + ": " + str(error)
            )
            rows.append(
                {"arm": arm, "seed": seed, "verified": False, "error": str(error)}
            )
    checks.check(
        len(rows) == 15 and len({(row["arm"], row["seed"]) for row in rows}) == 15,
        "all_15_selected_and_keep_pairs",
    )
    for portfolio in summary["portfolio_choice"]:
        group = [
            row for row in rows if row["seed"] == portfolio["seed"] and row["verified"]
        ]
        if len(group) != 5:
            checks.check(False, f"portfolio/{portfolio['seed']}/complete_replays")
            continue
        minimum = min(row["scores"]["selected"]["dev"] for row in group)
        tied = [
            row
            for row in group
            if row["scores"]["selected"]["dev"] <= minimum + portfolio["tie_tolerance"]
        ]
        chosen = min(tied, key=lambda row: portfolio["tie_priority"].index(row["arm"]))
        checks.check(
            chosen["arm"] == portfolio["method"]
            and chosen["selected_state_digest"] == portfolio["state_digest"],
            f"portfolio/{portfolio['seed']}/replayed_choice",
        )
    costs.update(
        total_verification_seconds=time.perf_counter() - began,
        verification_cpu_seconds=time.process_time() - cpu_began,
    )
    report = {
        "schema": "hcsn-selected-state-replay-v1",
        "passed": checks.ok,
        "rows": rows,
        "checks": checks.rows,
        "failures": [row for row in checks.rows if not row["passed"]],
        "cost": costs,
        "source_manifest_sha256": SOURCE_SHA,
        "prior_verification_sha256": digest(verification_path),
        "script_sha256": digest(__file__),
        "runtime": {
            "torch": str(torch.__version__),
            "threads": torch.get_num_threads(),
            "interop_threads": torch.get_num_interop_threads(),
            "device": "cpu",
            "dtype": "float64",
        },
        "score_tolerance": {"absolute": 1e-12, "relative": 1e-10},
        "scope": "post-hoc verification of saved KEEP and selected sensor predictions; no training, fitting, full candidate replay or test evaluation",
        "cost_treatment": "verification costs are separate; original cold training/search costs remain unchanged",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("studyroot", type=Path)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    result = replay(
        args.studyroot.resolve(),
        args.source_root.resolve(),
        (args.output or args.studyroot / "POSTHOC" / "selected_replay.json").resolve(),
    )
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "forward_calls": result["cost"]["forward_calls"],
                "verification_seconds": result["cost"]["total_verification_seconds"],
            }
        )
    )
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
