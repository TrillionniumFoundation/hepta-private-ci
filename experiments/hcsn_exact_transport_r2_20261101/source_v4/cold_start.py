"""Fresh-process first-use costs; no engineering or timing warmup precedes calls."""

import time
IMPORT_CPU, IMPORT_WALL = time.process_time(), time.perf_counter()

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

from . import adapter, audit


def run(kind, task, batch, condition, backward, out):
    torch.set_num_threads(1)
    if out.exists() or out.with_suffix(".npz").exists():
        raise FileExistsError("Refusing previous cold-use output")
    out.parent.mkdir(parents=True, exist_ok=True)
    imports = dict(cpu_seconds=time.process_time() - IMPORT_CPU, wall_seconds=time.perf_counter() - IMPORT_WALL)
    cpu, wall = time.process_time(), time.perf_counter()
    model = audit.model_for(task)
    arrays = audit.data.batch(task, batch, 972777, "dev", condition)
    x, dt, observed, labels = [torch.from_numpy(arrays[k]) for k in ("x", "dt", "observed", "y")]
    model_data_setup = dict(cpu_seconds=time.process_time() - cpu, wall_seconds=time.perf_counter() - wall)
    cpu, wall = time.process_time(), time.perf_counter()
    cache_empty = (adapter._SCRIPTED_JOINT is None and adapter._SCRIPTED_READ is None
                   and adapter._SCRIPTED_FEATURES is None)
    call = model if kind == "dense" else adapter.ExactAddressedAdapter(model, kind)
    construct = dict(cpu_seconds=time.process_time() - cpu, wall_seconds=time.perf_counter() - wall,
                     scripted_cache_empty_before_construction=cache_empty,
                     compiled_here=False if kind == "dense" else call.compiled_here)
    if kind != "dense" and (not cache_empty or not call.compiled_here):
        raise ValueError("Cold worker unexpectedly reused compiled code")
    rows, logits = [], []
    for index in range(4):
        model.zero_grad(set_to_none=True)
        cpu, wall = time.process_time(), time.perf_counter()
        with torch.set_grad_enabled(backward):
            output = call(x, dt, observed)
            if backward:
                F.cross_entropy(output.flatten(0, 1), labels.flatten()).backward()
        rows.append(dict(index=index, cpu_seconds=time.process_time() - cpu,
                         wall_seconds=time.perf_counter() - wall))
        logits.append(output.detach().numpy().copy())
    raw = out.with_suffix(".npz")
    np.savez_compressed(raw, logits=np.stack(logits), labels=arrays["y"])
    record = dict(schema="hcsn.exact-addressed-r2.cold-use.v1", kind=kind, task=task, batch=batch,
                  condition=condition, backward=backward, calls=rows, imports=imports,
                  model_data_setup=model_data_setup, construction=construct,
                  input_sha256={k: hashlib.sha256(arrays[k].tobytes()).hexdigest() for k in ("x", "dt", "observed", "y")},
                  checkpoint_sha256=audit.digest(audit.checkpoint(task)), raw_sha256=audit.digest(raw),
                  source_sha256={str(p.relative_to(audit.ROOT)): audit.digest(p) for p in
                                 [Path(__file__), Path(adapter.__file__), Path(audit.__file__)]},
                  scope="Four actual first-use calls in a fresh process; no warm-cache or free-compilation assumption")
    audit.write(out, record)
    print(json.dumps(dict(kind=kind, task=task, batch=batch, condition=condition, backward=backward,
                          constructor_wall=construct["wall_seconds"], first_call_wall=rows[0]["wall_seconds"])))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("dense", "separate_online"), required=True)
    parser.add_argument("--task", choices=("mqar", "binding"), required=True)
    parser.add_argument("--batch", type=int, required=True)
    parser.add_argument("--condition", required=True)
    parser.add_argument("--backward", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.kind, args.task, args.batch, args.condition, args.backward, args.out)
