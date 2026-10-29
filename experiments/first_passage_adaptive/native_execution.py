"""Execute bounded retrieval fixtures through original native NDU and Neuron owners.

This is a research adapter: the original sparse owner binds request/admission
digests; immutable sidecars carry complete FPT and post-I/O task state. It neither
claims production TaskFlow activation nor treats an uncertain read as absent.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from experiments.first_passage_cell.cell import CellParameters, FirstPassageCell
from experiments.first_passage_cell.kernels import first_passage
from experiments.first_passage_cell.ndu import NativeNduPort, SCHEMA, RECURSIVE_PROFILE, canonical, q32

HERE = Path(__file__).resolve().parent
PROFILE = "hepta.fpt-adaptive.owner-research.v1"
ZERO = "0" * 64
OBJECTIVE = {"schema":"hepta.fpt-adaptive.retrieval-objective.v1", "answer_reward":1.0,
             "read_price":0.05,"natural_event_penalty":1.0,"read_duration":0.05,
             "resource_unit":"read-attempt","continuation":"one-read forecast then replan"}


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def save_once(path, value):
    payload = canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError("immutable evidence conflict: " + str(path))
    else:
        with path.open("xb") as stream:
            stream.write(payload)


class ResearchNdu(NativeNduPort):
    def choose(self, values, snapshot, remaining_budget):
        objective = sha(OBJECTIVE)
        rows = []
        for name, row in values.items():
            rows.append({"id":name,"verified":row["feasible"],
                "verification_digest":sha(["deterministic-research-guards",snapshot,name,row["feasible"]]),
                "support_digest":sha([snapshot,name,row]),"resource_cost_q32":q32(row["cost"]),
                "risk_q32":q32(row["risk"]),"uncertainty_q32":0,"terminal_q32":0,
                "events":[{"instant_q32":q32(row["utility"]),"discount_q32":q32(1.0),
                           "event_digest":sha(["forecast",snapshot,name]),"preference_digest":objective}]})
        request={"schema":SCHEMA,"recursive_profile":RECURSIVE_PROFILE,"objective_digest":objective,
                 "snapshot_digest":sha(snapshot),"generation":1,"utility_unit":"task-return",
                 "resource_unit":"task-cost","risk_unit":"probability",
                 "resource_budget_q32":q32(remaining_budget),"risk_ceiling_q32":q32(1.0),"candidates":rows}
        response=self._invoke(request)
        selected=response["advisory_candidate_id"]
        if selected not in values or not values[selected]["feasible"]:
            raise ValueError("native NDU did not return a supported legal action")
        return selected,{"request":request,"response":response,
                         "unit_binding":"native task-cost is one physical read-attempt in this objective"}


class ResearchOwner:
    def __init__(self, manifest_path):
        self.build=json.loads(Path(manifest_path).read_text())
        self.binary=Path(self.build["binary"])
        if self.build["test_status"] != "passed" or sha(self.binary.read_bytes()) != self.build["binary_sha256"]:
            raise ValueError("native owner binary identity failed")
        for name,expected in self.build["adapter_sources"].items():
            if sha((HERE/"native"/name).read_bytes()) != expected:
                raise ValueError("native owner adapter source differs from built bytes")

    def invoke(self, directory, request, inspect=False):
        args=[str(self.binary),"--store",str(directory/"owner"),"--data-root",str(directory/"data")]
        if inspect:
            args.append("--inspect")
        result=subprocess.run(args,input=canonical(request),capture_output=True,timeout=10)
        value=json.loads(result.stdout)
        if result.returncode:
            raise ValueError(value.get("error","native owner failed"))
        if not inspect and value["request_digest"] != sha(request):
            raise ValueError("native owner request binding failed")
        return value


def execute_case(name, specification, output, owner, ndu):
    directory=output/name
    directory.mkdir(parents=True,exist_ok=False)
    (directory/"data").mkdir()
    answer_index=specification.get("answer_index",1)
    for index in range(4):
        text=f"distractor_{index}=unused\n" + ("needle=verified answer\n" if index==answer_index else "")
        (directory/"data"/f"chunk-{index}.txt").write_text(text)
    parameters=CellParameters(drift=-0.45,weights=(0.0,0.0),sigma=0.3,barrier=0.0,reset_gap=0.9,refractory=0.06)
    cell=FirstPassageCell(parameters,specification.get("initial_level",1.0),seed=20261029)
    if specification.get("initial_refractory"):
        cell.repair()
    state={"clock_us":0,"refractory_until_us":round(cell.refractory_remaining*1e6),
           "refractory_period_us":60000,"events":0,"read_units_spent":0,
           "read_units_budget":specification.get("budget",4),"terminal":None}
    deadline_us=specification.get("deadline_us",1_000_000)
    predecessor=ZERO
    fpt_predecessor=ZERO
    window={"end_us":0,"hit_times_us":[]}
    if specification.get("natural_event"):
        cell.level=0.001
        event=cell.advance(0.02,(0,0))
        if not event["events"]:
            raise AssertionError("frozen natural-event fixture produced no hit; no seed resampling permitted")
        window={"end_us":round(event["time"]*1e6),"hit_times_us":[round(x["time"]*1e6) for x in event["events"]]}
    rows=[]
    found=False
    source_reads=0
    for sequence in range(1,17):
        cp=cell.checkpoint()
        save_once(directory/"fpt"/(cp["sha256"]+".json"),cp)
        remaining=state["read_units_budget"]-state["read_units_spent"]
        horizon=min(OBJECTIVE["read_duration"],max(0.0,(deadline_us-round(cell.time*1e6))/1e6))
        forecast=first_passage(max(cell.level-parameters.barrier,0.0),parameters.mu((0,0)),parameters.sigma,horizon)
        risk=float(forecast["F"])
        cancelled=specification.get("cancel_after_reads")==source_reads
        in_ref=cell.refractory_remaining>1e-12
        read_feasible=not found and not cancelled and not in_ref and horizon>0 and source_reads<4
        # The 0.5 relevance prior is frozen and receives no future file contents.
        values={"read":{"utility":0.5-OBJECTIVE["read_price"]-risk,"cost":1.0,"risk":risk,"feasible":read_feasible},
                "wait":{"utility":0.1 if in_ref and not cancelled else -0.01,"cost":0.0,"risk":0.0,
                        "feasible":not found and not cancelled and horizon>0},
                "abstain":{"utility":0.0,"cost":0.0,"risk":0.0,"feasible":True}}
        snapshot={"objective":OBJECTIVE,"fpt_checkpoint":cp["sha256"],"task_state":state,
                  "found":found,"cancelled":cancelled,"risk":risk,"remaining_time":horizon}
        selected,ndu_receipt=ndu.choose(values,snapshot,remaining)
        command={"kind":"Cancel"} if cancelled else {"kind":{"read":"Read","wait":"Wait","abstain":"Stop"}[selected]}
        if command["kind"]=="Read":
            command.update(relative_path=f"chunk-{source_reads}.txt",query="needle")
        features=[min(8.0,max(-8.0,cell.level-parameters.barrier)),risk,
                  min(8.0,float(cell.event_count)),remaining/max(1,state["read_units_budget"]),horizon]
        request={"schema":PROFILE,"subject":"research."+name,"sequence":sequence,
                 "owner_monotonic_us":time.monotonic_ns()//1000,"checkpoint_digest":predecessor,
                 "objective_digest":sha(OBJECTIVE),"ndu_receipt_digest":ndu_receipt["response"]["evaluation_digest"],
                 "fpt_checkpoint_digest":cp["sha256"],"fpt_predecessor_digest":fpt_predecessor,
                 "fpt_checkpoint_json":canonical(cp["payload"]).decode(),
                 "features_q24":[round(x*(1<<24)) for x in features],"state":state,
                 "window":window,"deadline_us":deadline_us,"command":command}
        save_once(directory/"requests"/f"{sequence:04}.json",{"owner_request":request,"ndu":ndu_receipt})
        response=owner.invoke(directory,request)
        state=response["state"]
        source_reads+=response["source_reads_this_call"]
        found=found or bool(response["read"] and response["read"].get("answer"))
        predecessor=response["owner"]["checkpoint_after"]
        fpt_predecessor=cp["sha256"]
        rows.append({"request":request,"response":response})
        if state["terminal"] is not None:
            break
        duration=min(cell.refractory_remaining if command["kind"]=="Wait" else OBJECTIVE["read_duration"],
                     max(0.0,(deadline_us-round(cell.time*1e6))/1e6))
        event=cell.advance(duration,(0,0))
        window={"end_us":round(event["time"]*1e6),"hit_times_us":[round(x["time"]*1e6) for x in event["events"]]}
    else:
        raise ValueError("bounded execution did not terminate")
    # Every logical tick is a fresh OS process, hence later ticks exercise real recovery.
    last=rows[-1]
    replay=owner.invoke(directory,last["request"])
    if replay["source_reads_this_call"]!=0 or not replay["replayed"]:
        raise ValueError("lost-reply replay performed a source read")
    inspected=owner.invoke(directory,last["request"],inspect=True)
    if inspected["checkpoint_digest"]!=predecessor:
        raise ValueError("independent owner reopen lost final anchor")
    checkpoint_path=directory/"fpt"/(cell.checkpoint()["sha256"]+".json")
    # Compare restored execution with an uninterrupted live object. Reusing
    # from_checkpoint on both paths could hide a shared restoration bug.
    live_checkpoint=cell.checkpoint()
    live_clone=copy.deepcopy(cell)
    expected_probe=continuation_probe(live_clone)
    cold=subprocess.run([sys.executable,"-m","experiments.first_passage_adaptive.native_execution",
                         "--restore-checkpoint",str(checkpoint_path)],capture_output=True,check=True,timeout=15)
    cold_probe=json.loads(cold.stdout)
    if canonical(cold_probe["restored"])!=canonical(live_checkpoint):
        raise ValueError("cold-process FPT restore changed the saved live checkpoint")
    if canonical(cold_probe)!=canonical(expected_probe):
        raise ValueError("cold-process FPT restore changed next event/state/random stream")
    summary={"case":name,"source_reads":source_reads,"found":found,"terminal":state["terminal"],
             "actions":[row["request"]["command"]["kind"] for row in rows],
             "native_owner_recoveries":sum(row["response"]["owner"]["recovered"] for row in rows),
             "event_count":cell.event_count,"physical_clock":cell.time,"replay_source_reads":0,
             "cold_fpt_restore_exact":True,
             "read_budget":state["read_units_budget"],"spent":state["read_units_spent"],
             "actual_task_utility":float(found)-OBJECTIVE["read_price"]*state["read_units_spent"]-cell.event_count,
             "owner_final_anchor":predecessor,"full_fpt_checkpoint_digest":cell.checkpoint()["sha256"]}
    save_once(directory/"EXECUTION.json",{"summary":summary,"rows":rows,"replay":replay,"inspect":inspected,
              "cold_restore_verification":{"live_checkpoint":live_checkpoint,
                  "uninterrupted_live_clone":expected_probe,"cold_process":cold_probe}})
    return summary


def run(owner_build, output):
    output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=True)
    owner=ResearchOwner(owner_build)
    ndu=ResearchNdu(HERE.parent/"first_passage_cell/NATIVE_BUILD.json")
    specifications={"answer_then_stop":{},"budget_stop":{"budget":1,"answer_index":3},
                    "cancellation":{"cancel_after_reads":1,"answer_index":3},
                    "refractory":{"initial_refractory":True,"answer_index":0},
                    "risk_stop":{"initial_level":0.001,"answer_index":0},
                    "deadline_stop":{"deadline_us":0},"natural_event":{"natural_event":True,"answer_index":0}}
    results=[execute_case(name,spec,output,owner,ndu) for name,spec in specifications.items()]
    checks={"answer_then_stop":results[0]["found"] and results[0]["source_reads"]==2,
            "budget_stop":results[1]["source_reads"]==1,
            "cancellation":results[2]["source_reads"]==1 and results[2]["terminal"]=="Cancelled",
            "refractory":results[3]["actions"][0]=="Wait" and results[3]["source_reads"]==1,
            "risk_stop":results[4]["source_reads"]==0,
            "deadline_stop":results[5]["source_reads"]==0,
            "natural_event":results[6]["event_count"]>=1 and results[6]["actions"][0]=="Wait",
            "cold_fpt_restore_exact":all(row["cold_fpt_restore_exact"] for row in results),
            "no_budget_overrun":all(row["spent"]<=row["read_budget"] for row in results),
            "replay_no_new_reads":all(row["replay_source_reads"]==0 for row in results)}
    report={"schema":"hepta.fpt-adaptive.native-execution.v1","checks":checks,"cases":results,
            "native_ndu_calls":ndu.calls,"native_owner_build":owner.build,
            "old_ndu_binary_sha256":ndu.binary_sha256,"scientific_scope":"mechanistic execution and recovery fixtures, not efficacy evidence",
            "remaining_boundary":"native V1 owns sparse checkpoint; complete FPT/post-I/O state remains a bound research sidecar",
            "production_activation":False,"passed":all(checks.values())}
    save_once(output/"NATIVE_EXECUTION.json",report)
    if not report["passed"]:
        raise AssertionError(checks)
    return report


def checkpoint_probe(path):
    checkpoint=json.loads(Path(path).read_text())
    cell=FirstPassageCell.from_checkpoint(checkpoint,checkpoint["payload"]["model_digest"])
    return continuation_probe(cell)


def continuation_probe(cell):
    restored=cell.checkpoint()
    transition=cell.advance(0.02,(0,0))
    return {"restored":restored,"shadow_next_transition":transition,"shadow_next_checkpoint":cell.checkpoint(),
            "scope":"independent simulation restore probe; no stopped task action is reexecuted"}


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--owner-build",type=Path)
    parser.add_argument("--output",type=Path)
    parser.add_argument("--restore-checkpoint",type=Path)
    args=parser.parse_args()
    if args.restore_checkpoint:
        print(canonical(checkpoint_probe(args.restore_checkpoint)).decode())
    else:
        if args.owner_build is None or args.output is None:
            parser.error("--owner-build and --output are required for execution")
        report=run(args.owner_build,args.output)
        print(json.dumps({"checks":report["checks"],"cases":report["cases"],"native_ndu_calls":report["native_ndu_calls"]},indent=2))
