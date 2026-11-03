"""Measured research-owner lifecycle after actual training has terminated."""

import argparse
import gc
import json
import os
from pathlib import Path
import resource
import sqlite3
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import torch

from owner import Owner
from runtime_contract import canonical, source_id
from tensor_cell import TensorCell


def run(model_root, database, features_path, encoder_sha):
    began, cpu = time.perf_counter(), time.process_time()
    torch.set_num_threads(1)
    with np.load(features_path, allow_pickle=False) as archive:
        features = {kind: archive[kind].copy() for kind in ("semantic", "skill")}
    cells = {kind: TensorCell.load(model_root / kind, encoder_sha) for kind in ("semantic", "skill")}
    owner = Owner(database, cells, features)
    events = []

    def observe(name, operation):
        reads = owner.reads.copy()
        start = time.perf_counter_ns()
        value = operation()
        events.append({"operation": name, "result": value, "wall_ns": time.perf_counter_ns()-start,
                       "reads_before": reads, "reads_after": owner.reads.copy(), "owner_source_cut": owner.identity()})
        return value

    observe("read_original", lambda: owner.memory("semantic", 0))
    # New write is source-authorized before either old/new parameter version is read.
    # Values are a write command, not injected into a parameter read request.
    observe("correct_source", lambda: owner.change({"kind": "semantic", "index": 0, "version": 1,
                                                     "source_id": source_id("semantic", 0, 1), "value": [5, 4, 15]}))
    stale = observe("reject_stale_parameters", lambda: owner.memory("semantic", 0))
    if stale["status"] != "stale_source":
        raise AssertionError("old parameter version remained admissible after correction")
    owner.cells["semantic"] = TensorCell.load(model_root / "semantic-corrected", encoder_sha)
    observe("read_corrected", lambda: owner.memory("semantic", 0))
    observe("read_retained", lambda: [owner.memory("semantic", i) for i in range(1, 8)])
    observe("revoke_source", lambda: owner.revoke("semantic", 1))
    previous = owner.reads.copy()
    revoked = observe("revoked_composition", lambda: owner.execute({"role": "compose", "entity": 1, "workflow": 0}))
    if revoked["status"] != "missing_or_stale_input" or owner.reads["model"] != previous["model"] or owner.reads["events"] != previous["events"]:
        raise AssertionError("revocation failed to stop dependent model/event reads")
    owner.cells["semantic"] = TensorCell.load(model_root / "semantic-rebuilt", encoder_sha)
    observe("read_rebuilt_retained", lambda: [owner.memory("semantic", i) for i in (0, 2, 3, 4, 5, 6, 7)])
    if source_id("semantic", 1) in owner.cells["semantic"].source_ids:
        raise AssertionError("deleted source entered clean rebuild provenance")
    expected = observe("before_sleep", lambda: owner.memory("semantic", 2))
    sleeping = observe("sleep_evict", lambda: owner.sleep("semantic"))
    gc.collect()
    if "semantic" in owner.cells:
        raise AssertionError("sleep kept a model reference in the owner cache")
    suspended = observe("read_sleeping", lambda: owner.memory("semantic", 2))
    if suspended["status"] != "cell_sleeping":
        raise AssertionError("sleep did not stop reads")
    wrong = TensorCell.load(model_root / "semantic-corrected", encoder_sha)
    try:
        owner.wake("semantic", wrong)
    except ValueError:
        events.append({"operation": "reject_wrong_wake", "rejected": True})
    else:
        raise AssertionError("wake accepted a different checkpoint version")
    del wrong
    start = time.perf_counter_ns()
    restored = TensorCell.load(model_root / "semantic-rebuilt", encoder_sha)
    wake_load_ns = time.perf_counter_ns()-start
    observe("wake", lambda: owner.wake("semantic", restored))
    after = observe("after_wake", lambda: owner.memory("semantic", 2))
    if expected != after or sleeping["parameter_sha256"] != restored.parameter_digest():
        raise AssertionError("sleep/wake changed parameter identity or result")
    budget = observe("bounded_execution", lambda: owner.execute({"role": "compose", "entity": 2, "workflow": 0}, max_steps=1))
    if budget["status"] not in ("budget_stop", "completed") or len(budget["trace"]) > 1:
        raise AssertionError("program ignored its execution budget")
    previous = owner.reads.copy()
    owner.stop()
    stopped = observe("stopped_execute", lambda: owner.execute({"role": "compose", "entity": 2, "workflow": 0}))
    stopped_read = observe("stopped_direct_read", lambda: owner.memory("semantic", 2))
    if stopped["status"] != "owner_stopped" or stopped_read["status"] != "owner_stopped" or owner.reads != previous:
        raise AssertionError("stopped owner performed further reads")
    owner.close()
    return {"schema": "hepta.memory.adapter-owner-lifecycle.v1", "pid": os.getpid(), "events": events,
            "passed": True, "native_runtime": False, "wake_load_wall_ns": wake_load_ns,
            "wall_seconds": time.perf_counter()-began, "cpu_seconds": time.process_time()-cpu,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "explicit_fact_value_reads": owner.reads["explicit_values"],
            "sleep_guarantee": "owner cache reference evicted; physical allocator RSS release not guaranteed"}


def main():
    parser = argparse.ArgumentParser()
    for name in ("model-root", "database", "features"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--encoder-sha", required=True)
    args = parser.parse_args()
    sys.stdout.buffer.write(canonical(run(args.model_root, args.database, args.features, args.encoder_sha))+b"\n")


if __name__ == "__main__":
    main()
