"""Compare a deterministic DIRECT fixed-point stop with its original full run.

Run with a single BLAS thread: python benchmark.py ARCHIVE OUTPUT.json.
The five sources and GEN graphs come from the frozen upstream evidence bundle.
"""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time
import zipfile

for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[var] = "1"

import numpy as np
from original.data_contract import canonical, exact_radius, head, model_with_head
from original.soft_value import Forest, optimize
from soft_value_stop import optimize as optimize_with_stop

HISTORIC = "evidence/value/run/generation_attempt001/output/generation/fit_{}.json"
PROTOCOL = "evidence/pocket/value_review/PROTOCOL_FROZEN.json"
PROTOCOL_SHA = "adca7eed0c7dc63a5d884fc44f8e8431d7dae56eb44d0566d522eb8dae405d10"
ARCHIVE_SHA = "78a64761286fd662eb50ec55eec1884448521a3453dfebaf39864211a8ff1300"
def sha(data):
    return hashlib.sha256(data).hexdigest()

def load_pinned(z, pin):
    data = z.read("evidence/value/input_bundle/" + pin["path"])
    assert len(data) == pin["bytes"] and sha(data) == pin["sha256"]
    return data

def exact_gate(anchor, candidate):
    if not exact_radius(anchor, candidate)["within_shared_ball"]:
        raise ValueError("encoded candidate exceeds radius")

def run(z, protocol, fit, round_id):
    spec = protocol["fits"][str(fit)]
    base = json.loads(gzip.decompress(load_pinned(z, spec["model"])))
    anchor = head(base)
    with np.load(io.BytesIO(load_pinned(z, spec["hidden"]))) as hidden:
        matrix = hidden["H"]
    items = []
    for slot in spec["graphs"]:
        graph = json.loads(gzip.decompress(load_pinned(z, slot["graph"])))
        rows = matrix[slot["row_start"]:slot["row_end"]]
        assert len(rows) == len(graph["states"])
        assert graph["state_order_sha256"] == slot["state_order_sha256"]
        items.append({"graph": graph, "H": rows})
    forest = Forest(items)
    settings = dict(protocol["optimization"], radius=exact_radius(anchor)["numeric_radius"])
    historical = json.loads(z.read(HISTORIC.format(fit)))["optimizer_reports"]["DIRECT"]
    assert historical["status"] == "COMPLETED"
    outputs = {}
    arms = [("full", optimize), ("stop", optimize_with_stop)]
    if (round_id + protocol["fit_ids"].index(fit)) % 2:
        arms.reverse()
    for name, implementation in arms:
        result, log = implementation(forest, anchor, "DIRECT", settings, exact_gate, lambda: None)
        if result is None or log["status"] != "COMPLETED":
            raise RuntimeError((fit, name, log["error"]))
        encoded = sha(canonical(model_with_head(base, result, "G")[0]).encode())
        outputs[name] = dict(counters=log["counters"], CPU_seconds=log["CPU_seconds"],
                             wall_seconds=log["wall_seconds"], canonical_model_sha256=encoded,
                             rounds=len(log["trace"]), stopped=log.get("fixed_point_stop",False),
                             objective=log["returned_best_objective"],
                             proposals=log["proposals"])
    a, b = outputs["full"], outputs["stop"]
    assert a["canonical_model_sha256"] == b["canonical_model_sha256"] == sha(canonical(base).encode())
    assert a["objective"] == b["objective"] and b["proposals"] == a["proposals"][:len(b["proposals"])]
    assert a["counters"] == historical["counters"]
    max_replay_drift = max(abs(x["objective"]-y["objective"]) for x,y in zip(a["proposals"],historical["proposals"], strict=True))
    assert max_replay_drift < 1e-12
    assert all((x["state"],x["dose"])==(y["state"],y["dose"]) for x,y in zip(a["proposals"],historical["proposals"],strict=True))
    keys = ("state","dose","candidate_norm","objective","world","utility","local_priority")
    block = [tuple(p[k] for k in keys) for p in b["proposals"]]
    assert [tuple(p[k] for k in keys) for p in a["proposals"]] == block * (len(a["proposals"])//len(block))
    for result in outputs.values():
        result["proposal_trace_sha256"] = sha(canonical(result.pop("proposals")).encode())
    return dict(fit=fit, repeat=round_id + 1, order=[a for a,_ in arms], results=outputs,
                source_gzip_sha256=spec["model"]["sha256"], max_historical_proposal_objective_difference=max_replay_drift,
                worlds=forest.worlds, states=len(forest.H))

def main():
    archive_path, target = map(Path, sys.argv[1:])
    with archive_path.open("rb") as src:
        assert hashlib.file_digest(src, "sha256").hexdigest() == ARCHIVE_SHA
    parent_cpu, wall = time.process_time(), time.monotonic()
    with zipfile.ZipFile(archive_path) as z:
        data = z.read(PROTOCOL)
        assert sha(data) == PROTOCOL_SHA
        protocol = json.loads(data)
        rows = [run(z, protocol, fit, repeat) for repeat in range(2) for fit in protocol["fit_ids"]]
    totals = {}
    for arm in ("full","stop"):
        current=[r["results"][arm] for r in rows]
        totals[arm] = {k:sum(item[k] for item in current) for k in ("CPU_seconds","wall_seconds")}
        totals[arm].update({k:sum(item["counters"][k] for item in current) for k in current[0]["counters"]})
    report=dict(protocol_sha256=PROTOCOL_SHA,archive_sha256=ARCHIVE_SHA, python=sys.version,
                numpy=np.__version__, scientific_scope="historical generation inputs; deterministic optimizer benchmark",
                paired_repeats=2, rows=rows, totals=totals, harness_CPU_seconds=time.process_time()-parent_cpu,
                harness_wall_seconds=time.monotonic()-wall)
    with target.open("x") as out:
        json.dump(report,out,indent=2,allow_nan=False)
    print(json.dumps(totals,indent=2))
if __name__ == "__main__":
    main()
