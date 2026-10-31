"""Separate loading/support accounting for the unchanged registered policies."""

import json
from pathlib import Path
import sys
import time

import numpy as np

from tools.hcsn.round8_20261031.value_calibration import finite
from tools.hcsn.round8_20261031.value_calibration.frozen import FrozenR7
from tools.hcsn.round8_20261031.value_calibration.head import CalibratedHead
from tools.hcsn.round8_20261031.value_calibration.run import checkpoint, digest, write
from ..head import CostFactoredHead, PreservedNominalHead
from ..protocol import MODES, SEEDS
from ..run import EVIDENCE, OLD, verify_registration


HERE = Path(__file__).resolve().parent
CONFIRMATION = EVIDENCE / "confirmation02"


def load_deployment(mode, seed, new):
    model = FrozenR7(checkpoint(mode, seed))
    old = CalibratedHead.load(OLD / f"{mode}_{seed}.json")
    if not new:
        return model, old
    head = CostFactoredHead.load(EVIDENCE / "heads" / f"{mode}_{seed}.json")
    support = json.loads((HERE / "SUPPORT.json").read_text())["public_inputs"]
    return model, PreservedNominalHead(old, head, support)


def memory(model, head):
    arrays = sum(v.nbytes for v in vars(model).values() if isinstance(v, np.ndarray))
    arrays += sum(v.nbytes for v in model.w.values())
    heads = (head.old, head.new) if isinstance(head, PreservedNominalHead) else (head,)
    arrays += sum(v.nbytes for h in heads for v in vars(h).values() if isinstance(v, np.ndarray))
    support_bytes = 0
    if isinstance(head, PreservedNominalHead):
        support_bytes = sys.getsizeof(head.support) + sum(sys.getsizeof(row) +
            sum(sys.getsizeof(v) for v in row) for row in head.support)
    return {"numpy_payload_bytes": arrays, "support_python_bytes": support_bytes,
            "scope": "Retained numerical arrays and exact Python support objects; allocator overhead and RSS excluded."}


def measure():
    verify_registration()
    assert (CONFIRMATION / "RESULTS.json").exists(), "measure only after immutable confirmation"
    protocol = {"schema": "hepta.r9.value.deployment-cost.v1", "repeats": 10,
        "source_sha256": digest(__file__), "heads_frozen_sha256": digest(EVIDENCE / "HEADS_FROZEN.json"),
        "confirmation_sha256": digest(CONFIRMATION / "RESULTS.json"),
        "scope": "Full model+old/new checkpoint read/parse/arrays and support JSON read+set construction, balanced paired order; warm filesystem possible",
        "new_support_preparation": "nominal input membership only, generated offline, no action labels",
        "per_episode_cost": "Registered PAIRED raw already includes full old/new head invocation and support lookup inside episode_run timer",
        "energy_measured": False, "does_not_replace_registered_gates": True}
    path = HERE / "PROTOCOL.json"
    with path.open("x") as stream:
        json.dump(protocol, stream, indent=2); stream.write("\n")
    cpu, wall = time.process_time(), time.perf_counter()
    graph = finite.build_graph(finite.configurations())
    support = sorted(set(tuple(row) for row in graph["x"]))
    write(HERE / "SUPPORT.json", {"public_inputs": support, "action_labels": False})
    preparation = {"cpu_seconds": time.process_time() - cpu,
                   "wall_seconds": time.perf_counter() - wall, "unique_inputs": len(support),
                   "sha256": digest(HERE / "SUPPORT.json")}
    raw, summary = [], []
    for mode in MODES:
        for seed in SEEDS:
            rows = []
            for repeat in range(protocol["repeats"]):
                pair = {}
                for new in ((False, True) if (repeat + seed) % 2 else (True, False)):
                    cpu, wall = time.process_time(), time.perf_counter()
                    model, head = load_deployment(mode, seed, new)
                    pair["r9" if new else "r8"] = {"cpu_seconds": time.process_time() - cpu,
                        "wall_seconds": time.perf_counter() - wall, "memory": memory(model, head)}
                row = {"mode": mode, "seed": seed, "repeat": repeat, "runs": pair}
                raw.append(row); rows.append(row)
            summary.append({"mode": mode, "seed": seed,
                "median_incremental_load_cpu_seconds": float(np.median([r["runs"]["r9"]["cpu_seconds"] - r["runs"]["r8"]["cpu_seconds"] for r in rows])),
                "r8_median_cpu_seconds": float(np.median([r["runs"]["r8"]["cpu_seconds"] for r in rows])),
                "r9_median_cpu_seconds": float(np.median([r["runs"]["r9"]["cpu_seconds"] for r in rows])),
                "memory": rows[-1]["runs"]["r9"]["memory"]})
    write(HERE / "RESULTS.json", {"protocol_sha256": digest(path), "preparation": preparation,
                                 "summary": summary, "raw": raw})
    print(json.dumps({"preparation": preparation, "summary": summary}), flush=True)


if __name__ == "__main__":
    measure()
