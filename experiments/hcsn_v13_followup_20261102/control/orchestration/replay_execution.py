"""Actual new joint-state replay on predeclared TEST index0 in every model/policy.

Uses the sealed joint implementation, so this is fresh neural execution and
artifact binding, not a second independent implementation of the HX equations.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import torch

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))
from experiments.hcsn_v13_followup_20261102.joint_core.campaign import configure
from experiments.hcsn_v13_followup_20261102.control.value_fit import load
from experiments.hcsn_v13_followup_20261102.control.runtime import sha


def replay(run, out):
    source_sha = sha(Path(__file__))
    evaluation = run / "evaluation"
    summary = json.loads((evaluation / "SUMMARY.json").read_text())
    if summary["executions"] != 1944 or sha(evaluation / "TRACES.jsonl.gz") != summary["trace_sha256"]:
        raise RuntimeError("Complete frozen historical execution required")
    checks, maximum, cache, cases, steps = 0, {}, {}, [], 0

    def require(ok, label):
        nonlocal checks
        checks += 1
        if not bool(ok): raise AssertionError(label)

    def close(label, actual, expected):
        actual, expected = np.asarray(actual), np.asarray(expected)
        require(actual.shape == expected.shape, label + " shape")
        difference = float(abs(actual-expected).max()) if actual.size else 0.
        maximum[label] = max(maximum.get(label, 0.), difference)
        require(np.isfinite(actual).all() and np.allclose(actual, expected, rtol=0, atol=1e-15), label + " fixed tolerance")

    observed = set()
    with gzip.open(evaluation / "TRACES.jsonl.gz", "rt") as stream:
        for row in map(json.loads, stream):
            if row["index"] != 0: continue
            key = row["task"], row["family"], row["seed"]
            identity = (*key, row["policy"])
            require(identity not in observed, "unique predeclared neural replay")
            observed.add(identity)
            if key not in cache: cache[key] = load(run / f"fit-{key[0]}-{key[1]}-{key[2]}")
            model, norm, _, metadata = cache[key]
            state = model.initial(torch.zeros((1, 55), dtype=torch.float64))
            history = []
            probabilities = metadata["train_prior"]
            for saved in row["updates"]:
                normalized = np.asarray(norm.apply(np.asarray(saved["raw_row"])))
                close("normalized_actual_row", normalized, saved["model_row"])
                tensor = torch.as_tensor(normalized[None], dtype=torch.float64)
                with torch.no_grad():
                    state, event = model.step(tensor, state)
                    history.append(tensor)
                    probabilities = torch.softmax(model.classify(history, state), -1)[0].tolist()
                for index, value in enumerate(state): close("state_"+str(index), value.numpy(), saved["state"][index])
                for name, value in event.items(): require(value.tolist() == saved["event"][name], "actual reset/restoration")
                close("actual_prefix_probabilities", probabilities, saved["probabilities"])
                steps += 1
            execution = row["execution"]
            require(execution["output"]["head_id"] == metadata["head_id"], "new content checkpoint output identity")
            close("actual_final_probabilities", probabilities, execution["output"]["probabilities"])
            require(int(np.argmax(probabilities)) == execution["output"]["predicted_class"], "actual fresh final class")
            cases.append({"task": key[0], "family": key[1], "seed": key[2], "policy": row["policy"], "actual_updates": len(history)})
    expected = {(task, family, seed, policy) for task in ("async_av", "av_binding")
                for family in ("hx_full", "hx_margin", "ordinary_gate", "gru", "ssm", "history")
                for seed in (13301, 13303, 13307) for policy in ("fixed", "light", "value")}
    require(observed == expected and len(cases) == 108, "all model/policy predeclared index0 cases")
    require(sha(Path(__file__)) == source_sha, "replay source unchanged")
    result = {"schema": "hcsn-v13-actual-joint-execution-replay.v1", "checks": checks, "all_checks_passed": True,
              "cases": cases, "actual_joint_updates": steps, "largest_absolute_errors": maximum,
              "source_sha256_at_start": source_sha, "trace_sha256": summary["trace_sha256"],
              "candidate_remote_head": summary["remote_candidate_head"],
              "scope": "Predeclared index0, all36newcontentcheckpoints x3policy. Same-implementation actual state/classifier forward; no independent-kernel or new-cohort quality claim."}
    with out.open("x") as stream: json.dump(result, stream, indent=2); stream.write("\n")
    print(json.dumps({key: result[key] for key in ("checks", "all_checks_passed", "actual_joint_updates", "largest_absolute_errors")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True); parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); configure(); replay(args.run, args.out)
