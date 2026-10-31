"""Check floating-point prediction identity without changing any AV metric."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np


RUN = 41158089224
SEAL = "6469cc94a72aed214c5c9d2ff2fba14cdb146626"
AUDITOR_SHA = "026e1e40a7d50c86145aaafb39c9ae1bb432c07462d9efc87f0abf70d91b8f41"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def identity(logits):
    scores = np.asarray(logits, np.float64)
    if scores.ndim != 2 or scores.shape[1] != 6 or not np.isfinite(scores).all():
        raise ValueError("Six finite logits per prediction are required")
    centered = scores - scores.max(axis=1, keepdims=True)
    exponential = np.exp(centered)
    normalizer = exponential.sum(axis=1)
    registered = exponential / normalizer[:, None]
    independent = np.exp(centered - np.log(normalizer)[:, None])
    edges = np.arange(11) / 10.
    bins = lambda probabilities: np.clip(np.searchsorted(edges, probabilities.max(axis=1), side="right") - 1, 0, 9)
    return dict(predictions=len(scores),
        raw_logit_vs_registered_probability_argmax_disagreements=int(np.count_nonzero(
            scores.argmax(axis=1) != registered.argmax(axis=1))),
        registered_vs_independent_confidence_bin_disagreements=int(np.count_nonzero(bins(registered) != bins(independent))),
        maximum_absolute_probability_difference=float(np.abs(registered - independent).max()))


def emit(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selfcheck", action="store_true")
    parser.add_argument("--run-receipt", type=Path)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--study", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Preserve every numerical-identity attempt")
    if args.selfcheck:
        tiny = identity(np.array([[0., 1e-30, 0., 0., 0., 0.]]))
        ordinary = identity(np.array([[0., 1., 0., -2., 3., .5], [0., 0., 0., 0., 0., 0.]]))
        assert tiny["raw_logit_vs_registered_probability_argmax_disagreements"] == 1
        assert ordinary["raw_logit_vs_registered_probability_argmax_disagreements"] == 0
        assert ordinary["registered_vs_independent_confidence_bin_disagreements"] == 0
        emit(args.output, dict(passed=True, synthetic_only=True, current_raw_predictions_read=False,
            source_sha256=sha(__file__), tiny_counterexample=tiny, ordinary=ordinary))
        return
    run = read(args.run_receipt)
    if (run.get("id") != RUN or run.get("head_sha") != SEAL or run.get("status") != "completed"
            or run.get("repository", {}).get("full_name") != "TrillionniumFoundation/hepta-private-ci"):
        raise PermissionError("Exact full-run completion is required before raw prediction access")
    audit = read(args.audit)
    if audit.get("audit_source_sha256") != AUDITOR_SHA or audit.get("valid_jobs") != 90:
        raise ValueError("The unchanged complete ninety-job audit is required")
    inputs = []
    for shard in audit["input_files_shards"]:
        if Path(shard["file"]).name != shard["file"]:
            raise ValueError("Unbounded audit shard path")
        path = args.audit.parent / shard["file"]
        if sha(path) != shard["sha256"] or path.stat().st_size != shard["bytes"]:
            raise ValueError("Audit fingerprint shard changed")
        rows = read(path)
        if len(rows) != shard["rows"]:
            raise ValueError("Audit fingerprint count changed")
        inputs.extend(rows)
    rows = []
    for entry in inputs:
        path = Path(entry["path"])
        try:
            relative = path.resolve().relative_to(args.study.resolve())
        except ValueError:
            continue
        if (len(relative.parts) != 3 or relative.parts[0] not in ("development", "fixed", "equal_cpu")
                or not (relative.name == "test.npz" or relative.name.startswith("validation_") and relative.suffix == ".npz")):
            continue
        if path.is_symlink() or sha(path) != entry["sha256"] or path.stat().st_size != entry["bytes"]:
            raise ValueError("An already-audited prediction file changed")
        with np.load(path, allow_pickle=False) as saved:
            channels = {channel: identity(saved[channel + "_logits"]) for channel in ("audio", "video", "fused")}
        rows.append(dict(file=relative.as_posix(), sha256=entry["sha256"], channels=channels))
    if not 220 <= len(rows) <= 260:
        raise ValueError("Incomplete prediction inventory for ninety complete workers")
    disagreements = sum(value["raw_logit_vs_registered_probability_argmax_disagreements"]
                        for row in rows for value in row["channels"].values())
    bin_disagreements = sum(value["registered_vs_independent_confidence_bin_disagreements"]
                           for row in rows for value in row["channels"].values())
    parts = []
    for number, start in enumerate(range(0, len(rows), 80)):
        path = args.output.with_name(args.output.stem + f"_files_{number:03d}.json")
        emit(path, rows[start:start + 80])
        parts.append(dict(file=path.name, rows=min(80, len(rows) - start), sha256=sha(path), bytes=path.stat().st_size))
    result = dict(schema="hcsn-av-floating-point-equivalence.v1", diagnostic_complete=True,
        source_sha256=sha(__file__), audit_sha256=sha(args.audit), completed_run_receipt_sha256=sha(args.run_receipt),
        files=len(rows), predictions_per_channel=sum(row["channels"]["fused"]["predictions"] for row in rows),
        raw_logit_vs_probability_argmax_disagreements=disagreements,
        confidence_bin_disagreements=bin_disagreements,
        identity_confirmed=disagreements == 0 and bin_disagreements == 0, files_shards=parts,
        scientific_gate_or_metric_changed=False, labels_or_quality_metrics_computed=False,
        scope="Numerical method equivalence on already-audited logits only. Frozen classification uses probability argmax; frozen actor matrices use raw-logit argmax. Preserve and explain any discrepancy; do not silently relabel scientific outcomes.",
        python=sys.version, numpy=np.__version__)
    emit(args.output, result)
    print(json.dumps({key: result[key] for key in ("diagnostic_complete", "identity_confirmed", "files",
        "raw_logit_vs_probability_argmax_disagreements", "confidence_bin_disagreements")}))


if __name__ == "__main__":
    main()
