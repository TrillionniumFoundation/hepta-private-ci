"""Cross-language qualification under the explicit shared Q24 deployment profile.

The fixed vector sample precedes this evaluation. This checks native mathematics
and durable ingress only; it does not claim task benefit or native cell physics.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .client import NativeClient, canonical_digest
from .reference import NUMERIC_CONTRACT, infer, deployment_digest, quantization_error_bound


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prediction(checkpoint, raw, prior):
    weights = {k: np.asarray(v, float) for k, v in checkpoint["weights"].items()}
    x = np.clip((raw - checkpoint["norm"]["mean"]) / checkpoint["norm"]["scale"], -8., 8.)
    scores = prior + np.maximum(0., np.tanh(x @ weights["w"] + weights["b"]) @ weights["v"] + weights["c"])
    scores[0] = 0.
    return scores


def quantized(values):
    values = np.asarray(values, float)
    return np.sign(values) * np.floor(np.abs(values) * 2**24 + .5) / 2**24


def verify(binary, checkpoint_file, vectors_file, out):
    out.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    checkpoint = json.loads(checkpoint_file.read_text())
    fixture = json.loads(vectors_file.read_text())
    rows = fixture["rows"]
    if len(rows) != 512:
        raise ValueError("Qualification was declared for fixed next 512 rows")
    if not any(float(v) != 0 for line in checkpoint["weights"]["v"] for v in line):
        raise ValueError("Nonzero learned head is required for this numerical qualification")
    receipts, accounting, failures = [], [], []
    max_original, max_quantized, action_mismatches = 0., 0., []
    float_action_differences = []
    sequence, anchor = 0, "0"*64
    native_root = out/"native-owner"
    objective = canonical_digest({"qualification": "development-vectors", "model": sha(checkpoint_file)})
    for begin, end in ((0, 256), (256, 512)):
        with NativeClient(binary, checkpoint_file, native_root, "task.native.math.v2", objective,
                          sequence, anchor) as client:
            for index in range(begin, end):
                row = rows[index]
                raw, prior, mask = np.asarray(row["features"]), np.asarray(row["prior"]), np.asarray(row["feasible"], bool)
                if index == 128:
                    before = {p.name:sha(p) for p in native_root.glob("*.bin")}
                    bad = raw.copy()
                    bad[0] = 9.
                    try:
                        client.query(bad, prior, mask, canonical_digest({"cell": index}), canonical_digest(row))
                    except RuntimeError as error:
                        failures.append(dict(index=index, error=str(error),
                            durable_bytes_unchanged=before == {p.name:sha(p) for p in native_root.glob("*.bin")}))
                    else:
                        raise AssertionError("Out-of-envelope feature was accepted")
                receipt = client.query(raw, prior, mask, canonical_digest({"external_validation_row": index}),
                                       canonical_digest(row))
                observed = np.asarray(receipt["q_values"])
                exact = prediction(checkpoint, raw, prior)
                q24 = prediction(checkpoint, quantized(raw), quantized(prior))
                max_original = max(max_original, float(np.max(np.abs(observed[mask]-exact[mask]))))
                max_quantized = max(max_quantized, float(np.max(np.abs(observed[mask]-q24[mask]))))
                float_action = int(np.argmax(np.where(mask, exact, -np.inf)))
                action, shared_scores, drive = infer(checkpoint, raw, prior, mask)
                if float_action != receipt["action_index"]:
                    float_action_differences.append(dict(index=index+512, float_action=float_action,
                        native_action=receipt["action_index"],
                        original_score_gap=float(exact[float_action]-exact[receipt["action_index"]])))
                if action != receipt["action_index"]:
                    action_mismatches.append(dict(index=index, python_action=action,
                        native_action=receipt["action_index"], python_scores=exact.tolist(),
                        native_scores=observed.tolist()))
                receipts.append(dict(index=index, receipt=receipt))
            sequence, anchor = client.sequence, client.anchor
        accounting.append(client.accounting())
    accepted = (max_original <= 2e-6 and max_quantized <= 2e-12 and not action_mismatches
                and len(failures) == 1 and failures[0]["durable_bytes_unchanged"] and sequence == 512)
    summary = dict(schema="hepta.task.native-bridge.q24-profile-qualification.v1", accepted=accepted,
        sample_selection=fixture["selection"], evaluated_rows=len(rows),
        model_sha256=sha(checkpoint_file), model_selected_update=checkpoint["selected_update"],
        binary_sha256=sha(binary), vectors_sha256=sha(vectors_file),
        trained_head_nonzero=True, numeric_contract=NUMERIC_CONTRACT,
        deployment_identity_sha256=deployment_digest(sha(checkpoint_file)),
        quantization_error_bound=quantization_error_bound(checkpoint),
        original_float64_action_differences=float_action_differences,
        original_float64_action_equivalence_claim=False,
        maximum_original_float64_q_error=max_original,
        maximum_q24_reference_q_error=max_quantized, action_mismatches=action_mismatches,
        predeclared_tolerances=dict(original_q_absolute=2e-6, q24_reference_absolute=2e-12, action_mismatches=0),
        restart_after_acknowledged_sequence=256, final_sequence=sequence, injected_rejections=failures,
        process_accounting=accounting, total_wall_seconds=time.perf_counter()-started,
        parent_cpu_seconds=time.process_time()-cpu, native_physics_executed=False,
        task_utility_admission=False, production_activation=False,
        scope="Native and Python share explicit Q24 numeric deployment model; original float64 model is separately reported. Native MLP and journal/witness are real; feature/planner/cell producers remain external")
    with (out/"REPORT.json").open("x") as stream:
        json.dump(summary, stream, indent=2)
        stream.write("\n")
    with (out/"RECEIPTS.json.gz").open("xb") as stream:
        stream.write(gzip.compress(json.dumps(receipts, separators=(",", ":")).encode(), mtime=0))
    print(json.dumps(summary, indent=2))
    return accepted


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--vectors", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if verify(args.binary, args.checkpoint, args.vectors, args.out) else 1)
