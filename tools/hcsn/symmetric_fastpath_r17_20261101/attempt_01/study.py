"""Frozen, fully metered finite-operator and execution comparison; no retraining."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

import numpy as np
import scipy
from scipy.integrate import solve_ivp
from scipy.linalg import expm

from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.world import make_episode
from ..support_retention_r16_20261101.compression import BlockLaw
from ..support_retention_r16_20261101.execution import execute
from .fastpath import SymmetricLaw, UnsupportedSymmetry, decomposition

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = HERE.parent / "addressed_decision_r15_20261101"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if path.suffix == ".gz":
        raw = gzip.compress(raw, mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def verify():
    manifest = json.loads((HERE / "SOURCE_MANIFEST.json").read_text())
    for path, expected in manifest["files"].items():
        if digest(ROOT / path) != expected:
            raise RuntimeError(f"Frozen dependency changed: {path}")
    publication = json.loads((HERE / "PUBLICATION.json").read_text())
    if not publication["readback_verified"] or publication["manifest_sha256"] != digest(HERE / "SOURCE_MANIFEST.json"):
        raise RuntimeError("Remote source publication is required before execution")
    return json.loads((HERE / "PROTOCOL.json").read_text())


def models(seed):
    path = BASE / "run_01/training" / f"{seed}.json.gz"
    return json.loads(gzip.decompress(path.read_bytes()))["calibration"]["models"]


def audit(protocol):
    records, failures = [], []
    for seed in protocol["fits"]:
        for name, item in models(seed).items():
            dense, fast = BlockLaw.from_payload(item["payload"]), SymmetricLaw.from_payload(item["payload"])
            times = np.asarray(protocol["durations"])
            start = time.process_time()
            ode = solve_ivp(lambda _, y: (y.reshape(40, 40) @ dense.Q).ravel(),
                (0., float(times[-1])), np.eye(40).ravel(), t_eval=times,
                method="DOP853", rtol=2.3e-14, atol=2e-15)
            if not ode.success:
                failures.append(dict(fit=seed, model=name, error=ode.message))
                continue
            rows = []
            for index, dt in enumerate(times):
                actual, reference = fast.transition(dt), dense.transition(dt)
                independent = ode.y[:, index].reshape(40, 40)
                row = dict(dt=float(dt), dense_error=float(np.max(abs(actual-reference))),
                    ode_error=float(np.max(abs(actual-independent))), minimum=float(actual.min()),
                    mass_error=float(np.max(abs(actual.sum(1)-1))),
                    fast=actual.tolist(), dense=reference.tolist(), ode=independent.tolist())
                rows.append(row)
                if (row["dense_error"] > protocol["operator_atol"] or row["ode_error"] > protocol["operator_atol"]
                        or row["minimum"] < 0 or row["mass_error"] > protocol["operator_atol"]):
                    failures.append(dict(fit=seed, model=name, dt=float(dt), reason="operator threshold"))
            path = HERE / "results" / f"operator_{seed}_{name}.json.gz"
            save(path, dict(identity=dense.identity, operator_identity=dense.operator_identity, rows=rows))
            records.append(dict(fit=seed, model=name, eligible=fast.fastpath_status,
                identical_payload=fast.export()==dense.export(), cpu_seconds=time.process_time()-start,
                max_dense_error=max(x["dense_error"] for x in rows),
                max_ode_error=max(x["ode_error"] for x in rows),
                max_mass_error=max(x["mass_error"] for x in rows), minimum=min(x["minimum"] for x in rows)))
    # Preserve a conservative asymmetric generator as a fallback fixture.
    mutant = BlockLaw()
    mutant.Q = mutant.Q.copy()
    mutant.Q[0, 4] += .01
    mutant.Q[0, 0] -= .01
    mutant._finish()
    fallback = SymmetricLaw.from_payload(mutant.export())
    controls = dict(asymmetric_rejected=not fallback.fastpath_status["eligible"],
        fallback_exact=np.array_equal(fallback.transition(.5), expm(.5*mutant.Q)))
    for label, invalid in (("shape", np.zeros((4,4))), ("nonfinite", np.full((40,40), np.nan))):
        try:
            decomposition(invalid)
        except UnsupportedSymmetry:
            controls[label+"_rejected"] = True
        else:
            controls[label+"_rejected"] = False
    passed = not failures and all(controls.values()) and all(
        x["eligible"]["eligible"] and x["identical_payload"] for x in records)
    save(HERE / "results/OPERATOR_SUMMARY.json", dict(records=records, failures=failures,
        controls=controls, passed=passed))
    if not passed:
        raise RuntimeError("Operator or rejection gate failed; inspect retained records")


def behavior(row):
    # CPU/wall and numeric-state hashes are separately retained, never called equal.
    return {k:v for k,v in row.items() if k not in ("cpu_seconds", "wall_seconds", "checkpoint_io_cpu_seconds") and k!="queries"} | {
        "queries":[{k:v for k,v in q.items() if k!="checkpoint_sha256"} for q in row["queries"]]}


def campaign(protocol):
    pairs, failures, raw_paths, preparations = [], [], [], {}
    for fit in protocol["fits"]:
        frozen = models(fit)
        owner = Law(theta=protocol["world_theta"])
        laws, prep = {}, {}
        for model in protocol["models"]:
            for mode, cls in (("dense",BlockLaw),("fast",SymmetricLaw)):
                start = time.process_time()
                laws[model,mode] = cls.from_payload(frozen[model]["payload"])
                prep[model+"_"+mode] = time.process_time()-start
        preparations[fit] = prep
        rows = []
        with tempfile.TemporaryDirectory(prefix="hcsn-r17-fast-") as directory:
            for domain in protocol["domains"]:
                for index in range(protocol["worlds_per_fit_domain"]):
                    seed = protocol["namespace"]*10**12 + fit*10**5 + (10000 if domain=="ood" else 0) + index
                    episode = make_episode(owner,seed,domain)
                    for model in protocol["models"]:
                        for representation in protocol["representations"]:
                            results, snapshots = {}, {}
                            for mode in (["dense","fast"] if index%2==0 else ["fast","dense"]):
                                start = time.process_time()
                                try:
                                    result = execute(laws[model,mode],episode,representation=representation,
                                        checkpoint_path=Path(directory)/"state.json")
                                    snapshots[mode] = json.loads((Path(directory)/"state.json").read_text())
                                except Exception as exc:
                                    result = dict(invalid=True,error_type=type(exc).__name__,error=str(exc),
                                        cpu_seconds=time.process_time()-start,seed=seed,world=episode.fingerprint)
                                    failures.append(dict(fit=fit,model=model,representation=representation,mode=mode,**result))
                                results[mode] = result
                            valid = not any(x.get("invalid") for x in results.values())
                            hashes_differ = None if not valid else sum(a["checkpoint_sha256"]!=b["checkpoint_sha256"]
                                for a,b in zip(results["dense"]["queries"],results["fast"]["queries"]))
                            state_error = None if not valid else max(float(np.max(abs(np.asarray(snapshots["dense"][name])-np.asarray(snapshots["fast"][name]))))
                                for name in ("beliefs", "packed", "anchor_times", "clock") if name in snapshots["dense"])
                            pair = dict(fit=fit,model=model,representation=representation,domain=domain,seed=seed,
                                valid=valid,behavior_equal=valid and behavior(results["dense"])==behavior(results["fast"]),
                                checksum_differences=hashes_differ,checkpoint_state_error=state_error,
                                dense_cpu=results["dense"]["cpu_seconds"],fast_cpu=results["fast"]["cpu_seconds"])
                            pairs.append(pair)
                            rows.append(dict(pair=pair,results=results,checkpoint_snapshots=snapshots))
        raw_path = HERE / "results" / f"execution_{fit}.json.gz"
        save(raw_path,dict(fit=fit,preparation_cpu_seconds=prep,rows=rows))
        raw_paths.append(str(raw_path.relative_to(HERE)))
    grouped = {}
    for model in protocol["models"]:
        for representation in protocol["representations"]:
            selected = [p for p in pairs if p["model"]==model and p["representation"]==representation]
            dense = sum(p["dense_cpu"] for p in selected)
            fast = sum(p["fast_cpu"] for p in selected)
            dense_prep = sum(x[model+"_dense"] for x in preparations.values())/len(protocol["representations"])
            fast_prep = sum(x[model+"_fast"] for x in preparations.values())/len(protocol["representations"])
            grouped[model+"_"+representation] = dict(pairs=len(selected),dense_cpu_seconds=dense,
                fast_cpu_seconds=fast,ratio=fast/dense,preparation_dense_cpu=dense_prep,preparation_fast_cpu=fast_prep,
                with_allocated_preparation_ratio=(fast+fast_prep)/(dense+dense_prep),behavior_mismatches=sum(not p["behavior_equal"] for p in selected))
    save(HERE / "results/EXECUTION_SUMMARY.json",dict(pairs=pairs,groups=grouped,failures=failures,
        raw_paths=raw_paths,preparation_cpu_seconds=preparations,all_behavior_equal=all(p["behavior_equal"] for p in pairs),
        checkpoint_state_gate=all(p["valid"] and p["checkpoint_state_error"]<=protocol["state_atol"] for p in pairs),
        scope="Includes execute planning, state IO and checkpoint restore; preparation in each raw archive; excludes training/GPU/joules"))


def supervise():
    import resource
    results = []
    for phase in ("audit", "campaign"):
        log = HERE / "results" / f"{phase}.stdout.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        wall = time.perf_counter()
        with log.open("xb") as out, (HERE/"results"/f"{phase}.stderr.log").open("xb") as err:
            child = subprocess.Popen([sys.executable,"-m","tools.hcsn.symmetric_fastpath_r17_20261101.study",phase],
                stdout=out,stderr=err,cwd=ROOT)
            _, status, usage = os.wait4(child.pid,0)
            child.returncode = os.waitstatus_to_exitcode(status)
        receipt = dict(phase=phase,exit_code=child.returncode,total_cpu_seconds=usage.ru_utime+usage.ru_stime,
            wall_seconds=time.perf_counter()-wall,max_rss_linux_kib=usage.ru_maxrss,
            includes="fresh process imports, all attempted work, output serialization/writing and exit")
        save(HERE/"results"/f"{phase}.PROCESS_RECEIPT.json",receipt)
        results.append(receipt)
        if child.returncode:
            break
    save(HERE/"results/PROCESS_SUMMARY.json",dict(processes=results,
        nonoverlapping_cpu_seconds=sum(x["total_cpu_seconds"] for x in results),
        environment=dict(python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__,
                         platform=platform.platform(),thread_variables={name:os.environ.get(name) for name in
                         ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS")})))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase",choices=("audit","campaign","supervise"))
    args = parser.parse_args()
    protocol = verify()
    if args.phase == "supervise":
        supervise()
    elif args.phase == "audit":
        audit(protocol)
    else:
        campaign(protocol)
