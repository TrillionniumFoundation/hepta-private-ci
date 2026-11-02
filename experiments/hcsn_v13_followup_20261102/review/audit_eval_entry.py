"""Synthetic metrics and actual pre-evaluation rejection; no eval labels read."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import tempfile
from unittest.mock import patch

import numpy as np
import torch
from experiments.hcsn_v13_followup_20261102.joint_core.operations import evaluate_content as entry


def run(models, output):
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    checks, failed = 0, []

    def check(ok, label):
        nonlocal checks
        checks += 1
        if not ok:
            failed.append(label)

    sources = [Path(entry.__file__), Path(entry.__file__).with_name("publication_gate.py"),
               Path(entry.__file__).with_name("EVALUATION_PROTOCOL.json")]
    frozen = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    for classes in (2, 6):
        x = np.linspace(-.7, .9, 12*classes).reshape(2, 6, classes)
        x[0, 0] = 0.
        y = (np.arange(12).reshape(2, 6) % classes).astype(np.int64)
        p, correct, nll = entry.values(torch.tensor(x), torch.tensor(y))
        expected = np.zeros_like(x)
        expected_nll = np.zeros_like(y, dtype=float)
        for a in range(2):
            for t in range(6):
                z = x[a, t]
                logz = max(z)+math.log(math.fsum(math.exp(float(v-max(z))) for v in z))
                expected[a, t] = [math.exp(float(v-logz)) for v in z]
                expected_nll[a, t] = logz-z[y[a, t]]
        check(np.allclose(p, expected, rtol=1e-13, atol=1e-14), "independent synthetic class probabilities")
        check(np.array_equal(correct, x.argmax(-1) == y), "actual class argmax including uniform ties")
        check(np.allclose(nll, expected_nll, rtol=1e-13, atol=1e-14), "independent synthetic class NLL")
    with tempfile.TemporaryDirectory(dir=output) as directory:
        bad = Path(directory)/"publication.json"
        bad.write_text(json.dumps({"local_head": "0"*40, "remote_head": "1"*40,
                                  "all_stage_root_trees_exact": False, "base_remote": "2"*40}))
        with patch.object(entry, "dataset", side_effect=AssertionError("Evaluation data must remain unopened")) as loader:
            rejected = False
            try:
                entry.evaluate(models, Path(directory)/"never-evaluate", "2"*40, "1"*40, bad)
            except RuntimeError:
                rejected = True
            check(rejected and loader.call_count == 0, "actual invalid-publication rejection precedes any dataset read")
    check(all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in frozen.items()), "tested evaluation sources unchanged")
    result = {"checks": checks, "all_checks_passed": not failed, "failed_examples": failed,
              "source_sha256": frozen, "validation_or_test_loaded": False,
              "scope": "Synthetic metric arithmetic and actual negative publication gate only; no formal model evaluation"}
    (output/"RESULT.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result))
    return result["all_checks_passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if run(args.models, args.out) else 1)
