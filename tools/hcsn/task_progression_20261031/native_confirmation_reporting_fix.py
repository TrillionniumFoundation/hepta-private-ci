"""Prospective backend qualification of all five frozen nonzero policy models.

This does not select checkpoints or test a new task-utility hypothesis. Exactly
validation rows 512:1024 and the first 16 confirmation episodes of each split are
declared before any confirmation data exist. Native work executes the trained
MLP and durable action owner; content, planning and cell physics stay external.
"""
import argparse
import contextlib
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ..native_task_bridge_20261031.task_parity import run_one
from ..native_task_bridge_20261031.verify_profile import verify
from ..task_value_factorial_20261030.task import ContentAdapter


SEEDS = (73031, 73037, 73043, 73049, 73057)
SELECTION = "Prespecified validation rows 512:1024, and first 16 frozen confirmation episodes per split/seed; backend qualification only"


def unpack(path):
    return json.loads(gzip.decompress(Path(path).read_bytes()))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def comparable(row):
    traces = []
    for trace in row["traces"]:
        # Performance measurements are retained in raw rows and compared as
        # costs. Their numerical equality is not a task-semantics requirement.
        event = {k:v for k,v in trace["event"].items() if "seconds" not in k}
        if "decoded" in event:
            event["decoded"] = {k:v for k,v in event["decoded"].items() if "seconds" not in k}
        traces.append(dict(state=trace["state"], action=trace["action"], event=event,
            external_cell_snapshot_sha256=trace["external_cell_snapshot_sha256"],
            cell_interval=trace["cell_interval"]))
    return dict(score=row["score"], counts=row["counts"], elapsed=row["task_elapsed"],
                failure=row["failure"], cell=row["final_cell_snapshot"], traces=traces)


def qualify(prepared, confirmed, binary, out):
    out.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), time.process_time()
    protocol = json.loads((prepared/"PROTOCOL.json").read_text())
    confirmation = json.loads((confirmed/"CONFIRMATION.json").read_text())
    if tuple(protocol["seeds"]) != SEEDS:
        raise ValueError("Unregistered frozen model set")
    if confirmation["main_activation"] is not False:
        raise ValueError("Research-only upstream confirmation expected")
    root = Path(__file__).resolve().parents[1]
    cell_file = root/"task_value_factorial_20261030/evidence/preflight_01/models/seed1234.json.gz"
    cell_parameters = unpack(cell_file)["cellfits"]["analytic"]["parameters"]
    adapter = ContentAdapter()
    summaries = []
    for seed in SEEDS:
        directory = out/f"seed{seed}"
        directory.mkdir()
        seed_report = json.loads((prepared/f"seed{seed}/PREPARE_SEED.json").read_text())
        checkpoint = prepared/seed_report["models"]["nonzero"]["path"]
        if sha(checkpoint) != seed_report["models"]["nonzero"]["sha256"]:
            raise ValueError("Frozen checkpoint identity changed")
        teacher_data = unpack(prepared/f"seed{seed}/TEACHER_DATA.json.gz")
        vectors = dict(selection=SELECTION, rows=teacher_data["validation"]["rows"][512:1024])
        vector_path = directory/"VECTORS.json"
        vector_path.write_text(json.dumps(vectors, separators=(",", ":"))+"\n")
        with (directory/"NUMERIC_LOG.txt").open("x") as log, contextlib.redirect_stdout(log):
            numeric_passed = verify(binary, checkpoint, vector_path, directory/"numeric")
        pairs, rows = [], []
        rng = np.random.default_rng(seed*10000+5101)
        for split in ("test", "ood"):
            cohort_path = confirmed/f"seed{seed}/{split}_COHORT.json.gz"
            cohort = unpack(cohort_path)
            for index, session in enumerate(cohort["records"][:16]):
                results = {}
                for backend in rng.permutation(["python", "native"]):
                    backend = str(backend)
                    result = run_one(session, adapter, seed_report["confusion"], protocol, checkpoint,
                        cell_parameters, backend, binary, directory/"owners"/f"{split}_{index}_{backend}")
                    result.update(split=split, seed=seed)
                    rows.append(result)
                    results[backend] = result
                equal = comparable(results["python"]) == comparable(results["native"])
                pairs.append(dict(split=split, session_id=session["id"], equivalent=equal,
                    python_cpu_seconds=results["python"]["complete_cpu_seconds"],
                    native_cpu_seconds=results["native"]["complete_cpu_seconds"],
                    python_wall_seconds=results["python"]["wall_seconds"],
                    native_wall_seconds=results["native"]["wall_seconds"],
                    cohort_sha256=sha(cohort_path)))
        with (directory/"PAIRS.json.gz").open("xb") as stream:
            stream.write(gzip.compress(json.dumps(dict(pairs=pairs, rows=rows),
                                                 separators=(",", ":"), allow_nan=False).encode(), mtime=0))
        result = dict(seed=seed, model_sha256=sha(checkpoint), selected_update=seed_report["models"]["nonzero"]["update"],
            numeric_passed=numeric_passed, pairs=len(pairs), equivalent_pairs=sum(p["equivalent"] for p in pairs),
            actual_file_reads=sum(r["counts"]["packet_file_reads"] for r in rows),
            content_invocations=sum(r["counts"]["content_invocations"] for r in rows),
            restored_rollouts=sum(r["restored"] for r in rows),
            python_mean_cpu_seconds=float(np.mean([p["python_cpu_seconds"] for p in pairs])),
            native_mean_cpu_seconds=float(np.mean([p["native_cpu_seconds"] for p in pairs])),
            native_child_cpu_seconds=sum(r["native_child_cpu_seconds"] for r in rows),
            accepted=numeric_passed and all(p["equivalent"] for p in pairs))
        summaries.append(result)
        print(json.dumps(result), flush=True)
    report = dict(schema="hepta.task.progression.native-five-model-qualification.v1", selection=SELECTION,
        source_sha256=sha(__file__), binary_sha256=sha(binary), adapter_setup=adapter.setup,
        frozen_confirmation_sha256=sha(confirmed/"CONFIRMATION.json"),
        prepared_manifest_sha256=sha(prepared/"PREPARED_MANIFEST.json"),
        external_cell_parameters_sha256=hashlib.sha256(np.asarray(cell_parameters,dtype="<f8").tobytes()).hexdigest(),
        models=summaries, accepted=all(r["accepted"] for r in summaries),
        parent_cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall,
        native_physics_executed=False, main_activation=False,
        cost_scope="Actual lifecycle cost; native has durable journal/witness and process recovery. Python restores trusted snapshots. This is not an equal-durability language-performance benchmark or a hardware-energy measurement.",
        scope="Post-freeze five-model backend qualification on prespecified existing data; no checkpoint selection, task-benefit retuning, or arbitrary-crash external-effect settlement guarantee")
    (out/"REPORT.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    print(json.dumps(dict(accepted=report["accepted"], models=len(summaries))), flush=True)
    return report["accepted"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("prepared", "confirmed", "binary", "out"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if qualify(args.prepared, args.confirmed, args.binary, args.out) else 1)
