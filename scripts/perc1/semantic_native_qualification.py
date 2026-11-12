"""Replay preserved PERC heads through native ownership; never new confirmation."""

import argparse
import json
from pathlib import Path
import shutil
import time

import numpy as np

from perc1_process_meter import run as measured_run

from .schema import canonical, require, sha
from .semantic_policy import head_scores
from .semantic_replay_data import load_replay


def write(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def validate_candidate_mapping(value, candidates):
    reserved = value["abstain_candidate_id"]
    require(
        type(reserved) is str and reserved not in candidates, "invalid abstain identity"
    )
    require(
        value["source_candidate_ids"] == candidates, "native source catalog differs"
    )
    policy = value["decision"]["policy"]
    require(
        len(policy) == 5
        and {row["candidate_id"] for row in policy} == set(candidates + [reserved]),
        "native policy catalog differs",
    )
    selected = value["decision"]["selected_candidate"]
    require(selected in candidates + [reserved], "unknown native choice")
    abstained = selected == reserved
    require(
        type(value["abstained"]) is bool and value["abstained"] == abstained,
        "native abstention differs",
    )
    require(
        value["selected_source_candidate"] == (None if abstained else selected),
        "native source choice mapping differs",
    )


def qualify(args):
    started = time.perf_counter_ns()
    root = args.output.absolute()
    root.mkdir(mode=0o700)
    repo = Path(__file__).resolve().parents[2]
    code = [
        Path(__file__),
        Path(__file__).with_name("semantic_replay_data.py"),
        Path(__file__).with_name("semantic_policy.py"),
        Path(__file__).with_name("semantic_contract.py"),
        Path(__file__).with_name("semantic_data.py"),
        Path(__file__).with_name("schema.py"),
        Path(__file__).with_name("native.py"),
        repo / "scripts/perc1_process_meter.py",
        *sorted((repo / "scripts").glob("perc1_semantic_native*.rs")),
    ]
    pins = {str(p.relative_to(repo)): sha(p.read_bytes()) for p in code}
    binary = args.native_binary.absolute()
    binary_sha = sha(binary.read_bytes())
    source, cases = load_replay(args.archive)
    source_sha = sha(source)
    write(root / "SOURCE_MANIFEST.json", source)
    models = root / "models"
    models.mkdir()
    results, envelopes = [], []

    def invoke(name, argv, *, refusal=None):
        receipt = measured_run(
            [str(binary), *map(str, argv)],
            root / name,
            cwd=repo,
            timeout_seconds=30,
            source_paths=[*code, binary],
        )
        require(receipt["measurement_valid"], f"{name}: invalid process measurement")
        envelopes.append({"name": name, "receipt": f"{name}/receipt.json"})
        require(
            receipt["outcome"] == ("failed" if refusal else "succeeded")
            and receipt["returncode"] == (1 if refusal else 0),
            f"{name}: unexpected lifecycle/exit; retained original stderr",
        )
        if refusal:
            require(
                refusal in (root / name / "stderr.bin").read_text(),
                f"{name}: refusal reason differs; inspect retained stderr",
            )
        return receipt

    selected = [case for case in cases if case["split"] == "confirmation"]
    require(len(selected) == 180, "historical confirmation denominator changed")
    model_registry = {
        (arm, seed) for arm in ("global", "dense") for seed in (1101, 2202, 3303)
    }
    require(
        {(case["arm"], case["seed"]) for case in selected} == model_registry,
        "historical model registry changed",
    )
    task_sets = [
        {case["task_id"] for case in selected if (case["arm"], case["seed"]) == model}
        for model in sorted(model_registry)
    ]
    require(
        all(len(tasks) == 30 and tasks == task_sets[0] for tasks in task_sets),
        "historical task panel changed across models",
    )
    seen, fault_models = set(), set()
    worst_error = 0.0
    for index, case in enumerate(selected):
        identity = (case["task_id"], case["arm"], case["seed"])
        require(identity not in seen, "duplicate historical case")
        seen.add(identity)
        require(
            case["head"]["arm"] == case["arm"]
            and case["head"]["seed"] == case["seed"]
            and sha(json.loads(case["head_raw"])) == sha(case["head"]),
            "replay head identity mismatch",
        )
        require(
            len(case["candidate_ids"]) == 4
            and len(set(case["candidate_ids"])) == 4
            and all(type(candidate) is str for candidate in case["candidate_ids"]),
            "invalid replay candidate catalog",
        )
        model_key = f"{case['arm']}-{case['seed']}"
        head_path = models / (model_key + ".json")
        if not head_path.exists():
            with head_path.open("xb") as stream:
                stream.write(case["head_raw"])
        require(sha(head_path.read_bytes()) == sha(case["head_raw"]), "model drift")
        case_root = root / f"case-{index:03d}"
        case_root.mkdir()
        rows = np.asarray(case["rows"], dtype=np.float64)
        require(rows.shape == (4, 59) and np.isfinite(rows).all(), "feature shape")
        envelope = {
            "schema": "perc1.semantic-native-features.v1",
            "rows": rows.tolist(),
            "candidate_ids": case["candidate_ids"],
            "source_manifest_sha256": source_sha,
            "head_sha256": sha(case["head_raw"]),
            "projection_sha256": case["head"]["projection_sha256"],
        }
        features = case_root / "features.json"
        write(features, envelope)
        expected = head_scores(case["head"], rows)
        ranking = sorted(
            range(4), key=lambda i: (-expected[i], case["candidate_ids"][i])
        )
        expected_ranking = [case["candidate_ids"][i] for i in ranking]
        write(
            case_root / "REFERENCE.json",
            {"logits_f64": expected, "ranking": expected_ranking},
        )
        owner, observed_path = case_root / "owner", case_root / "first.json"
        invoke(
            f"commands/{index:03d}-first",
            ["start", owner, features, head_path, observed_path],
        )
        observed = json.loads(observed_path.read_bytes())
        validate_candidate_mapping(observed, case["candidate_ids"])
        logits = np.asarray(observed["logits_f64"], dtype=np.float64)
        require(
            logits.shape == (4,) and np.isfinite(logits).all(), "invalid native logits"
        )
        error = float(np.max(np.abs(logits - expected)))
        worst_error = max(worst_error, error)
        require(
            np.allclose(logits, expected, rtol=1e-10, atol=1e-10),
            "native arithmetic differs",
        )
        require(observed["ranking"] == expected_ranking, "native ranking differs")
        require(
            observed["trained_semantic_head_inference_executions"] == 1,
            "head did not execute once",
        )
        require(observed["status"] == "COMMITTED", "owner did not commit")
        replay_path = case_root / "replay.json"
        invoke(f"commands/{index:03d}-replay", ["read", owner, replay_path])
        replay = json.loads(replay_path.read_bytes())
        validate_candidate_mapping(replay, case["candidate_ids"])
        require(replay["status"] == "REPLAYED", "cold process did not replay")
        require(
            replay["trained_semantic_head_inference_executions"] == 0,
            "replay executed model",
        )
        for key in ("logits_f64", "ranking", "decision"):
            require(replay[key] == observed[key], f"replay changed {key}")
        results.append(
            {
                "task_id": case["task_id"],
                "arm": case["arm"],
                "seed": case["seed"],
                "historical_split": "confirmation",
                "max_abs_logit_error": error,
                "ranking_equal": True,
                "replay_equal": True,
                "source_manifest_sha256": source_sha,
                "head_file_sha256": envelope["head_sha256"],
                "features_file_sha256": sha(features.read_bytes()),
                "sparse_cell_selected_candidate": observed["selected_source_candidate"],
                "native_cell_selected_candidate": observed["decision"][
                    "selected_candidate"
                ],
                "sparse_cell_abstained": observed["abstained"],
                "raw_mlp_top_candidate": expected_ranking[0],
            }
        )
        if model_key not in fault_models:
            fault_models.add(model_key)
            pending_owner, pending_path = (
                case_root / "ack-owner",
                case_root / "pending.json",
            )
            invoke(
                f"commands/{index:03d}-lose-ack",
                ["lose-ack", pending_owner, features, head_path, pending_path],
            )
            pending = json.loads(pending_path.read_bytes())
            require(
                pending["status"] == "PENDING_ORIGINAL_READBACK",
                "ACK loss not retained",
            )
            require(
                pending["trained_semantic_head_inference_executions"] == 1,
                "ACK loss dispatched twice",
            )
            recovered_path = case_root / "recovered.json"
            invoke(
                f"commands/{index:03d}-recover", ["read", pending_owner, recovered_path]
            )
            recovered = json.loads(recovered_path.read_bytes())
            validate_candidate_mapping(recovered, case["candidate_ids"])
            require(
                recovered["status"] == "COMMITTED", "original inference not recovered"
            )
            require(
                recovered["trained_semantic_head_inference_executions"] == 0,
                "recovery executed model",
            )
            require(
                recovered["inference_readbacks"] == 1, "recovery did not read original"
            )
            require(
                recovered["logits_f64"] == observed["logits_f64"],
                "recovery changed logits",
            )
            require(
                recovered["ranking"] == observed["ranking"], "recovery changed ranking"
            )
            recovered_replay_path = case_root / "recovered-replay.json"
            invoke(
                f"commands/{index:03d}-recovered-replay",
                ["read", pending_owner, recovered_replay_path],
            )
            recovered_replay = json.loads(recovered_replay_path.read_bytes())
            require(
                recovered_replay["status"] == "REPLAYED"
                and recovered_replay["trained_semantic_head_inference_executions"] == 0
                and recovered_replay["inference_readbacks"] == 0,
                "committed recovery caused new inference or original readback",
            )
            for key in ("logits_f64", "ranking", "decision"):
                require(
                    recovered_replay[key] == recovered[key],
                    f"recovered replay changed {key}",
                )
    require(len(fault_models) == 6, "missing model ACK-loss case")
    negative = root / "negative"
    negative.mkdir()
    bad = dict(envelope, head_sha256="0" * 64)
    bad_path = negative / "bad-binding.json"
    write(bad_path, bad)
    invoke(
        "commands/negative-binding",
        ["start", negative / "bad-owner", bad_path, head_path, negative / "bad.json"],
        refusal="head byte binding mismatch",
    )
    require(
        not (negative / "bad-owner/head-claim.bin").exists()
        and not (negative / "bad-owner/head-receipt.json").exists(),
        "bad binding dispatched inference",
    )
    corrupted = negative / "corrupt-owner"
    shutil.copytree(root / "case-000/owner", corrupted)
    retained_head = corrupted / "head.json"
    with retained_head.open("ab") as stream:
        stream.write(b" ")
    before_refusal = {
        str(path.relative_to(corrupted)): sha(path.read_bytes())
        for path in corrupted.rglob("*")
        if path.is_file()
    }
    invoke(
        "commands/negative-retained-head",
        ["read", corrupted, negative / "corrupt.json"],
        refusal="retained source changed",
    )
    require(
        before_refusal
        == {
            str(path.relative_to(corrupted)): sha(path.read_bytes())
            for path in corrupted.rglob("*")
            if path.is_file()
        },
        "corrupt replay changed owner state",
    )
    require(
        not (negative / "bad.json").exists()
        and not (negative / "corrupt.json").exists(),
        "negative control emitted success",
    )
    require(
        pins == {str(p.relative_to(repo)): sha(p.read_bytes()) for p in code},
        "source changed during execution",
    )
    require(binary_sha == sha(binary.read_bytes()), "native binary changed")
    write(root / "ROWS.json", results)
    sparse_matches = sum(
        row["sparse_cell_selected_candidate"] == row["raw_mlp_top_candidate"]
        for row in results
    )
    report = {
        "schema": "perc1.semantic-native-qualification.v1",
        "engineering_status": "PASS_HISTORICAL_HEAD_AND_OWNER_REPLAY_ONLY",
        "scientific_status": "HOLD",
        "adoption": "NoUpdate",
        "historical_cases": len(results),
        "unique_historical_tasks": len({c["task_id"] for c in results}),
        "models": len(fault_models),
        "new_confirmation_sources": 0,
        "max_abs_logit_error": worst_error,
        "ranking_matches": len(results),
        "candidate_identity_mapping_validated": True,
        "cell_abstentions": sum(row["sparse_cell_abstained"] for row in results),
        "candidate_policy_scope": "diagnostic sparse policy with hand-authored calibration; no semantic policy qualification",
        "sparse_cell_choice_matches_raw_mlp_top": sparse_matches,
        "sparse_cell_choice_differs_from_raw_mlp_top": len(results) - sparse_matches,
        "cold_process_replays_without_new_inference": len(results),
        "lost_ack_recoveries_without_new_inference": len(fault_models),
        "expected_refusals": 2,
        "source_manifest_sha256": source_sha,
        "source_pins": pins,
        "native_binary_sha256": binary_sha,
        "command_envelopes": envelopes,
        "source_unchanged": True,
        "driver_wall_ns": time.perf_counter_ns() - started,
        "production_daemon_integrated": False,
        "native_visual_encoder_exercised": False,
        "new_training_performed": False,
        "terminal_quality_gain_established": False,
        "raw_mlp_and_sparse_cell_decisions_reported_separately": True,
        "cost_scope": "per-command process envelopes plus inclusive driver wall; nested values must not be added; no capture/OCR/backbone performed",
        "energy_joules": None,
        "provider_billing": None,
    }
    write(root / "REPORT.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("native-binary", "archive", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    existed = args.output.exists()
    try:
        print(json.dumps(qualify(args), indent=2))
    except Exception as error:
        if not existed and args.output.is_dir():
            write(
                args.output / "FAILURE.json",
                {
                    "status": "FAILED",
                    "scientific_status": "HOLD",
                    "adoption": "NoUpdate",
                    "error_type": type(error).__name__,
                    "message": str(error),
                },
            )
        raise


if __name__ == "__main__":
    main()
