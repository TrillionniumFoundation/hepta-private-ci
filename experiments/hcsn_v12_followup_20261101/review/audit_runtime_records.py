"""Independent standard-library audit of V12 fresh Torch/NumPy dual traces.

No model runtime or numerical package is imported. This checks raw executed
trajectories, source/export/reference identities, and the declared tolerance;
actual neural forward replay is recorded separately.
"""

import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_gzip(path):
    with gzip.open(path, "rt") as stream:
        return json.load(stream)


def audit(root, bundle, validation):
    checks, failures, maxima = 0, [], {}

    def check(ok, label):
        nonlocal checks
        checks += 1
        if not ok and len(failures) < 30:
            failures.append(label)

    def close(label, left, right):
        if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
            check(len(left) == len(right), label + " shape")
            for a, b in zip(left, right):
                close(label, a, b)
            return
        check(isinstance(left, (int, float)) and isinstance(right, (int, float))
              and math.isfinite(left) and math.isfinite(right), label + " finite")
        difference = abs(left-right)
        maxima[label] = max(maxima.get(label, 0.), difference)
        check(difference <= 1e-12 + 1e-10*abs(right), label + " declared tolerance")

    manifest = json.loads((bundle / "MANIFEST.json").read_text())
    protocol = json.loads((bundle / "PROTOCOL.json").read_text())
    check((protocol["rtol"], protocol["atol"]) == (1e-10, 1e-12), "predeclared tolerance")
    for path, expected in manifest["source_sha256"].items():
        check(sha(root / path) == expected, "sealed current runtime source")
    for path, expected in manifest["artifact_sha256"].items():
        check(sha(bundle / path) == expected, "sealed export artifact")
    check(sha(bundle / "SOURCE_V10_FROZEN.json") == protocol["source_v10_freeze_sha256"], "copied original freeze identity")
    original = json.loads((bundle / "SOURCE_V10_FROZEN.json").read_text())
    model_ids = {(r["task"], r["family"], r["seed"]): r for r in original["models"]}
    check(len(model_ids) == len(original["models"]) == len(manifest["models"]) == 16, "complete 16 model identities")
    for item in manifest["models"]:
        before = model_ids[item["task"], item["family"], item["seed"]]
        check(item["source_pt_sha256"] == before["sha256"] and item["source_pt_path"] == before["path"], "export uses exact original selected checkpoint")
    for task in ("async_av", "av_binding"):
        head = json.loads((bundle / task / "head.json").read_text())
        check(sha(bundle / task / "head.npz") == head["source_checkpoint_sha256"], "exact common head checkpoint export")
    reference = read_gzip(validation / "FROZEN_REFERENCE.json.gz")
    check(reference["bundle_manifest_sha256"] == sha(bundle / "MANIFEST.json"), "fresh Torch reference bundle binding")
    references = {}
    for case in reference["cases"]:
        key = tuple(case[k] for k in ("task", "family", "seed", "index", "policy", "implementation"))
        check(key not in references, "unique frozen reference case")
        references[key] = case
    check(len(references) == 720, "complete frozen reference roster")
    seen, inventory, updates, candidates = set(), Counter(), 0, 0
    with gzip.open(validation / "TRACES.jsonl.gz", "rt") as stream:
        for record in map(json.loads, stream):
            item = record["model"]
            key = (item["task"], item["family"], item["seed"], record["index"], record["policy"], record["implementation"])
            check(key not in seen and key in references, "unique expected dual execution")
            seen.add(key)
            inventory[item["task"], item["family"], record["implementation"]] += 1
            actual, expected = record["numpy"], record["torch"]
            for field in ("output", "requested_observations", "observation_fee", "latency_fee", "deadline_penalty",
                          "timely_output", "output_elapsed_seconds", "source_window_updates", "serialized_output_sha256", "events"):
                check(actual[field] == expected[field], "same-platform exact executed " + field)
            check({k: expected[k] for k in references[key]["reference"]} == references[key]["reference"], "fresh frozen reference reproduces executed Torch record")
            check(len(actual["decisions"]) == len(expected["decisions"]), "same decision roster")
            for a, b in zip(actual["decisions"], expected["decisions"]):
                check(a["selected"] == b["selected"] and a.get("mode") == b.get("mode"), "exact selected actions including ties")
                if "plans" in b:
                    check([p["plan"] for p in a["plans"]] == [p["plan"] for p in b["plans"]], "same candidate roster")
                    close("stop_score", a["stop_score"], b["stop_score"])
                    for ap, bp in zip(a["plans"], b["plans"]):
                        for field in ("correctness", "score", "increment_over_stop"):
                            close("candidate_" + field, ap[field], bp[field])
                        candidates += 1
                    best = max(a["plans"], key=lambda p: (p["score"], p["plan"]), default=None)
                    selected = best["plan"] if best is not None and best["score"] > a["stop_score"] else None
                    check(selected == a["selected"], "NumPy strict STOP threshold and lexical ties")
            check(len(record["numpy_updates"]) == len(record["torch_updates"]), "same accepted update roster")
            for a, b in zip(record["numpy_updates"], record["torch_updates"]):
                for field in ("event_id", "row", "source_time", "global_source_increment", "content_fingerprint", "path_shape"):
                    check(a[field] == b[field], "exact accepted data/state interface " + field)
                close("hidden", a["hidden"], b["hidden"])
                close("path", a["path_probability"], b["path_probability"])
                updates += 1
    check(seen == set(references), "all 720 references executed")
    declared = json.loads((validation / "VALIDATION.json").read_text())
    check(declared["status"] == "passed" and declared["executions"] == len(seen) == 720, "producer validation agrees with raw complete roster")
    check(declared["per_forward_checks"]["whole_trajectory_hidden"] == updates, "declared whole-trajectory hidden count")
    check(declared["per_forward_checks"]["candidate_probability_score"] == candidates, "declared candidate-forward count")
    return {"schema": "hcsn-v12-independent-dual-runtime-raw-audit.v1", "checks": checks,
            "all_checks_passed": not failures, "failed_examples": failures, "executions": len(seen),
            "accepted_updates": updates, "candidate_values": candidates, "largest_absolute_errors": maxima,
            "inventory": {"/".join(key): value for key, value in inventory.items()},
            "scope": "Raw fresh dual-execution/source/export/reference consistency; numerical forward replay is a separate receipt"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root, args.bundle, args.validation)
    with args.out.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result))
    raise SystemExit(0 if result["all_checks_passed"] else 1)
