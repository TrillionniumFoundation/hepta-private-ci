"""Verify learned-parameter parity and serving boundaries without held data."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from compact_router import CompactRouter
from native_router import FrozenRouter
from v5.contracts import canonical, unlabeled
from v5.corpus import build_public_corpus


def verify(run):
    selected = json.loads((run / "SELECTED.json").read_text())
    artifact = run / selected["candidate"] / "model.json"
    identity = selected["artifact"]["sha256"]
    reference = CompactRouter.load(artifact, identity)
    native = FrozenRouter(artifact, identity)
    folds, _ = build_public_corpus()
    requests = [unlabeled(row) for rows in folds.values() for row in rows]
    expected = reference.decisions(requests)
    actual = [native.decide(request) for request in requests]
    largest_error = 0.0
    for left, right in zip(expected, actual, strict=True):
        for key in ("raw_label", "accepted_intent", "accepted", "reason"):
            if left[key] != right[key]:
                raise AssertionError("stdlib serving differs from trained inference")
        largest_error = max(largest_error, max(abs(a - b) for a, b in zip(left["linear_scores"], right["linear_scores"], strict=True)))
    if largest_error > 1e-10:
        raise AssertionError("trained versus stdlib logits differ")
    base = {"utterance": "Give the mean of monthly quantity R17 over the three months ending at 2020-07.", "series_name": "monthly quantity R17", "date": "2020-07"}
    renamed = {"utterance": "Give the mean of arbitrary private metric over the three months ending at 1988-12.", "series_name": "arbitrary private metric", "date": "1988-12"}
    if native.decide(base) != native.decide(renamed):
        raise AssertionError("supplied slot identity leaked into prediction")
    bad = [{**base, "expected_operation": "at"}, {**base, "date": "2020-13"}, {**base, "utterance": "x" * 4097}, {**base, "series_name": ""}]
    for request in bad:
        try:
            native.decide(request)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid serving request accepted")
    try:
        FrozenRouter(artifact, "0" * 64)
    except ValueError:
        pass
    else:
        raise AssertionError("artifact identity was not enforced")
    selected_requests = requests[:12]
    command = [sys.executable, str(Path(__file__).with_name("native_router.py")), "--model", str(artifact.resolve()), "--sha256", identity]
    started = time.perf_counter()
    child = subprocess.run(command, input=b"\n".join(canonical(row) for row in selected_requests) + b"\n", stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=20)
    results = [json.loads(line) for line in child.stdout.splitlines()]
    if len(results) != len(selected_requests) or any(row["accepted_intent"] != native.decide(request)["accepted_intent"] for row, request in zip(results, selected_requests, strict=True)):
        raise AssertionError("fresh process serving failed")
    print(json.dumps({"schema": "memory-cell-v6.inference-verification.v1", "public_rows": len(requests),
        "prediction_parity": True, "max_logit_absolute_error": largest_error,
        "slot_invariance": True, "invalid_requests_rejected": len(bad), "hash_enforced": True,
        "fresh_process_rows": len(results), "fresh_process_wall_seconds": time.perf_counter() - started,
        "fresh_process_stderr": child.stderr.decode(), "held_rows_read": 0}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    verify(parser.parse_args().run)
