"""Verify and use an already selected V13 release through its original owner.

This is a research SourceOwner adapter, not native Hepta adoption authority.
It performs no training, evaluation, publication or version selection. Invoke
the CLI in a fresh process to observe a cold load and next-task prediction.
"""

import argparse
from contextlib import contextmanager
import io
import os
from pathlib import Path
import sys
import threading
import time
import types

import numpy as np

from bounded_npz import inspect_npz
from closure_common import (
    ClosureError,
    ClosureLimits,
    REFERENCE_HASHES,
    canonical,
    digest_text,
    integer,
    object_keys,
    read_capped,
    reference,
    sha,
    strict_json,
    text,
)
from verify_closure import _verified_checkpoint


_IMPORT_LOCK = threading.RLock()


@contextmanager
def original_owner(root):
    adapter, _, _ = reference()
    path = Path(__file__).parent / "reference/lifecycle.py.source"
    raw = read_capped(path, 32768)
    if sha(raw) != REFERENCE_HASHES["lifecycle.py"]:
        raise ClosureError("Original SourceOwner changed")
    with _IMPORT_LOCK:
        previous = sys.modules.get("adapter")
        module = types.ModuleType("adapter")
        module.Adapter = adapter
        sys.modules["adapter"] = module
        try:
            namespace = {"__name__": "hepta_v13_selected_owner", "__file__": str(path)}
            exec(compile(raw, str(path), "exec"), namespace)
        finally:
            if previous is None:
                sys.modules.pop("adapter", None)
            else:
                sys.modules["adapter"] = previous
    owner = namespace["SourceOwner"](root)
    try:
        yield owner
    finally:
        owner.close()


def _bounded_predictions(model, features, limits):
    # The original adapter computes in float64. Bound the intermediate rank,
    # feature and class tensors as well as the input, including simultaneous
    # logits/exp/normalization arrays. This is a numeric workspace bound, not
    # a claim about total interpreter/BLAS/process resident memory.
    config = model.config
    row_bytes = 8 * (
        4 * config["input_dim"] + 2 * config["rank"] + 4 * config["num_classes"] + 8
    )
    rows = min(256, limits.max_array_bytes // row_bytes)
    if rows < 1:
        raise ClosureError("One prediction exceeds the numeric workspace bound")
    predictions = np.empty(len(features), dtype=np.int64)
    batches = 0
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        for start in range(0, len(features), rows):
            stop = min(start + rows, len(features))
            batch = np.ascontiguousarray(features[start:stop], dtype=np.float64)
            predicted = model.predict(batch)
            if (
                predicted.shape != (stop - start,)
                or not np.issubdtype(predicted.dtype, np.integer)
                or predicted.min() < 0
                or predicted.max() >= config["num_classes"]
            ):
                raise ClosureError("Invalid prediction output")
            predictions[start:stop] = predicted
            batches += 1
    return predictions.tolist(), {
        "batches": batches,
        "maximum_batch_rows": rows,
        "numeric_workspace_budget_bytes": limits.max_array_bytes,
        "estimated_peak_numeric_bytes_per_row": row_bytes,
    }


def selected_use(request):
    """Read exact current selection; a stale/withdrawn selection fails closed."""
    object_keys(
        request,
        {
            "backend_profile",
            "owner_root",
            "scope",
            "cell",
            "artifact",
            "epoch",
            "encoder_manifest",
            "encoder_root",
            "training_dataset",
            "data_id",
            "task_features",
            "task_id",
            "mode",
        },
        "selected-use request",
    )
    if request["backend_profile"] != "v13-residual-adapter":
        raise ClosureError("V13 content is not a JointGenerator learning closure")
    for key in ("scope", "cell", "task_id"):
        text(request[key], 1024, key)
    artifact = digest_text(request["artifact"], "selected artifact")
    epoch = integer(request["epoch"], 1, (1 << 63) - 1, "selection epoch")
    root = Path(request["owner_root"])
    database = root / "sources.sqlite"
    if root.is_symlink() or database.is_symlink() or not database.is_file():
        raise ClosureError("An existing original SourceOwner is required")
    started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
    limits = ClosureLimits()
    directory = root / "artifacts" / artifact
    if directory.is_symlink():
        raise ClosureError("Linked release is not accepted")
    manifest_path = directory / "manifest.json"
    raw_manifest = read_capped(manifest_path, limits.max_source_bytes)
    if sha(raw_manifest) != artifact:
        raise ClosureError("Selected release manifest changed")
    manifest = strict_json(raw_manifest)
    with original_owner(root) as owner:
        with owner.transaction():
            row = owner.db.execute(
                "SELECT * FROM releases WHERE scope=? AND cell=?",
                (request["scope"], request["cell"]),
            ).fetchone()
            if row is None or row["epoch"] != epoch or row["artifact"] != artifact:
                raise ClosureError("Current selected artifact or epoch differs")
            selection = dict(row)
        source_ids = [item["source_id"] for item in manifest["source_cut"]["records"]]
        cut, records = owner.snapshot(request["scope"], source_ids)
        receipt, model = _verified_checkpoint(
            directory / "model.npz",
            source_snapshot={"cut": cut, "records": records},
            encoder_manifest_path=request["encoder_manifest"],
            encoder_root=request["encoder_root"],
            dataset_npz_path=request["training_dataset"],
            expected_data_id=request["data_id"],
            release_manifest_path=manifest_path,
            mode=request["mode"],
        )
        if receipt["release"]["artifact_id"] != artifact:
            raise ClosureError("Verified release differs from the requested selection")
        task_raw = read_capped(request["task_features"], limits.max_dataset_bytes)
        headers, _ = inspect_npz(task_raw, {"X"}, limits)
        header = headers["X"]
        expected_width = receipt["context"]["config"]["input_dim"]
        if (
            len(header["shape"]) != 2
            or header["shape"][1] != expected_width
            or not 1 <= header["shape"][0] <= limits.max_examples
            or np.prod(header["shape"], dtype=object) > limits.max_dataset_elements
            or header["dtype"] not in (np.dtype("float32"), np.dtype("float64"))
        ):
            raise ClosureError("Unsupported bounded task features")
        with np.load(io.BytesIO(task_raw), allow_pickle=False) as data:
            features = data["X"]
        if not np.isfinite(features).all():
            raise ClosureError("Non-finite task features")
        # Reuse the exact model loaded from the verified bounded bytes. The
        # original owner's transaction is the selection/source barrier. Check
        # the expected release BEFORE any prediction, and keep this barrier
        # for every batch. Do not reopen the NPZ through the unbounded legacy
        # loader or run an intervening release before noticing an epoch change.
        with owner.transaction():
            row = owner.db.execute(
                "SELECT * FROM releases WHERE scope=? AND cell=?",
                (request["scope"], request["cell"]),
            ).fetchone()
            if row is None or row["epoch"] != epoch or row["artifact"] != artifact:
                raise ClosureError("Selection changed during content verification")
            if owner.cut(request["scope"], source_ids) != receipt["source"]["cut"]:
                raise ClosureError("Source changed during content verification")
            selection = dict(row)
            predictions, batching = _bounded_predictions(model, features, limits)
            result = {
                "predictions": predictions,
                "epoch": epoch,
                "artifact": artifact,
                "source_version": receipt["context"]["source_version"],
            }
    return {
        "schema": "hepta.cell-learning.v13.selected-use.v1",
        "authority": "DENY_ALL",
        "backend_profile": request["backend_profile"],
        "task_id": request["task_id"],
        "task_features_sha256": sha(task_raw),
        "worker_pid": os.getpid(),
        "verification_mode": receipt["verification_mode"],
        "synthetic": receipt["synthetic"],
        "binding": receipt["binding"],
        "checkpoint": receipt["checkpoint"],
        "content_receipt_sha256": sha(canonical(receipt)),
        "existing_selection": {
            "scope": selection["scope"],
            "cell": selection["cell"],
            "epoch": epoch,
            "artifact": artifact,
            "validation_sha256": sha(selection["validation"].encode()),
        },
        "result": result,
        "prediction_execution": batching,
        "live_source_frontier_checked": True,
        "inference_executed": True,
        "training_executed": False,
        "adoption_performed": False,
        "cost": {
            "wall_micros": (time.perf_counter_ns() - started) // 1000,
            "cpu_micros": (time.process_time_ns() - cpu_started) // 1000,
            "energy_microjoules": None,
            "includes_interpreter_startup": False,
            "includes_model_acquisition_or_training": False,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request")
    args = parser.parse_args()
    try:
        request = strict_json(read_capped(args.request, 65536))
        result = selected_use(request)
    except Exception as error:
        print(f"selected V13 use refused: {error}", file=sys.stderr)
        return 2
    print(canonical(result).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
