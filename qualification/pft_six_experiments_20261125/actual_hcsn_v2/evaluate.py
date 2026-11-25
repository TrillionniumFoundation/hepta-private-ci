"""Separate post-seal evaluator; preflight every candidate before generating test."""
import argparse
import json
from pathlib import Path
import re
import time
import traceback

from common import (ScaledReadout, SmallHCSN, ModelConfig, data, data_hash, dump, extract,
                    metrics, np, ridge_logits, runtime, sha, torch, utc)
from runner import case_name, fit_to_numpy, tensor_digest, validate_protocol
from optimized import CachedSmallHCSN


def preflight(protocol_path, root, sealed=None):
    protocol = json.loads(Path(protocol_path).read_text())
    validate_protocol(protocol)
    if protocol["phase"] != "formal":
        raise ValueError("No testing of diagnostic or pilot data")
    names = [case_name(case) for case in protocol["cases"]]
    if len(set(names)) != len(names):
        raise ValueError("Duplicate frozen roster names")
    if sealed is not None and set(sealed) != set(names):
        raise ValueError("Sealed roster must match every and only frozen name")
    rows = []
    for case in protocol["cases"]:
        name = case_name(case)
        result = Path(root) / name / "RESULT.json"
        row = json.loads(result.read_text())
        if row["protocol_sha256"] != sha(protocol_path) or row["case"] != case:
            raise ValueError("Candidate roster identity mismatch")
        if row["status"] not in ("COMPLETED_MAX_UPDATES", "CENSORED_BUDGET", "FAILED"):
            raise ValueError("Unterminated candidate")
        if sha(result.with_name("HISTORY.json")) != row["history_sha256"]:
            raise ValueError("Selection history changed")
        if row.get("candidate_sha256"):
            if sha(result.with_name("candidate.pt")) != row["candidate_sha256"]:
                raise ValueError("Candidate changed after selection")
        bound = {"name": name, "result_sha256": sha(result), "candidate_sha256": row.get("candidate_sha256"),
                 "status": row["status"], "case": case}
        if sealed is not None and bound != sealed[name]:
            raise ValueError("Candidate changed after global seal")
        rows.append(bound)
    return protocol, rows


def seal(protocol_path, root, output, anchor):
    if not re.fullmatch("[0-9a-f]{40}", anchor):
        raise ValueError("An external Git source/protocol publication anchor is required")
    output = Path(output)
    if output.exists():
        raise FileExistsError("Global selection is already sealed")
    protocol, rows = preflight(protocol_path, root)
    dump(output, {"protocol_sha256": sha(protocol_path), "frozen_utc": utc(), "source_git_anchor": anchor,
                  "git_anchor_verification": "provided by orchestrator; independently checked through GitHub receipts",
                  "source_hashes": protocol["source_hashes"], "test_descriptor": protocol["data"],
                  "rows": rows, "test_generated": False})


def model_from_payload(payload, which):
    model = CachedSmallHCSN(ModelConfig(**payload["config"]))
    model.recurrent.weight.requires_grad_(payload["case"]["connection"] == "learned")
    model.readout = ScaledReadout(fit_to_numpy(payload["baseline_fits"]["standardized"]))
    model.load_state_dict(payload[which])
    return model


def evaluate(protocol_path, root, seal_path, out):
    out = Path(out)
    out.mkdir(exist_ok=False)
    start, cpu = time.perf_counter(), time.process_time()
    sealed = json.loads(Path(seal_path).read_text())
    if sealed["protocol_sha256"] != sha(protocol_path):
        raise ValueError("Sealed protocol identity changed")
    if len({row["name"] for row in sealed["rows"]}) != len(sealed["rows"]):
        raise ValueError("Duplicate seal names")
    protocol, bindings = preflight(protocol_path, root, {r["name"]: r for r in sealed["rows"]})
    dump(out / "OPEN_RECEIPT.json", {"seal_sha256": sha(seal_path), "protocol_sha256": sha(protocol_path),
                                   "test_first_generated_after_utc": utc(), "all_candidates_preflighted": len(bindings),
                                   "runtime": runtime(), "source_git_anchor": sealed["source_git_anchor"]})
    t = time.perf_counter()
    test = data("test", protocol["data"]["per_source_test"], protocol["data"]["seed"], "formal")
    data_time = time.perf_counter() - t
    np.savez_compressed(out / "test_data.npz", x=test["x"].numpy(), y=test["y"].numpy(),
                        margin=test["margin"].numpy(), late=test["late"].numpy(), ids=np.array(test["ids"]))
    rows = []
    for bound in bindings:
        if bound["status"] == "FAILED":
            rows.append({"name": bound["name"], "status": "UNAVAILABLE_FAILED_TRAINING", "case": bound["case"]})
            continue
        tick, tick_cpu = time.perf_counter(), time.process_time()
        try:
            source = Path(root) / bound["name"] / "candidate.pt"
            if sha(source) != bound["candidate_sha256"]:
                raise ValueError("Candidate changed after common preflight")
            t = time.perf_counter()
            payload = torch.load(source, map_location="cpu", weights_only=True)
            if payload["case"] != bound["case"] or payload["protocol_sha256"] != sha(protocol_path):
                raise ValueError("Loaded checkpoint identity mismatch")
            initial = model_from_payload(payload, "initial_weights")
            load_s = time.perf_counter() - t
            initial_logits, initial_features, initial_cost = extract(initial, test)
            t = time.perf_counter()
            scores, prediction_arrays = {}, {}
            for key, fit in payload["baseline_fits"].items():
                logits = ridge_logits(fit_to_numpy(fit), initial_features.numpy())
                scores[key] = metrics(logits, test)
                prediction_arrays[key] = logits
            metrics_s = time.perf_counter() - t
            t = time.perf_counter()
            selected = model_from_payload(payload, "selected_weights")
            selected_load_s = time.perf_counter() - t
            logits, _, selected_cost = extract(selected, test)
            score = metrics(logits, test)
            prediction_arrays["selected"] = logits.numpy()
            destination = out / (bound["name"] + ".npz")
            t = time.perf_counter()
            np.savez_compressed(destination, **prediction_arrays)
            serialize_s = time.perf_counter() - t
            rows.append({"name": bound["name"], "case": bound["case"], "status": "EVALUATED",
                         "training_status": bound["status"], "updates": payload["updates"],
                         "selected_step": payload["selected_step"], "selected": score, "baselines": scores,
                         "test_quality_reached": score["accuracy"] >= protocol["test_quality_threshold_accuracy"],
                         "candidate_sha256": bound["candidate_sha256"], "predictions_sha256": sha(destination),
                         "cost": {"file_load_and_initial_model_wall_s": load_s,
                                  "initial_feature_propagation_wall_s": initial_cost["wall_s"],
                                  "baseline_metrics_wall_s": metrics_s,
                                  "selected_model_load_wall_s": selected_load_s,
                                  "selected_feature_propagation_wall_s": selected_cost["wall_s"],
                                  "prediction_serialize_wall_s": serialize_s,
                                  "total_wall_s": time.perf_counter() - tick,
                                  "total_cpu_s": time.process_time() - tick_cpu},
                         "physical_diagnostics": selected_cost,
                         "load_scope": "fresh model objects in separate evaluation process; process reused across cases"})
            print(json.dumps({"name": bound["name"], "selected": score["accuracy"],
                              "initial_scaled": scores["standardized"]["accuracy"],
                              "raw": scores["raw_same_penalty"]["accuracy"],
                              "selected_step": payload["selected_step"]}), flush=True)
        except Exception as exc:
            rows.append({"name": bound["name"], "case": bound["case"], "status": "FAILED_EVALUATION",
                         "error": repr(exc), "traceback": traceback.format_exc()})
    result = {"status": "COMPLETED_MEASUREMENTS" if all(r["status"] == "EVALUATED" for r in rows) else "PARTIAL_OR_FAILED",
              "protocol_sha256": sha(protocol_path), "seal_sha256": sha(seal_path), "test_data_sha256": data_hash(test),
              "test_artifact_sha256": sha(out / "test_data.npz"), "test_generation_wall_s": data_time,
              "rows": rows, "total_wall_s": time.perf_counter() - start, "total_cpu_s": time.process_time() - cpu,
              "real_cross_user_gate": "BLOCKED_SYNTHETIC_DATA", "production_adoption": False,
              "test_not_used_for_selection": True}
    dump(out / "RESULT.json", result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("seal", "test"))
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--seal")
    parser.add_argument("--git-anchor")
    args = parser.parse_args()
    if args.action == "seal":
        seal(args.protocol, args.root, args.out, args.git_anchor)
    else:
        evaluate(args.protocol, args.root, args.seal, args.out)
