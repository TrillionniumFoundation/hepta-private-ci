"""Freeze all V4 predictions, then execute the shared real action census."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from cell_field_action_control import score_common
from cell_field_action_io import EXTRA_SOURCE_FILES, deny_withheld_labels, environment, load_inputs, project, split_arrays
from cell_field_closure_control import ARMS, closure_maps, fixed_actions
from cell_field_closure_data import write
from cell_field_control import build_reference
from cell_field_features import file_hash, load_features
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead, normalize_features


def arrays(path, **values):
    with Path(path).open("xb") as stream:
        np.savez_compressed(stream, **values)


def seal(root, name):
    files = {str(p.relative_to(root)): {"sha256": file_hash(p), "bytes": p.stat().st_size}
             for p in sorted(root.rglob("*")) if p.is_file()}
    write(root / name, {"schema": "hepta.cell-closure-seal.v4", "files": files,
                       "at_utc": datetime.now(timezone.utc).isoformat()})
    return file_hash(root / name)


def score(plan, reference, old_anchor, action, fields):
    sequence = np.zeros((plan["horizon"], len(action)))
    sequence[0] = action
    return score_common(fields, sequence, reference.observations[:, :2], old_anchor,
                        dt=plan["h"], effort_price=plan["effort_price"],
                        current_shift=plan["current_shift"], direct_coefficient=plan["direct_coefficient"])


def source_hashes():
    names = ["cell_field_action_control.py", "cell_field_action_io.py", "cell_field_features.py",
             "cell_field_control.py", "cell_field_state.py", "cell_learning_models.py", "cell_learning_metrics.py",
             "cell_field_closure_control.py", "cell_field_closure_run.py", "cell_field_closure_data.py",
             "cell_field_closure_evaluate.py", "cell_field_closure_audit.py", "cell_field_closure_features.py",
             "requirements-cell-closure-v4.txt"]
    return {name: file_hash(Path(__file__).with_name(name)) for name in sorted(set(names) | set(EXTRA_SOURCE_FILES))}


def execute(v3_data, v3_features, v3_protocol, data, features, protocol, source_commit, output):
    sys.addaudithook(deny_withheld_labels)
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    try:
        plan = json.loads(Path(protocol).read_bytes())
        if tuple(plan["arms"]) != ARMS or plan["horizon"] != 8:
            raise ValueError("registered closure census changed")
        if any(os.environ.get(key) not in {"1", "2"} for key in
               ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")):
            raise ValueError("launch with each registered numerical thread limit at one or two")
        git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent,
                             text=True, capture_output=True, check=True, timeout=10).stdout.strip()
        if git != source_commit:
            raise ValueError("executed source commit differs from frozen head")
        hashes = source_hashes()
        paths = sorted(hashes) + [Path(protocol).name]
        if Path(protocol).resolve().parent != Path(__file__).resolve().parent:
            raise ValueError("run the committed protocol beside the committed source")
        for command in (["git", "ls-files", "--error-unmatch", "--", *paths],
                        ["git", "diff", "--quiet", "HEAD", "--", *paths]):
            subprocess.run(command, cwd=Path(__file__).parent, text=True, capture_output=True,
                           check=True, timeout=10)
        write(root / "source-freeze.json", {"git_commit": git, "files": hashes,
              "protocol_sha256": file_hash(protocol), "authority": "DENY_ALL"})
        if file_hash(v3_protocol) != plan["v3_protocol_sha256"]:
            raise ValueError("original V3 protocol changed")
        original = load_inputs(v3_data, v3_features, v3_protocol)
        if (file_hash(Path(v3_data) / "sources.json") != plan["v3_sources_sha256"]
                or file_hash(Path(v3_features) / "features.npz") != plan["v3_features_sha256"]):
            raise ValueError("original V3 data or real feature bytes changed")
        projected, q = project(original["features"], original["plan"])
        split = split_arrays(projected, original["labels"])
        new_features, new_report = load_features(features, file_hash(protocol))
        data, features = Path(data), Path(features)
        receipt = json.loads((data / "data_receipt.json").read_bytes())
        sources = json.loads((data / "sources.json").read_bytes())["rows"]
        if (receipt["protocol_sha256"] != file_hash(protocol)
                or receipt["files"]["sources.json"]["sha256"] != file_hash(data / "sources.json")
                or new_report["plan"]["data_receipt_sha256"] != file_hash(data / "data_receipt.json")
                or new_report["plan"]["source_ids"] != [x["source_id"] for x in sources]
                or new_report["encoder_identity"]["checkpoint_revision"] != plan["encoder_revision"]
                or new_report["encoder_updates"] != 0
                or new_report["bridge"]["passed"] is not True
                or new_report["bridge"]["maximum_absolute_feature_difference"] > plan["encoder_bridge"]["maximum_absolute_feature_difference"]
                or new_features.shape != (sum(x["rows"] for x in plan["new_source_plan"]), 384)):
            raise ValueError("fresh real feature/source binding mismatch")
        new_projected = new_features.astype(np.float64) @ q
        arrays(root / "projection.npz", q=q)
        arrays(root / "new-projected-features.npz", features=new_projected)
        write(root / "protocol.json", plan)
        write(root / "inputs.json", {"v3_input_hashes": original["input_hashes"],
              "new_data_receipt_sha256": file_hash(data / "data_receipt.json"),
              "new_sources_sha256": file_hash(data / "sources.json"),
              "new_feature_report_sha256": file_hash(features / "report.json"),
              "new_feature_sha256": file_hash(features / "features.npz"),
              "final_labels_sha256": receipt["files"]["final_labels.json"]["sha256"],
              "final_labels_opened": False})
        contexts = {name: dataset_digest(*split[name]) for name in ("old_train", "current_train")}
        runtime, anchors, warmups = [], [], []
        for seed in plan["seeds"]:
            for mode in plan["head_modes"]:
                state = CellTrainingState(NumpyCellHead(8, 4, mode, seed=seed),
                    bindings={"protocol_sha256": file_hash(protocol), "seed": seed, "mode": mode,
                              "source_commit": git, "v3_features_sha256": plan["v3_features_sha256"]},
                    protocol=plan["optimizer"], seed=seed, contexts=contexts, active_context="old_train")
                warm_receipts = [state.advance(*split["old_train"]) for _ in range(plan["warmup_steps"])]
                state.select_context("current_train")
                warm_id = f"seed{seed}-{mode}"
                warm_path = root / (warm_id + "-warm.npz")
                arrays(warm_path, state=state.vector(), predictions=state.head.predict_proba(new_projected))
                write(root / (warm_id + "-warm-receipts.json"), warm_receipts)
                warmups.append({"id": warm_id, "seed": seed, "head": mode, "path": warm_path.name})
                old_anchor = state.head.loss_gradients(normalize_features(split["old_probe"][0]), split["old_probe"][1], 0.0)[0]
                offset = 0
                for target in plan["anchor_offsets"]:
                    while offset < target:
                        state.advance(*split["current_train"])
                        offset += 1
                    identity = f"{warm_id}-step{target}"
                    directory = root / identity
                    directory.mkdir()
                    initial = state.clone()
                    initial.save(directory / "checkpoint")
                    reference = build_reference(initial, *split["current_train"],
                        probes=(split["current_probe"], split["old_probe"]), horizon=8, dt=plan["h"])
                    arrays(directory / "reference.npz", **reference.arrays())
                    actions = fixed_actions(initial.parameter_count, **{key: plan["action_library"][key]
                                            for key in ("seed", "directions", "radius")})
                    arrays(directory / "actions.npz", actions=actions)
                    forecasts, metadata, selected = {}, {}, {}
                    for arm in ARMS:
                        maps, metadata[arm] = closure_maps(reference, arm)
                        fields = np.einsum("kij,aj->aki", maps, actions)
                        scores = [score(plan, reference, old_anchor, action, response)
                                  for action, response in zip(actions, fields)]
                        forecasts[arm] = {"scores": scores, "metadata": metadata[arm]}
                        selected[arm] = int(np.argmin([x["direct_soft_total"] for x in scores]))
                        arrays(directory / (arm + "-forecast.npz"), maps=maps, fields=fields)
                    write(directory / "forecast.json", {"arms": forecasts, "selected": selected})
                    record = {"id": identity, "seed": seed, "head": mode, "anchor_offset": target,
                              "parameter_count": initial.parameter_count, "old_anchor": old_anchor,
                              "reference_wall_ns": reference.build_wall_ns, "selected": selected,
                              "derivative_audit": reference.derivative_audit}
                    anchors.append(record)
                    runtime.append((initial, reference, actions, directory, record))
        write(root / "candidates.json", {"anchors": anchors, "warmups": warmups,
              "registered_branches": len(anchors) * plan["action_library"]["actions_per_anchor"]})
        candidate_seal = seal(root, "candidate-seal.json")
        records = []
        for initial, reference, actions, directory, record in runtime:
            for index, action in enumerate(actions):
                branch = initial.clone()
                branch_started, branch_cpu = time.perf_counter_ns(), time.process_time_ns()
                states, observations, receipts = [branch.vector()], [reference.observe(branch.vector())[0][:2]], []
                for k in range(8):
                    receipts.append(branch.advance(*split["current_train"],
                        intervention=plan["h"] * action if k == 0 else np.zeros(len(action))))
                    states.append(branch.vector())
                    observations.append(reference.observe(branch.vector())[0][:2])
                fields = np.asarray(observations) - reference.observations[:, :2]
                actual = score(plan, reference, record["old_anchor"], action, fields)
                filename = f"action-{index:02d}.npz"
                arrays(directory / filename, states=np.asarray(states), observations=np.asarray(observations),
                       fields=fields, predictions=branch.head.predict_proba(new_projected))
                write(directory / f"action-{index:02d}-receipts.json", receipts)
                records.append({"anchor": record["id"], "action": index, "status": "completed",
                                "path": record["id"] + "/" + filename, "actual": actual,
                                "wall_ns": time.perf_counter_ns() - branch_started,
                                "cpu_ns": time.process_time_ns() - branch_cpu})
        if source_hashes() != hashes:
            raise ValueError("frozen source changed during execution")
        write(root / "runs.json", {"schema": "hepta.cell-closure-run.v4", "source_commit": git,
              "anchors": anchors, "warmups": warmups, "records": records, "registered": 306,
              "completed": len(records), "candidate_seal_sha256": candidate_seal,
              "wall_ns": time.perf_counter_ns() - began, "cpu_ns": time.process_time_ns() - cpu,
              "environment": environment(), "final_labels_opened": False,
              "authority": "DENY_ALL", "production_authority": False})
        run_seal = seal(root, "run-seal.json")
        return {"anchors": len(anchors), "completed": len(records), "run_seal_sha256": run_seal,
                "source_commit": git, "final_labels_opened": False}
    except Exception as error:
        write(root / "failure.json", {"error_type": type(error).__name__, "message": str(error),
              "at_utc": datetime.now(timezone.utc).isoformat(), "final_labels_opened": False,
              "partial_outputs_preserved": True, "authority": "DENY_ALL"})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("v3-data", "v3-features", "v3-protocol", "data", "features", "protocol", "source-commit", "output"):
        parser.add_argument("--" + name, required=True)
    print(json.dumps(execute(**vars(parser.parse_args())), sort_keys=True))
