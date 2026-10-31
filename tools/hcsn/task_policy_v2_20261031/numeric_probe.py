"""Fixed development-data comparison of float64 and the shared Q24 contract.

No fitting, checkpoint selection, new cohorts or new calibration occur here.
Both profiles execute real owners on the same previously retained packet files.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ..native_task_bridge_20261031 import reference
from ..task_value_factorial_20261030.task import ContentAdapter
from .execution import FLOAT64_CONTRACT, diagnose, rollout, source_hashes
from .training import predictions


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def states_comparison(data, checkpoint):
    rows = data["validation"]["rows"]
    mask = np.asarray([r["feasible"] for r in rows], bool)
    prior = np.asarray([r["prior"] for r in rows])
    teacher = np.asarray([r["teacher"] for r in rows])
    raw = np.asarray([r["features"] for r in rows])
    weights = {k:np.asarray(v, float) for k,v in checkpoint["weights"].items()}
    model = dict(checkpoint, weights=weights)
    x = np.clip((raw-checkpoint["norm"]["mean"])/checkpoint["norm"]["scale"], -8., 8.)
    tables = dict(exact_teacher=np.where(mask, teacher, -np.inf),
                  one_read=np.where(mask, prior, -np.inf), residual=predictions(weights, x, prior, mask))
    result, summaries = {}, {}
    for policy, scores in tables.items():
        details = []
        for index, row in enumerate(rows):
            if policy == "residual":
                action, q, drive = reference.infer(model, raw[index], prior[index], mask[index])
            else:
                q = scores[index]
                action, drive = reference.select_action(q, mask[index])
            original = int(np.argmax(scores[index]))
            maximum = float(np.max(teacher[index][mask[index]]))
            details.append(dict(index=index, float_action=original, q24_action=action, drive=drive.tolist(),
                float_regret=maximum-float(teacher[index,original]), q24_regret=maximum-float(teacher[index,action]),
                score_error=float(np.max(np.abs(q[mask[index]]-scores[index][mask[index]])))))
        result[policy] = details
        summaries[policy] = dict(states=len(details), action_changes=sum(r["float_action"] != r["q24_action"] for r in details),
            float_regret=float(np.mean([r["float_regret"] for r in details])),
            q24_regret=float(np.mean([r["q24_regret"] for r in details])),
            maximum_score_error=max(r["score_error"] for r in details),
            maximum_regret_increase=max(r["q24_regret"]-r["float_regret"] for r in details))
    return dict(rows=result, summaries=summaries)


def run(out, checkpoint_path, data_path, probe_path):
    out.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), time.process_time()
    checkpoint = json.loads(checkpoint_path.read_text())
    data = json.loads(gzip.decompress(data_path.read_bytes()))
    prior = json.loads(gzip.decompress(probe_path.read_bytes()))
    fixed_states = states_comparison(data, checkpoint)
    adapter = ContentAdapter()
    confusion = np.asarray(prior["calibration"]["confusion"], float)
    protocol, rows, diagnoses, summaries = prior["protocol"], [], {}, {}
    order = np.random.default_rng(720310903)
    variants = [(p,n) for p in ("exact_teacher", "one_read", "residual")
                for n in (FLOAT64_CONTRACT, reference.NUMERIC_CONTRACT)]
    for distribution, cohort in prior["cohorts"].items():
        current = []
        for session in cohort["records"]:
            for variant in order.permutation(len(variants)):
                policy, numeric_contract = variants[variant]
                row = rollout(session, adapter, confusion, protocol["multiplier"], protocol["latency_price"],
                              policy, checkpoint, numeric_contract=numeric_contract)
                row["development_distribution"] = distribution
                rows.append(row)
                current.append(row)
        meta = {s["id"]:json.loads((Path(s["folder"])/"public.json").read_text()) for s in cohort["records"]}
        diagnosis = diagnose(current, meta, confusion, protocol["multiplier"], protocol["latency_price"])
        for record, regret in zip(current, diagnosis["rows"]):
            regret["numeric_contract"] = record["numeric_contract"]
        diagnoses[distribution] = diagnosis
        summaries[distribution] = {}
        for policy, numeric_contract in variants:
            group = [r for r in current if (r["policy"],r["numeric_contract"]) == (policy,numeric_contract)]
            regrets = [r["cumulative_regret"] for r in diagnosis["rows"]
                       if (r["policy"],r["numeric_contract"]) == (policy,numeric_contract)]
            summaries[distribution][policy+"/"+numeric_contract] = dict(sessions=len(group),
                utility=float(np.mean([r["score"]["utility"] for r in group])),
                completed=float(np.mean([r["score"]["completed_jobs"] for r in group])),
                teacher_regret=float(np.mean(regrets)),
                controller_cpu_seconds=float(np.mean([r["controller_cpu_seconds"] for r in group])),
                cpu_seconds=float(np.mean([r["cpu_seconds"] for r in group])))
    result = dict(scope="Fixed previous development inputs; numeric profile verification, not new confirmation or model selection",
        source_hashes=source_hashes(), numeric_profile_source_sha256=digest(Path(reference.__file__)),
        inputs={str(p):digest(p) for p in (checkpoint_path, data_path, probe_path)},
        residual_deployment_digest=reference.deployment_digest(digest(checkpoint_path)),
        numeric_contract=reference.NUMERIC_CONTRACT, comparison_contract=FLOAT64_CONTRACT,
        fixed_states=fixed_states, rows=rows, diagnoses=diagnoses, summaries=summaries,
        cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall,
        timing_scope="Includes input loading, static comparison, adapter setup, all owner executions and separate teacher diagnostics; serialization excluded")
    (out/"NUMERIC_PROBE.json.gz").write_bytes(gzip.compress(json.dumps(result, allow_nan=False, separators=(",", ":")).encode(), mtime=0))
    print(json.dumps(dict(out=str(out), fixed_states=fixed_states["summaries"], summaries=summaries)), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("out", "checkpoint", "data", "probe"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    run(args.out, args.checkpoint, args.data, args.probe)
