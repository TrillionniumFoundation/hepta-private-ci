"""Pure-standard-library post-exit verifier, outside measured model cgroups."""

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RTOL, ATOL = 1e-10, 1e-12


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(bundle, run, reference_path, output):
    manifest = json.loads((bundle / "MANIFEST.json").read_text())
    ci = json.loads((bundle / "CI_MANIFEST.json").read_text())
    if (ci["base_manifest_sha256"] != sha(bundle / "MANIFEST.json") or ci["models"] != manifest["models"]
            or ci["source_sha256"] != manifest["source_sha256"]):
        raise ValueError("CI reference seal belongs to a different runtime capsule")
    for relative, expected in manifest["source_sha256"].items():
        if sha(ROOT / relative) != expected:
            raise ValueError("Frozen runtime source changed: " + relative)
    for relative, expected in ci["artifact_sha256"].items():
        path = (bundle / relative).resolve()
        if not path.is_relative_to(bundle.resolve()) or sha(path) != expected:
            raise ValueError("Frozen artifact changed: " + relative)
    if sha(reference_path) != ci["reference_sha256"]:
        raise ValueError("Frozen reference bytes changed")
    with gzip.open(reference_path, "rt") as stream:
        references = json.load(stream)
    if references["bundle_manifest_sha256"] != sha(bundle / "MANIFEST.json"):
        raise ValueError("Reference belongs to a different frozen bundle")
    if (references["rtol"], references["atol"]) != (RTOL, ATOL):
        raise ValueError("Frozen numeric tolerance differs")
    summary = json.loads((run / "SUMMARY.json").read_text())
    if summary["torch_imported"] is not False:
        raise ValueError("Measured model worker imported Torch")
    item, implementation = summary["model"], summary["implementation"]
    if item not in manifest["models"]:
        raise ValueError("Task model is not in frozen bundle")
    selected_references = [r for r in references["cases"]
        if (r["task"], r["family"], r["seed"], r["implementation"]) ==
           (item["task"], item["family"], item["seed"], implementation)]
    expected_cases = {(r["index"], r["policy"]): r["reference"] for r in selected_references}
    expected_correct = {(r["index"], r["policy"]): r["correct"] for r in selected_references}
    if len(expected_cases) != len(selected_references):
        raise ValueError("Frozen reference has duplicate case identities")
    if not expected_cases:
        raise ValueError("No frozen reference cases for this worker")
    checks, maximum = 0, 0.0

    def close(a, b):
        nonlocal checks, maximum
        if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
            if len(a) != len(b):
                raise AssertionError("Numeric roster differs")
            for x, y in zip(a, b, strict=True):
                close(x, y)
        else:
            if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or not math.isfinite(a) or not math.isfinite(b):
                raise AssertionError("Invalid numeric value")
            difference = abs(a - b); maximum = max(maximum, difference); checks += 1
            if difference > ATOL + RTOL * abs(b):
                raise AssertionError("Frozen numeric tolerance exceeded")

    seen = set()
    with gzip.open(run / "TRACES.jsonl.gz", "rt") as stream:
        for line in stream:
            actual = json.loads(line)
            key = actual["index"], actual["policy"]
            if key in seen or key not in expected_cases:
                raise AssertionError("Duplicate or unexpected actual case")
            seen.add(key); expected = expected_cases[key]; result = actual["execution"]
            if actual["correct"] != expected_correct[key]:
                raise AssertionError("Actual task correctness differs from frozen Torch reference")
            if actual["output"] != result["output"] or actual["requests"] != result["requested_observations"]:
                raise AssertionError("Worker summary row differs from actual execution")
            for field in ("requested_observations", "observation_fee", "latency_fee", "deadline_penalty",
                          "source_window_updates", "timely_output", "output_elapsed_seconds"):
                if result[field] != expected[field]:
                    raise AssertionError("Actual action, source clock or fees differ: " + field)
                checks += 1
            for field, expected_value in expected["output"].items():
                if field == "probabilities":
                    close(result["output"][field], expected_value)
                elif result["output"][field] != expected_value:
                    raise AssertionError("Actual frozen class/output identity differs: " + field)
            serialized = (json.dumps(result["output"], sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
            if hashlib.sha256(serialized).hexdigest() != result["serialized_output_sha256"]:
                raise AssertionError("Actual serialized output digest is invalid")
            if result["events"] != expected["events"]:
                raise AssertionError("Actual accepted/paid action sequence differs")
            if len(result["decisions"]) != len(expected["decisions"]):
                raise AssertionError("Actual decision count differs")
            for a, b in zip(result["decisions"], expected["decisions"], strict=True):
                if a["selected"] != b["selected"] or a.get("mode") != b.get("mode"):
                    raise AssertionError("Actual selected plan differs")
                if "plans" in b:
                    close(a["stop_score"], b["stop_score"])
                    if [p["plan"] for p in a["plans"]] != [p["plan"] for p in b["plans"]]:
                        raise AssertionError("Actual candidate roster differs")
                    for ap, bp in zip(a["plans"], b["plans"], strict=True):
                        for field in bp:
                            if field in ("correctness", "score", "increment_over_stop"):
                                close(ap[field], bp[field])
                            elif ap[field] != bp[field]:
                                raise AssertionError("Actual candidate service/fee differs")
    if seen != set(expected_cases) or summary["executions"] != len(seen) or len(summary["rows"]) != len(seen):
        raise AssertionError("Model worker omitted a frozen case")
    payload = {"status": "passed", "model": item, "implementation": implementation,
        "executions": len(seen), "checks": checks, "maximum_numeric_difference": maximum,
        "rtol": RTOL, "atol": ATOL, "actions_classes_requests_fees_exact": True,
        "bundle_manifest_sha256": sha(bundle / "MANIFEST.json"), "reference_sha256": sha(reference_path),
        "ci_manifest_sha256": sha(bundle / "CI_MANIFEST.json"),
        "verifier_source_sha256": sha(__file__), "worker_trace_sha256": sha(run / "TRACES.jsonl.gz"),
        "scope": "Post-exit standard-library correctness audit, outside measured model worker"}
    with output.open("x") as stream:
        json.dump(payload, stream, indent=2, allow_nan=False); stream.write("\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    reference_path = args.reference or args.bundle / "FROZEN_REFERENCE.json.gz"
    verify(args.bundle, args.run, reference_path, args.out)
