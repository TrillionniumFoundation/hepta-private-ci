"""Recompute restored finite-model certificates without changing frozen fits.

The original preparation and confirmation are immutable. This additional audit
does not train, choose a policy, alter a budget, or replace original CPU timings.
"""

import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
import scipy

from .. import finite
from ..frozen import FrozenR7
from ..head import CalibratedHead
from ..run import REPO, checkpoint, digest, metrics, source_manifest, write


def verify():
    started, cpu = time.perf_counter(), time.process_time()
    root = Path(__file__).resolve().parents[1]
    evidence = root / "evidence"
    prepared = evidence / "prepared02"
    freeze = json.loads((prepared / "FREEZE.json").read_text())
    if freeze["source"] != source_manifest():
        raise ValueError("restored source differs from immutable freeze")
    for relative, sha in freeze["upstream_checkpoints"].items():
        if digest(REPO / relative) != sha:
            raise ValueError("upstream checkpoint bytes differ: " + relative)
    for relative, sha in freeze["files"].items():
        if digest(prepared / relative) != sha:
            raise ValueError("prepared bytes differ: " + relative)
    manifest = json.loads((evidence / "EVIDENCE_MANIFEST.json").read_text())
    for relative, sha in manifest["files"].items():
        if digest(evidence / relative) != sha:
            raise ValueError("restored evidence differs: " + relative)
    graph = finite.build_graph(finite.configurations())
    independent = finite.build_graph(finite.configurations(), independent=True)
    alignment = np.asarray([independent["ids"][s] for s in graph["states"]])
    preparation = json.loads((prepared / "PREPARE.json").read_text())
    records = []
    for record in preparation["fits"]:
        mode, seed = record["mode"], record["seed"]
        model = FrozenR7(checkpoint(mode, seed))
        matrix, events = model.kernels(graph["x"])
        target, optimum = finite.targets(graph, matrix, events)
        head = CalibratedHead.load(prepared / record["head_file"])
        before, after = model.old_q(graph["x"]), head.predict(model.inputs(graph["x"]), target[:, :, 3])
        before_metrics, old_actions = metrics(before, target, graph)
        after_metrics, new_actions = metrics(after, target, graph)
        _, old_values = finite.targets(graph, matrix, events, old_actions)
        _, new_values = finite.targets(graph, matrix, events, new_actions)
        imatrix, ievents = model.kernels(independent["x"])
        i_actions = np.empty_like(new_actions)
        i_actions[alignment] = new_actions
        independent_optimum = finite.reference(independent, imatrix, ievents)[alignment]
        independent_new = finite.reference(independent, imatrix, ievents, i_actions)[alignment]
        oracle_error = max(float(np.max(abs(independent_optimum - optimum))),
            float(np.max(abs(independent_new - new_values))))
        current = {"target_q": target, "old_q": before, "new_q": after,
            "old_actions": old_actions, "new_actions": new_actions,
            "old_value": old_values, "new_value": new_values, "optimal_value": optimum}
        errors = {}
        with np.load(prepared / f"{mode}_{seed}_tables.npz", allow_pickle=False) as archived:
            for key, value in current.items():
                saved = archived[key]
                if not np.array_equal(np.isfinite(value), np.isfinite(saved)):
                    raise AssertionError("finite/legal support changed: " + key)
                mask = np.isfinite(value)
                errors[key] = float(np.max(abs(value[mask] - saved[mask])))
        metrics_error = max(abs(v - record[k][name]) for k, row in
            (("before", before_metrics), ("after", after_metrics)) for name, v in row.items())
        if oracle_error > 1e-10 or max(errors.values()) > 1e-10 or metrics_error > 1e-10:
            raise AssertionError((mode, seed, oracle_error, errors, metrics_error))
        records.append({"mode": mode, "seed": seed, "table_max_errors": errors,
            "independent_optimum_and_policy_error": oracle_error,
            "published_metrics_max_error": metrics_error,
            "before": before_metrics, "after": after_metrics,
            "old_exact_mean": float(old_values[graph["starts"], model.n // 2].mean()),
            "new_exact_mean": float(new_values[graph["starts"], model.n // 2].mean())})
    report = {"schema": "hepta.round8.value-recovery-verification.v1", "passed": True,
        "immutable_freeze_commit": "3a0e62c61b595576f16313c9b6016ec62cf8088b",
        "freeze_sha256": digest(prepared / "FREEZE.json"),
        "restored_evidence_manifest_sha256": digest(evidence / "EVIDENCE_MANIFEST.json"),
        "restored_original_evidence_files": len(manifest["files"]),
        "restored_original_evidence_bytes": sum((evidence / p).stat().st_size for p in manifest["files"]),
        "source_matches_frozen": True, "fits_recomputed": len(records),
        "public_states": len(graph["states"]), "records": records,
        "verification_source_sha256": digest(Path(__file__)),
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__},
        "cpu_seconds": time.process_time() - cpu, "wall_seconds": time.perf_counter() - started,
        "cost_scope": "This recovery audit only; excludes imports/final serialization; original deployment timings preserved.",
        "training_repeated": False, "production_activation": False}
    write(evidence / "RECOVERY_FINITE_VERIFICATION_20261031.json", report)
    print(json.dumps({k: report[k] for k in ("passed", "fits_recomputed", "public_states", "cpu_seconds")}), flush=True)


if __name__ == "__main__":
    verify()
