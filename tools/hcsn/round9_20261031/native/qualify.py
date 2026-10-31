"""Frozen FullHX parity, unified process recovery and owner-side scheduling cost.

The client sends one identical public interval to each scheduling mode. Rust
owns interval subdivision, physical state, content inference and durable state.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import struct
import subprocess
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
ZERO = "0"*64
PARAMETERS = [.2,-.3,.4,-.1,.5,.2,.4,-.2,.3,.5,-.1]
FAMILIES = ("ordinary","distribution","sampled")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(data, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def logits(output):
    return [struct.unpack("!f",bytes.fromhex(s))[0] for s in output["logits_bits"]]


class Client:
    def __init__(self,binary,model,root,pair):
        self.proc=subprocess.Popen([str(binary),str(model),str(root),pair],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)

    def step(self,request):
        self.proc.stdin.write(json.dumps(request,allow_nan=False)+"\n")
        self.proc.stdin.flush()
        line=self.proc.stdout.readline()
        if not line:
            raise RuntimeError(self.proc.stderr.read())
        return json.loads(line)

    def close(self):
        self.proc.stdin.close()
        _, status, usage=os.wait4(self.proc.pid,0)
        self.proc.returncode=os.waitstatus_to_exitcode(status)
        stderr=self.proc.stderr.read()
        self.proc.stdout.close()
        self.proc.stderr.close()
        if self.proc.returncode:
            raise RuntimeError((self.proc.returncode,stderr))
        return dict(cpu_seconds=usage.ru_utime+usage.ru_stime,peak_rss_kib=usage.ru_maxrss)


def owner_run(binary, weights, root, schedule, family, seed, subdivisions, restart):
    root.mkdir()
    wall,cpu=time.perf_counter(),time.process_time()
    model=root/"model.json"
    save(model,dict(parameters=PARAMETERS,family=family,seed_hex=f"{seed:016x}",
        content_model=str(weights),content_model_sha256=sha(weights),subdivisions=subdivisions))
    client=Client(binary,model,root,ZERO)
    pair=ZERO
    endpoints=[]
    children=[]
    try:
        with (root/"receipts.jsonl").open("x") as log:
            for index, step in enumerate(schedule):
                request=dict(operation="interval",pair_before=pair,**step)
                response=client.step(request)
                if not response["ok"]:
                    raise RuntimeError(response)
                receipt=response["receipt"]
                pair=receipt["pair_after"]
                log.write(json.dumps(receipt,sort_keys=True)+"\n")
                log.flush()
                os.fsync(log.fileno())
                endpoints.append(receipt)
                if restart and index==5:
                    children.append(client.close())
                    # Reconstruct nothing in Python. The only restored client
                    # knowledge is its externally acknowledged pair digest.
                    client=Client(binary,model,root,pair)
    finally:
        children.append(client.close())
    result=dict(family=family,seed=seed,subdivisions=subdivisions,restart=restart,
        cpu_seconds=time.process_time()-cpu+sum(x["cpu_seconds"] for x in children),
        wall_seconds=time.perf_counter()-wall,child_cpu_seconds=sum(x["cpu_seconds"] for x in children),
        peak_child_rss_kib=max(x["peak_rss_kib"] for x in children),
        native_commits=sum(x["scheduled_commits"] for x in endpoints),
        physical_propagations=sum(x["scheduled_commits"] for x in endpoints),
        physical_queries=sum(x["scheduled_commits"] for x in endpoints),
        host_requests=len(endpoints),
        decoder_calls=endpoints[-1]["content"]["completed_reads"],
        durable_bytes=sum(x["durable_bytes_written"] for x in endpoints),
        native_content_nanos=sum(x["content_execution_nanos"] for x in endpoints),
        final_pair=pair,final_checkpoint_sha256=sha(root/"cell-checkpoint.json"),
        endpoints=endpoints)
    save(root/"RESULT.json",{k:v for k,v in result.items() if k!="endpoints"})
    return result


def fault_checks(binary,weights,root,step):
    root.mkdir()
    model=root/"model.json"
    save(model,dict(parameters=PARAMETERS,family="sampled",seed_hex="00000000000000ad",
        content_model=str(weights),content_model_sha256=sha(weights),subdivisions=16))
    client=Client(binary,model,root,ZERO)
    good=client.step(dict(operation="interval",pair_before=ZERO,**step))
    assert good["ok"],good
    pair=good["receipt"]["pair_after"]
    names=("journal.bin","witness.bin","cell-checkpoint.json")
    before={name:sha(root/name) for name in names}
    rejected=[]
    for kind in ("missing_packet","packet_digest_mismatch","stale_acknowledgement"):
        request=dict(operation="interval",pair_before=pair,**step)
        request["content"]=dict(step["content"])
        if kind=="missing_packet": request["content"]["path"]=str(root/"absent.json")
        if kind=="packet_digest_mismatch": request["content"]["sha256"]=ZERO
        if kind=="stale_acknowledgement": request["pair_before"]=ZERO
        response=client.step(request)
        after={name:sha(root/name) for name in names}
        rejected.append(dict(case=kind,rejected=not response["ok"],frontier_unchanged=before==after,error=response.get("error")))
    client.close()
    original=(root/"cell-checkpoint.json").read_bytes()
    value=json.loads(original)
    value["content"]["completed_reads"]+=1
    (root/"cell-checkpoint.json").write_text(json.dumps(value))
    proc=subprocess.run([str(binary),str(model),str(root),pair],input="",text=True,capture_output=True)
    rejected.append(dict(case="content_checkpoint_tamper",rejected=proc.returncode!=0,error=proc.stderr.strip()))
    (root/"cell-checkpoint.json").write_bytes(original)
    changed=json.loads(model.read_text()); changed["content_model_sha256"]=ZERO
    altered=root/"wrong-model.json"; save(altered,changed)
    proc=subprocess.run([str(binary),str(altered),str(root),pair],input="",text=True,capture_output=True)
    rejected.append(dict(case="content_model_digest_change",rejected=proc.returncode!=0,error=proc.stderr.strip()))
    return rejected


def main(args):
    start_wall,start_cpu=time.perf_counter(),time.process_time()
    args.out.mkdir(parents=True,exist_ok=False)
    source=args.hcsn_source/"task_value_factorial_20261030/task.py"
    spec=importlib.util.spec_from_file_location("frozen_r8_content",source)
    task=importlib.util.module_from_spec(spec); spec.loader.exec_module(task)
    protocol=dict(schema="hepta.r9.native-content-owner.protocol.v1",seeds=[173,271,419,587],
        families=list(FAMILIES),intervals=12,duration_micros=2_000_007,horizon_micros=750_000,
        subdivisions=[1,16],restarts=[False,True],logit_absolute_tolerance=5e-5,
        physical_tolerance=2e-10,jump_time_tolerance=2e-12,
        packet_length=32,parameters=PARAMETERS,native_binary_sha256=sha(args.binary),
        content_model_sha256=sha(args.weights),runner_sha256=sha(Path(__file__)),
        task_sha256=sha(source),reference_sha256=sha(args.hcsn_source/"third/memory/reference.py"),
        hypothesis="A single Rust owner decodes real content and restores it with physical state; its public-interval scheduler omits redundant control commits without losing endpoint observations",
        novelty_scope="Unified native ownership and scheduling; no intrinsic analytic-cell superiority hypothesis",
        observation_contract="Piecewise constant public driver, content decoding and observation at every interval endpoint; no intermediate external action obligation",
        training="Frozen inherited FullHX, no retraining or new trained native control weights",
        production_activation=False,authority="DENY_ALL")
    # Freeze before input generation or any reference/native evaluation.
    save(args.out/"PROTOCOL.json",protocol)
    data=args.out/"data"; data.mkdir()
    schedules={}; labels={}
    for seed in protocol["seeds"]:
        rng=np.random.default_rng(9000+seed)
        schedules[seed]=[]; labels[seed]=[]
        for index in range(12):
            symbol=(index+seed)%2
            packet=data/f"packet-{seed}-{index}.json"
            save(packet,task.packet(symbol,181031+seed*100+index,length=32))
            schedules[seed].append(dict(driver=float(rng.uniform(-.9,.9)),duration_micros=2_000_007,
                horizon_micros=750_000,reset=index in (3,8),content=dict(path=str(packet),sha256=sha(packet))))
            labels[seed].append(symbol)
    save(args.out/"DATA_IDENTITY.json",{p.name:sha(p) for p in sorted(data.iterdir())})
    adapter=task.ContentAdapter()
    reference={seed:[adapter.read(step["content"]["path"]) for step in schedule] for seed,schedule in schedules.items()}
    save(args.out/"ORACLE.json",{str(seed):rows for seed,rows in reference.items()})
    jobs=[(f,s,n,r) for f in FAMILIES for s in protocol["seeds"] for n in (1,16) for r in (False,True)]
    random.Random(921031).shuffle(jobs)
    rows=[]
    for f,s,n,r in jobs:
        root=args.out/f"{f}-{s}-{'event' if n==1 else 'dense'}-{'restart' if r else 'continuous'}"
        row=owner_run(args.binary,args.weights,root,schedules[s],f,s,n,r)
        row["accuracy"]=sum(e["content"]["last"]["observation"]==label for e,label in zip(row["endpoints"],labels[s]))/12
        row["oracle_observations_equal"]=all(e["content"]["last"]["observation"]==o["observation"] for e,o in zip(row["endpoints"],reference[s]))
        row["maximum_logit_error"]=max(max(abs(a-b) for a,b in zip(logits(e["content"]["last"]),o["logits"])) for e,o in zip(row["endpoints"],reference[s]))
        rows.append(row)
    pairs=[]; recoveries=[]
    for event in (r for r in rows if r["subdivisions"]==1):
        dense=next(r for r in rows if r["subdivisions"]==16 and all(r[k]==event[k] for k in ("family","seed","restart")))
        errors=[]; jumps=True
        for a,b in zip(event["endpoints"],dense["endpoints"]):
            errors.extend(abs(x-y) for x,y in zip(a["features"],b["features"]))
            if len(a["jumps"])!=len(b["jumps"]): jumps=False
            for x,y in zip(a["jumps"],b["jumps"]):
                jumps &= all(x[k]==y[k] for k in ("before","after","fired")) and abs(x["elapsed_seconds"]-y["elapsed_seconds"])<2e-12
        pairs.append(dict(family=event["family"],seed=event["seed"],restart=event["restart"],
            content_equal=all(a["content"]==b["content"] for a,b in zip(event["endpoints"],dense["endpoints"])),
            signals_equal=all(a["signals_q24"]==b["signals_q24"] for a,b in zip(event["endpoints"],dense["endpoints"])),
            maximum_feature_error=max(errors),jumps_equal=jumps,cpu_saved=dense["cpu_seconds"]-event["cpu_seconds"],
            commit_reduction=1-event["native_commits"]/dense["native_commits"]))
    for continuous in (r for r in rows if not r["restart"]):
        resumed=next(r for r in rows if r["restart"] and all(r[k]==continuous[k] for k in ("family","seed","subdivisions")))
        keys=("pair_after","native_checkpoint","cell","content","features","signals_q24","jumps")
        recoveries.append(dict(family=continuous["family"],seed=continuous["seed"],subdivisions=continuous["subdivisions"],
            endpoints_bit_exact=all(all(a[k]==b[k] for k in keys) for a,b in zip(continuous["endpoints"],resumed["endpoints"]))))
    faults=fault_checks(args.binary,args.weights,args.out/"faults",schedules[173][0])
    passed=all(p["content_equal"] and p["signals_equal"] and p["jumps_equal"] and p["maximum_feature_error"]<2e-10 for p in pairs)
    passed &= all(r["endpoints_bit_exact"] for r in recoveries) and all(x["rejected"] and x.get("frontier_unchanged",True) for x in faults)
    passed &= all(r["oracle_observations_equal"] and r["maximum_logit_error"]<5e-5 and r["decoder_calls"]==12 and r["native_commits"]==12*r["subdivisions"] for r in rows)
    means={}
    for family in FAMILIES:
        for n in (1,16):
            group=[r for r in rows if r["family"]==family and r["subdivisions"]==n]
            means[f"{family}/{'event' if n==1 else 'dense'}"]={k:float(np.mean([r[k] for r in group])) for k in
                ("cpu_seconds","wall_seconds","child_cpu_seconds","native_commits","decoder_calls","durable_bytes","accuracy","peak_child_rss_kib")}
    report=dict(schema="hepta.r9.native-content-owner.report.v1",passed=bool(passed),protocol=protocol,pairs=pairs,
        recoveries=recoveries,faults=faults,means=means,runs=[{k:v for k,v in r.items() if k!="endpoints"} for r in rows],
        native_content_inference=True,python_content_inference_in_runtime=False,
        owner_schedules_intermediate_commits=True,shared_content_and_physics_checkpoint=True,
        energy_joules=None,energy_measured=False,analytic_cell_advantage_established=False,
        probability_gate_content_savings=False,
        campaign_parent_cpu_seconds=time.process_time()-start_cpu,campaign_wall_seconds=time.perf_counter()-start_wall,
        cost_scope="Parent IPC, receipt serialization/fsync and child startup, weight parsing, actual file reads, FullHX inference, physics/native runtime, journal/witness/paired checkpoint, complete owner process restart, shutdown",
        excluded_per_run="Shared input generation, separate NumPy oracle, evaluator scoring, summary; no native training in this frozen-content experiment",
        crash_scope="Acknowledged completed-interval restarts; arbitrary-crash atomicity is not established; incomplete native/pair commits fail closed",
        event_scope="Public input/observation schedule; native output does not autonomously decide which required endpoint to omit",
        hardware_energy_claim=False,production_activation=False,authority="DENY_ALL")
    save(args.out/"REPORT.json",report)
    print(json.dumps(dict(passed=bool(passed),maximum_logit_error=max(r["maximum_logit_error"] for r in rows),means=means)))
    return passed


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("binary","weights","hcsn-source","out"):
        parser.add_argument("--"+name,type=Path,required=True)
    args=parser.parse_args()
    args.binary=args.binary.resolve(); args.weights=args.weights.resolve(); args.out=args.out.resolve()
    raise SystemExit(0 if main(args) else 1)
