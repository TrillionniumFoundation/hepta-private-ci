"""Read only the exact original parent best bytes for the inherited C2 winner."""

import hashlib
import io
import json
import os
from pathlib import Path
import resource
import sys
import time


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False); stream.write("\n")


def checked(path, expected=None, cap=8 * 1024**2):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "missing or nonregular exact artifact: " + str(path))
    before = path.stat()
    require(0 < before.st_size <= cap, "empty or oversized artifact")
    data = path.read_bytes(); after = path.stat()
    require((before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns), "artifact changed during read")
    actual = {"path": str(path), "bytes": len(data), "sha256": sha(data)}
    if expected is not None:
        require(actual["sha256"] == expected, "exact artifact hash differs: " + str(path))
    return data, actual


def main(request_path):
    started, cpu = time.monotonic(), time.process_time()
    request = json.loads(request_path.read_text()); root = Path(request["output_root"])
    require(request["E_payload_or_label_access"] is False and len(request["models"]) == 1, "D-only fixed roster")
    limits = request["limits"]
    resource.setrlimit(resource.RLIMIT_AS, (limits["address_space_bytes"],) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (limits["cpu_seconds"],) * 2)
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    import numpy as np
    import torch
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    sources = []
    for path, expected in request["source_files"].items():
        try:
            _, actual = checked(path, expected)
            sources.append({**actual, "status": "MATCHED"})
        except Exception as error:
            sources.append({"path": path, "expected_sha256": expected, "status": "UNAVAILABLE_OR_CHANGED", "error": str(error)})
    write(root / "SOURCE_BYTES.json", sources)
    outputs = []
    for row in request["models"]:
        start = time.monotonic()
        result = {"name": row["name"], "expected": row, "model_construction_calls": 0,
                  "model_forward_calls": 0, "model_backward_calls": 0, "optimizer_operations": 0}
        try:
            checkpoint, ci = checked(row["checkpoint"]["path"], row["checkpoint"]["sha256"])
            logits, li = checked(row["D_logits"]["path"], row["D_logits"]["sha256"])
            report, ri = checked(row["report"]["path"], row["report"]["sha256"])
            state = torch.load(io.BytesIO(checkpoint), map_location="cpu", weights_only=True)
            d = torch.load(io.BytesIO(logits), map_location="cpu", weights_only=True)
            require(state["model_configuration"] == row["model_configuration"], "checkpoint config differs")
            require(state["data_manifest_sha256"] == request["data_manifest_sha256"], "D manifest binding")
            require(state["epochs_completed"] == row["selected_epoch"], "selected strict-best epoch")
            tensors = []
            for name, tensor in sorted(state["model"].items()):
                value = tensor.detach().contiguous().numpy()
                require(np.isfinite(value).all(), "finite saved model tensor")
                tensors.append({"name": name, "shape": list(value.shape), "dtype": str(value.dtype),
                                "bytes": value.nbytes, "sha256": sha(value.tobytes())})
            z, y = d["logits"].numpy(), d["labels"].numpy()
            require(z.shape == (31952, 11) and y.shape == (31952,) and np.isfinite(z).all(), "complete finite D logits")
            require(y.dtype.kind in "iu" and ((y >= 0) & (y < 11)).all(), "D class labels")
            ids = d["episode_ids"]
            require(len(ids) == len(set(ids)) and len(ids) > 0 and all(s.startswith("D") for s in ids), "D-only unique episode order")
            matrix = np.bincount(11 * y + z.argmax(1), minlength=121).reshape(11, 11)
            den = matrix.sum(1) + matrix.sum(0)
            f1 = float(np.divide(2 * matrix.diagonal(), den, out=np.zeros(11), where=den != 0).mean())
            require(abs(f1 - row["D_macro_f1"]) <= 1e-12, "saved D macro-F1 differs")
            r = json.loads(report)
            result.update(status="MATCHED", checkpoint=ci, D_logits=li, report=ri,
                checkpoint_schema_keys=sorted(state), saved_model_tensors=tensors,
                model_tensor_manifest_sha256=sha(canonical(tensors)),
                configuration_canonical_sha256=sha(canonical(state["model_configuration"])),
                saved_epoch=state["epochs_completed"], saved_main_updates=state["main_updates"],
                D_logits_shape=list(z.shape), D_logits_dtype=str(z.dtype), D_labels_dtype=str(y.dtype),
                D_episode_order_sha256=sha(canonical(ids)), D_label_array_sha256=sha(y.tobytes()),
                D_logits_array_sha256=sha(z.tobytes()), D_macro_f1_recomputed=f1,
                D_macro_f1_absolute_difference=abs(f1 - row["D_macro_f1"]),
                producer_runtime_fields={k: r[k] for k in ["runtime", "python", "numpy", "torch", "torch_git", "device", "dtype"] if k in r},
                raw_runtime_field_absence_is_not_imputed=True)
            for path, expected in [(ci["path"], ci["sha256"]), (li["path"], li["sha256"]), (ri["path"], ri["sha256"])]:
                checked(path, expected)
        except Exception as error:
            result.update(status="MISSING_OR_INCONSISTENT", error_type=type(error).__name__, error=str(error))
        result["body_wall_seconds"] = time.monotonic() - start
        target = root / (row["name"] + ".json"); write(target, result)
        outputs.append({"name": row["name"], "status": result["status"], "file": str(target),
                        "bytes": target.stat().st_size, "sha256": sha(target.read_bytes())})
        require(time.monotonic() - started < limits["wall_seconds"] - 10, "postprocessing deadline")
    failures = [r for r in outputs if r["status"] != "MATCHED"]
    source_failures = [r for r in sources if r["status"] != "MATCHED"]
    index = {"schema": "hcsn-D-only-actual-artifact-inventory-v1", "outputs": outputs,
        "selection_sha256": request["selection_sha256"], "request_sha256": sha(request_path.read_bytes()),
        "source_sha256": sha(Path(__file__).read_bytes()), "source_bytes_record_sha256": sha((root / "SOURCE_BYTES.json").read_bytes()),
        "matched_models": len(outputs) - len(failures), "source_matched": len(sources) - len(source_failures),
        "source_total": len(sources), "status": "COMPLETE" if not failures and not source_failures else "INVENTORIED_WITH_GAPS",
        "reader_runtime": {"python": sys.version, "torch": torch.__version__, "numpy": np.__version__, "executable": sys.executable},
        "cost_scope": "Main entry including NumPy/Torch imports; native process startup and orchestration not fully measured.",
        "body_wall_seconds": time.monotonic() - started, "body_cpu_seconds": time.process_time() - cpu,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, "E_access": False,
        "model_construction_calls": 0, "model_forward_calls": 0, "model_backward_calls": 0, "optimizer_operations": 0}
    write(root / "INVENTORY.json", index)
    print(json.dumps({k: v for k, v in index.items() if k != "outputs"}), flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
