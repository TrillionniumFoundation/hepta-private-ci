"""Native physics, durable recovery, independent oracle and full-cost comparison.

Sparse and dense schedules share public observations. Ordinary receives the same
event-aware schedule as analytic cells. No task-utility or energy claim is made.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import subprocess
import time

import numpy as np
from scipy.linalg import expm
from reference import Reference, coefficients, decode, features

PARAMETERS = [.2, -.3, .4, -.1, .5, .2, .4, -.2, .3, .5, -.1]
ZERO = "0"*64
FAMILIES = ("ordinary", "distribution", "sampled")


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)


class Client:
    def __init__(self, binary, model, root, pair, log):
        self.stderr = (root / ("stderr-"+pair[:8]+".txt")).open("w")
        self.process = subprocess.Popen([str(binary), str(model), str(root), pair],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr, text=True)
        self.log, self.bytes = log, 0

    def step(self, request):
        text = json.dumps(request, separators=(",", ":"), allow_nan=False)+"\n"
        self.process.stdin.write(text); self.process.stdin.flush()
        response = self.process.stdout.readline()
        self.bytes += len(text.encode())+len(response.encode())
        if not response:
            raise RuntimeError("native process stopped without receipt")
        value = json.loads(response)
        self.log.write(json.dumps(dict(request=request, response=value), separators=(",", ":"))+"\n")
        if not value["ok"]:
            raise RuntimeError(value)
        return value["receipt"]

    def close(self):
        self.process.stdin.close()
        _, status, usage = os.wait4(self.process.pid, 0)
        self.process.returncode = os.waitstatus_to_exitcode(status)
        self.stderr.close(); self.process.stdout.close()
        if self.process.returncode:
            raise RuntimeError(("native process exit", self.process.returncode))
        return usage.ru_utime+usage.ru_stime, usage.ru_maxrss


def run_one(binary, out, family, seed, dense):
    root = out / f"{family}-{seed}-{'dense' if dense else 'event'}"
    root.mkdir()
    model = root / "model.json"
    save(model, dict(parameters=PARAMETERS, family=family, seed_hex=f"{seed:016x}"))
    rng = np.random.default_rng(9000+seed)
    schedule = [dict(driver=float(rng.uniform(-.9, .9)), duration_micros=2_000_000,
                     horizon_micros=750_000, reset=(i in (3, 8))) for i in range(12)]
    save(root / "public_schedule.json", schedule)
    reference = Reference(PARAMETERS, family)
    errors, endpoints, jumps = [], [], []
    count_error = mass_error = 0.
    sequence, pair, native_cpu, rss, ipc_bytes, journal_bytes = 0, ZERO, 0., 0, 0, 0
    parent_start, wall_start = time.process_time(), time.perf_counter()
    with (root / "receipts.jsonl").open("x") as log:
        client = Client(binary, model, root, pair, log)
        for index, segment in enumerate(schedule):
            subdivisions = 16 if dense else 1
            for part in range(subdivisions):
                sequence += 1
                reset = segment["reset"] and part+1 == subdivisions
                request = dict(sequence=sequence, pair_before=pair, driver=segment["driver"],
                    duration_micros=segment["duration_micros"]//subdivisions,
                    horizon_micros=segment["horizon_micros"], reset=reset)
                receipt = client.step(request)
                pair = receipt["pair_after"]
                journal_bytes += receipt["durable_bytes_written"]
                jumps.extend(receipt["jumps"])
                state = receipt["cell"]
                if family == "sampled":
                    actual_state = np.eye(5)[state["index"]]
                    expected = features(PARAMETERS, family, actual_state, request["driver"], request["horizon_micros"]/1e6)
                else:
                    reference.advance(request["driver"], request["duration_micros"]/1e6, reset)
                    expected = reference.query(request["driver"], request["horizon_micros"]/1e6)
                    bits = state["gates_bits"] if family == "ordinary" else state["probability_bits"]
                    actual_state = np.array([decode(x) for x in bits])
                    errors.append(float(np.max(np.abs(actual_state-reference.state))))
                    count_error = max(count_error, abs(decode(state["event_count_bits"])-reference.events))
                    if family == "distribution":
                        mass_error = max(mass_error, abs(actual_state.sum()-1))
                errors.append(float(np.max(np.abs(np.asarray(receipt["features"])-expected))))
                drive = np.floor(np.asarray(receipt["features"])*2**24+.5).astype(int)
                expected_signal = np.zeros(5, dtype=int); selected = int(np.argmax(drive)); expected_signal[selected] = drive[selected]
                if receipt["signals_q24"] != expected_signal.tolist():
                    raise AssertionError("native output did not consume computed physical features")
            endpoints.append(dict(cell=receipt["cell"], features=receipt["features"], signals_q24=receipt["signals_q24"]))
            if index == 5:
                cost, peak = client.close(); native_cpu += cost; rss = max(rss, peak); ipc_bytes += client.bytes
                client = Client(binary, model, root, pair, log)
        cost, peak = client.close(); native_cpu += cost; rss = max(rss, peak); ipc_bytes += client.bytes
    full_wall = time.perf_counter()-wall_start
    # SciPy/reference work is deliberately outside the deployment CPU measure below.
    validation_parent_cpu = time.process_time()-parent_start
    result = dict(family=family, seed=seed, dense=dense, intervals=sequence, restarts=1,
        max_error=max(errors), count_error=count_error, mass_error=mass_error,
        native_child_full_cpu_seconds=native_cpu, validation_parent_cpu_seconds=validation_parent_cpu,
        validation_wall_seconds=full_wall, child_maxrss_kib=rss, ipc_bytes=ipc_bytes,
        owner_durable_record_bytes=journal_bytes, endpoints=endpoints, jumps=jumps,
        physics_features_drive_native_signals=True)
    save(root / "result.json", result)
    return result


def cost_run(binary, out, family, seed, dense):
    """Same event schedule, recovery and receipt retention; no SciPy in timed loop."""
    root=out/f"cost-{family}-{seed}-{'dense' if dense else 'event'}"; root.mkdir(); model=root/"model.json"
    save(model,dict(parameters=PARAMETERS,family=family,seed_hex=f"{seed:016x}"))
    schedule=json.loads((out/f"{family}-{seed}-event/public_schedule.json").read_text())
    start_cpu,start_wall=time.process_time(),time.perf_counter()
    cpu=0.; pair=ZERO; size=0
    with (root/"receipts.jsonl").open("x") as log:
        client=Client(binary,model,root,pair,log)
        sequence=0
        for i,step in enumerate(schedule):
            subdivisions=16 if dense else 1
            for part in range(subdivisions):
                sequence+=1
                current=dict(step,duration_micros=step["duration_micros"]//subdivisions,
                             reset=step["reset"] and part+1==subdivisions)
                r=client.step(dict(sequence=sequence,pair_before=pair,**current)); pair=r["pair_after"];size+=r["durable_bytes_written"]
            if i==5:
                c,_=client.close();cpu+=c;client=Client(binary,model,root,pair,log)
        c,_=client.close();cpu+=c
    return dict(family=family,seed=seed,dense=dense,complete_cpu_seconds=cpu+time.process_time()-start_cpu,
                complete_wall_seconds=time.perf_counter()-start_wall,owner_durable_record_bytes=size,
                includes="startup, model parse, physics, signal, IPC, journal, witness, cell checkpoint, receipt retention, one restart, shutdown")


def tail_check(binary, model):
    """Positive-flux expm and independent finite Taylor integrals at tiny times."""
    probe=json.loads(subprocess.check_output([str(binary),"--tail-probe",str(model)],text=True))
    q,r,_=coefficients(PARAMETERS,.3)
    killed=q.copy();killed[2,4]=0
    augmented=np.zeros((6,6));augmented[:5,:5],augmented[:5,5]=killed,r
    matrix_norm=float(np.linalg.norm(killed,np.inf))
    passed=True
    for row in probe["rows"]:
        state=row["initial_state"];t=row["horizon_micros"]/1e6
        hit=float(row["features"][3]); flux=float(expm(t*augmented)[state,5])
        old_subtraction=1-float(expm(t*killed)[state].sum())
        row.update(positive_flux_expm=flux,old_one_minus_survival=old_subtraction,
                   expm_absolute_error=abs(hit-flux),q24_first_hit=int(np.floor(hit*2**24+.5)))
        if row["horizon_micros"]<=10:
            # This reference does not compute an exponential or 1-survival.
            term=r.copy();terms=[]
            for n in range(6):
                terms.append(float(term[state]*t**(n+1)/math.factorial(n+1)))
                term=killed@term
            reference=sum(terms)
            remainder=t*float(np.max(abs(r)))*math.exp(t*matrix_norm)*(t*matrix_norm)**6/math.factorial(7)
            relative_error=abs(hit/reference-1)
            row.update(taylor_terms=terms,taylor_sum=reference,
                exact_arithmetic_taylor_remainder_bound=remainder,
                taylor_relative_error=relative_error,
                passed=bool(hit>0 and relative_error<1e-12))
        else:
            row["passed"]=bool(abs(hit-flux)<2e-10 and abs(hit-old_subtraction)<2e-10)
        passed=passed and row["passed"]
    probe.update(passed=passed,relative_tolerance=1e-12,
        tail_reference="six-term integral Taylor series sum e_i K^n r t^(n+1)/(n+1)!; independent from uniformization/expm",
        bound_scope="Taylor analytic truncation only, excludes floating-point coefficient/arithmetic error",
        quantization_scope="Tail preserved in f64 physical query; sub-half-Q24 probabilities quantize to zero in published channel",
        whole_parameter_envelope_relative_accuracy_established=False)
    return probe


def qualify(args):
    args.out.mkdir(parents=True, exist_ok=False)
    protocol=dict(seeds=[173,271,419,587], families=list(FAMILIES), dense_subdivisions=16,
        intervals=12, duration_micros=2_000_000, horizon_micros=750_000,
        numeric_tolerance=2e-10, ensemble_samples=20_000, ensemble_sigma_gate=6,
        tail_probe_horizons_micros=[1,10,750_000],tail_relative_tolerance=1e-12,
        claim="native finite-law correctness and measured implementation cost; no task efficacy")
    save(args.out/"PROTOCOL.json",protocol)
    jobs=[(f,s,d) for f in FAMILIES for s in protocol["seeds"] for d in (False,True)]
    random.Random(71273).shuffle(jobs)
    rows=[run_one(args.binary,args.out,*job) for job in jobs]
    paired=[]
    for family in FAMILIES:
        for seed in protocol["seeds"]:
            event=next(x for x in rows if x["family"]==family and x["seed"]==seed and not x["dense"])
            dense=next(x for x in rows if x["family"]==family and x["seed"]==seed and x["dense"])
            error=max(float(np.max(np.abs(np.array(x["features"])-y["features"]))) for x,y in zip(event["endpoints"],dense["endpoints"]))
            signals=all(x["signals_q24"]==y["signals_q24"] for x,y in zip(event["endpoints"],dense["endpoints"]))
            jump_equal=len(event["jumps"])==len(dense["jumps"]) and all(
                (a["before"],a["after"],a["fired"])==(b["before"],b["after"],b["fired"])
                and abs(a["elapsed_seconds"]-b["elapsed_seconds"])<2e-10 for a,b in zip(event["jumps"],dense["jumps"]))
            paired.append(dict(family=family,seed=seed,feature_error=error,signals_equal=signals,sampled_events_equal=jump_equal,
                event_intervals=event["intervals"],dense_intervals=dense["intervals"]))
    model=args.out/"sampled-173-event/model.json"
    tail=tail_check(args.binary,model)
    save(args.out/"TAIL_CHECK.json",tail)
    ensemble=json.loads(subprocess.check_output([str(args.binary),"--ensemble",str(model),"20000"],text=True))
    q,r,origin=coefficients(PARAMETERS,.3); aug=np.zeros((6,6));aug[:5,:5],aug[:5,5]=q,r
    flow=expm(4*aug); expected=origin@flow[:5,:5]; expected_count=float(origin@flow[:5,5])
    empirical=np.array(ensemble["counts"])/ensemble["samples"]
    probability_gate=bool(np.all(np.abs(empirical-expected)<=6*np.sqrt(expected*(1-expected)/ensemble["samples"])+1/ensemble["samples"]))
    se=np.sqrt(max(0,ensemble["event_second_moment"]-ensemble["event_mean"]**2)/ensemble["samples"])
    count_gate=bool(abs(ensemble["event_mean"]-expected_count)<=6*se+1/ensemble["samples"])
    ensemble.update(reference_probability=expected.tolist(),reference_expected_count=expected_count,
                    probability_gate=probability_gate,count_gate=count_gate)
    save(args.out/"ENSEMBLE.json",ensemble)
    cost_jobs=[(f,s,d) for f in FAMILIES for s in protocol["seeds"] for d in (False,True)];random.Random(8191).shuffle(cost_jobs)
    costs=[cost_run(args.binary,args.out,*job) for job in cost_jobs]
    passed=(max(x["max_error"] for x in rows)<2e-10 and max(x["count_error"] for x in rows)<2e-10
        and all(x["feature_error"]<2e-10 and x["signals_equal"] and x["sampled_events_equal"] for x in paired)
        and probability_gate and count_gate and tail["passed"])
    report=dict(schema="hcsn.native-event-owner-qualification.v1",passed=passed,source_build_sha256=args.build_sha,
        binary_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),protocol=protocol,
        max_independent_reference_error=max(x["max_error"] for x in rows), max_event_count_error=max(x["count_error"] for x in rows),
        max_mass_error=max(x["mass_error"] for x in rows), paired=paired,ensemble=ensemble,tail_check=tail,costs=costs,
        cost_means={f+('/dense' if d else '/event'):dict(cpu_seconds=float(np.mean([x["complete_cpu_seconds"] for x in costs if x["family"]==f and x["dense"]==d])),
                           wall_seconds=float(np.mean([x["complete_wall_seconds"] for x in costs if x["family"]==f and x["dense"]==d]))) for f in FAMILIES for d in (False,True)},
        native_physics_executed=True, continuum_exact=False, task_utility_superiority_established=False,
        energy_saving_established=False, production_activation=False, authority="DENY_ALL",
        limitations=["Finite 5-state CTMC law, not continuum He-Xiong exactness", "Debug build; measured CPU is not hardware energy",
            "No new task policy or value-head benefit is inferred", "Arbitrary interruption between two commits is detected and blocked, not automatically repaired",
            "SplitMix64 samples are a distinct explicit RNG contract, not PCG64 path parity",
            "Tail f64 query checks use the fixed fixture; Q24 cannot represent probabilities below half an LSB",
            "No whole-envelope floating-point or relative tail error certificate"])
    save(args.out/"REPORT.json",report); print(json.dumps({k:report[k] for k in ("passed","max_independent_reference_error","cost_means")}))
    return passed


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--binary",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True);p.add_argument("--build-sha",required=True)
    raise SystemExit(0 if qualify(p.parse_args()) else 1)
