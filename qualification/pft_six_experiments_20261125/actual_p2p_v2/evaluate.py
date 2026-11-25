"""Read frozen peer candidates, then generate independent evaluation sources."""

import argparse
import json
from pathlib import Path
import re
import time
import zlib

from features import (CAPSULE_SHA, NODES, array_hash, coordinates, corpus, digest,
                      encode, extract, file_sha, load_model, np, source_identity, torch)
from prepare import verify_protocol, write_new


def scores(prediction, labels):
    return {"accuracy": float(np.mean((prediction > 0) == (labels > 0))),
            "mse": float(np.mean((prediction - labels) ** 2)), "count": len(labels)}


def apply_candidate(model, basis, candidate):
    weight = np.asarray(candidate[:-1]) / np.asarray(basis["scale"])
    bias = candidate[-1] - np.asarray(basis["mean"]) @ weight
    with torch.no_grad():
        model.readout.weight.copy_(torch.tensor(np.stack((-weight / 2, weight / 2))))
        model.readout.bias.copy_(torch.tensor([-bias / 2, bias / 2]))


def numerical_reference(result, directory, protocol):
    path = directory / "stats.json.zlib"
    if file_sha(path) != result["stats_sha256"]:
        raise ValueError("Persisted statistics differ from the peer result")
    stats = json.loads(zlib.decompress(path.read_bytes()))
    if stats["header"] != result["header"] or len(stats["messages"]) != 8:
        raise ValueError("Wrong aggregate")
    dimension = result["size"]
    gram, moment = np.zeros((dimension, dimension)), np.zeros(dimension)
    for message in sorted(stats["messages"], key=lambda row: row["id"]):
        gram += np.asarray(message["gram"])
        moment += np.asarray(message["moment"])
    ridge = protocol["objective"]["ridge"]
    started = time.perf_counter()
    action = np.linalg.solve(gram + ridge * np.eye(dimension), moment)
    seconds = time.perf_counter() - started
    actual = np.asarray(result["solution"]["action"])
    relative = float(np.linalg.norm(actual - action) / max(1., np.linalg.norm(action)))
    residual = float(np.linalg.norm((gram + ridge * np.eye(dimension)) @ actual - moment)
                     / max(1., np.linalg.norm(moment)))
    passed = (relative <= protocol["relative_central_tolerance"]
              and residual <= protocol["relative_normal_residual_tolerance"])
    return {"central_relative_action_error": relative, "relative_normal_residual": residual,
            "central_solve_wall_s": seconds, "passed": passed}


def main(args):
    started = time.perf_counter()
    protocol = verify_protocol(args.protocol)
    if file_sha(Path(__file__)) != protocol["evaluation_source_sha256"]:
        raise ValueError("Evaluator differs from the predeclared protocol")
    if not re.fullmatch("[0-9a-f]{40}", args.freeze_commit):
        raise ValueError("External candidate publication anchor is required")
    seal = json.loads(Path(args.seal).read_text())
    if seal["protocol_sha256"] != file_sha(args.protocol):
        raise ValueError("Candidate seal uses another protocol")
    expected = {(n, s) for n in protocol["widths"] for s in protocol["seeds"]}
    if {(r["width"], r["seed"]) for r in seal["rows"]} != expected or len(seal["rows"]) != len(expected):
        raise ValueError("Sealed roster differs from the predeclared experiment")
    root, output = Path(args.results).resolve(), Path(args.output)
    output.mkdir(exist_ok=False)
    bound = []
    for row in seal["rows"]:
        path = (root / row["result_relative_path"]).resolve()
        if not path.is_relative_to(root) or file_sha(path) != row["result_sha256"]:
            raise ValueError("Peer result changed after the external seal")
        result = json.loads(path.read_text())
        if digest(result["solution"]["candidate"]) != row["candidate_sha256"]:
            raise ValueError("Candidate changed")
        if result["seed"] != row["seed"] or not result["peer_same_candidate"]:
            raise ValueError("Missing agreed peer candidate")
        width, seed = row["width"], row["seed"]
        outer = json.loads((Path(args.basis) / f"basis_n{width}_s{seed}.json").read_text())
        basis, candidate = outer["basis"], np.asarray(result["solution"]["candidate"])
        header = result["header"]
        objective = digest([protocol["objective"], digest(source_identity()), CAPSULE_SHA])
        if (digest(basis) != outer["coordinates_sha256"] or header["coordinates"] != digest(basis)
                or header["parent"] != digest(basis["parent"]) or header["objective"] != objective):
            raise ValueError("Candidate is not in the frozen physical coordinates")
        parent, action = np.asarray(basis["parent"]), np.asarray(result["solution"]["action"])
        if (candidate.shape != (basis["dimension"],) or not np.isfinite(candidate).all()
                or not np.array_equal(parent + action, candidate)):
            raise ValueError("Candidate is not the recorded parent plus solved action")
        model, identity = load_model(args.capsule, width, seed)
        if identity != basis["physical_model"]:
            raise ValueError("Different physical model")
        reference = numerical_reference(result, path.parent, protocol)
        if not reference["passed"]:
            raise ValueError("Independent central numerical reference did not pass")
        bound.append((row, path, result, basis, model, identity, reference))
    write_new(output / "OPEN_RECEIPT.json", {"candidate_freeze_commit": args.freeze_commit,
              "anchor_scope": "GitHub publication independently verified by orchestrator",
              "candidate_seal_sha256": file_sha(args.seal), "test_not_previously_generated": True,
              "preflighted_candidates": len(bound), "protocol_sha256": file_sha(args.protocol)})
    rows = []
    for row, path, result, basis, model, identity, reference in bound:
        tick = time.perf_counter()
        width, seed = row["width"], row["seed"]
        if file_sha(path) != row["result_sha256"]:
            raise ValueError("Candidate result changed after common preflight")
        candidate = np.asarray(result["solution"]["candidate"])
        node_rows, largest_realization_error = [], 0.
        for node in NODES:
            batch = corpus("test", node, seed, 0, protocol["test_per_node"])
            initial, initial_report = extract(model, batch)
            design = coordinates(initial, basis)
            expected_prediction = design @ candidate
            apply_candidate(model, basis, candidate)
            after, report = extract(model, batch)
            prediction = np.asarray(report["model_logit_margin"])
            realization_error = float(np.max(np.abs(prediction - expected_prediction)))
            largest_realization_error = max(largest_realization_error, realization_error)
            if not np.array_equal(initial, after) or realization_error > protocol["head_realization_tolerance"]:
                raise ValueError("Readout installation changed physics or predictions")
            node_rows.append({"test_source": batch["source"],
                              "test_sha256": array_hash(batch["x"], batch["margin"], batch["y"]),
                              "parent": scores(design @ np.asarray(basis["parent"]), batch["y"]),
                              "candidate": scores(prediction, batch["y"]),
                              "initial_feature_wall_s": initial_report["wall_s"],
                              "candidate_forward_wall_s": report["wall_s"],
                              "mass_error": report["mass_error"], "mark_excess": report["mark_excess"]})
            np.savez_compressed(output / f"predictions_n{width}_s{seed}_{node}.npz",
                                prediction=prediction, target=batch["y"], expected=expected_prediction)
        saved = output / f"adopted_n{width}_s{seed}.pt"
        torch.save({"state_dict": model.state_dict(), "config": identity["config"],
                    "candidate_sha256": row["candidate_sha256"]}, saved)
        loaded = torch.load(saved, map_location="cpu", weights_only=True)
        cold, _ = load_model(args.capsule, width, seed)
        cold.load_state_dict(loaded["state_dict"])
        if any(not torch.equal(v, cold.state_dict()[k]) for k, v in model.state_dict().items()):
            raise ValueError("Cold full-model parameter reload differs")
        rows.append({"width": width, "seed": seed, "candidate_sha256": row["candidate_sha256"],
                     "reference": reference, "test": node_rows,
                     "readout_realization_max_abs_error": largest_realization_error,
                     "cold_full_parameter_reload_equal": True, "saved_model_sha256": file_sha(saved),
                     "saved_model_bytes": saved.stat().st_size, "wall_s": time.perf_counter() - tick})
        print(json.dumps({"width": width, "seed": seed, "central_passed": reference["passed"],
                          "accuracy": float(np.mean([v["candidate"]["accuracy"] for v in node_rows]))}), flush=True)
    write_new(output / "RESULT.json", {"rows": rows, "protocol_sha256": file_sha(args.protocol),
              "candidate_freeze_commit": args.freeze_commit, "total_wall_s": time.perf_counter() - started,
              "test_used_for_training_or_backward_boundary": False,
              "scope": "Two physical hosts; synthetic task; fixed real SmallHCSN physics; learned readout only",
              "real_cross_user_evidence": False, "native_daemon_adoption": False})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "capsule", "basis", "results", "seal", "freeze-commit", "output"):
        parser.add_argument("--" + name, required=True)
    main(parser.parse_args())
