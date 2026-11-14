"""Read-only reachable-budget and streaming checks for root evaluate.py."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
import numpy as np
import torch

from rrsnn_experiments.resource_env import Scenario,Oracle,legal_actions,exogenous,transition
from ..evaluate import OracleTable,evaluate,load_scenarios
from ..policy import Policy

OUT=Path(__file__).resolve().parent/"results"
ROOT=Path(__file__).resolve().parents[1]


def build_like_evaluator(s):
    maximum=s.budget+s.refill_amount
    values=np.zeros((len(s.events()),16,maximum+1),dtype=np.float64)
    filled=np.zeros_like(values,dtype=bool)
    table=OracleTable(s,values)
    for index in range(len(s.events())-1,-1,-1):
        for live in range(16):
            for before in range(maximum+1):
                budget,_,_=exogenous(s,s.events()[index],before)
                if budget>maximum:continue
                values[index,live,before]=np.max(table.q_values(index,live,budget))
                filled[index,live,before]=True
    return table,filled


def reachable_comparison(s):
    table,filled=build_like_evaluator(s);original=Oracle(s)
    frontier={(15,s.budget)};checked=0;max_error=0.;q_error=0.;max_budget=0
    for index,t in enumerate(s.events()):
        following=set()
        for live,before in frontier:
            assert filled[index,live,before]
            value=table.value(index,live,before)
            max_error=max(max_error,abs(value-original.value(index,live,before)))
            budget,_,_=exogenous(s,t,before);max_budget=max(max_budget,budget)
            assert budget<=s.budget+s.refill_amount
            if index==len(s.events())-1:
                checked+=1;continue
            valid,_=legal_actions(s,t,live,budget)
            qs=table.q_values(index,live,budget);qo=original.q_values(index,live,budget)
            q_error=max(q_error,float(np.max(np.abs(qs[valid]-qo[valid]))))
            for action in np.flatnonzero(valid):
                l2,b2,_,_=transition(s,t,live,budget,int(action))
                assert filled[index+1,l2,b2],"A reachable transition read a skipped placeholder"
                following.add((l2,b2))
            checked+=1
        frontier=following
    assert max_error<1e-10 and q_error<1e-10
    return table,{"reachable_states_checked":checked,"value_max_error":max_error,
                  "legal_q_max_error":q_error,"maximum_reachable_budget":max_budget,
                  "table_bound":s.budget+s.refill_amount,
                  "skipped_placeholders_never_read_by_reachable_states":True}


class FlatScoringOracle:
    """Change evaluation labels only; the actor must remain unchanged."""
    def __init__(self,base):self.base=base;self.s=base.s;self.times=base.times
    def value(self,*args):return self.base.value(*args)
    def q_values(self,index,live,budget):
        valid,_=legal_actions(self.s,self.times[index],live,budget)
        return np.where(valid,0.,-np.inf)


def main():
    torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.manual_seed(89301)
    began=time.perf_counter();source=ROOT/"evaluate.py"
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    scenarios=load_scenarios("test")[:4]+load_scenarios("shift")[:4]
    scenarios += [
        Scenario(values=(1.,.7,.5,.3),deadlines=(1.,1.,3.,3.),budget=0,shock_amount=2,refill_amount=2),
        Scenario(values=(1.,.7,.5,.3),deadlines=(2.,2.,2.,2.),budget=4,shock_amount=3,refill_amount=2,shock_time=1.5,refill_time=1.5),
        Scenario(values=(1.,.7,.5,.3),deadlines=(1.,2.,2.,3.),budget=1,shock_amount=0,refill_amount=2,refill_time=4.),
    ]
    tables=[];checks=[]
    for s in scenarios:
        table,check=reachable_comparison(s);tables.append(table);checks.append(check)
    model=Policy("ctrnn")
    batched=evaluate(model,scenarios,tables,mode="density",keep_trace=True)
    scalar=[evaluate(model,[s],[o],mode="density",keep_trace=True) for s,o in zip(scenarios,tables)]
    assert batched["episode_utility"]==[r["episode_utility"][0] for r in scalar]
    assert batched["episode_budget_spent"]==[r["episode_budget_spent"][0] for r in scalar]
    assert batched["traces"]==[r["traces"][0] for r in scalar]
    latent_error=float(np.max(np.abs(np.array(batched["terminal_latents"])-
                                  np.array([r["terminal_latents"][0] for r in scalar]))))
    assert latent_error<2e-6
    changed=evaluate(model,scenarios,[FlatScoringOracle(o) for o in tables],mode="density",keep_trace=True)
    assert changed["episode_utility"]==batched["episode_utility"]
    assert changed["traces"]==batched["traces"]
    # Inspect any completed persisted caches without writing or triggering them.
    provenance=[]
    for name in ("test","shift","paired"):
        proof=ROOT/"data"/f"{name}_oracle_provenance.json"
        if not proof.exists():
            provenance.append({"name":name,"completed_cache_present":False});continue
        record=json.loads(proof.read_text())
        sp=ROOT/"data"/f"{name}_scenarios.json";cp=ROOT/"data"/f"{name}_oracle.npz"
        matches=(hashlib.sha256(sp.read_bytes()).hexdigest()==record["source_scenario_sha256"] and
                 hashlib.sha256(cp.read_bytes()).hexdigest()==record["cache_sha256"])
        assert matches
        provenance.append({"name":name,"completed_cache_present":True,"provenance_hashes_match":matches})
    final_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    result={"schema":"rrsnn.independent-streaming-oracle-audit.v1","source_sha256":source_hash,
        "source_unchanged_during_audit":source_hash==final_hash,
        "scenarios":len(scenarios),"reachable_states_checked":sum(r["reachable_states_checked"] for r in checks),
        "budget_checks":checks,"batched_vs_singleton_action_utility_ledger_equal":True,
        "batched_vs_singleton_terminal_latent_error":latent_error,
        "posthoc_oracle_label_perturbation_changes_no_actions_or_rewards":True,
        "ragged_event_grids_exercised":sorted(set(len(s.events()) for s in scenarios)),
        "persisted_cache_provenance":provenance,
        "budget_argument":"Before the single refill, any initial-reachable budget is<=B0. After it, budget<=B0+refill. Actions and shocks never increase budget. Therefore skipped table entries whose refill exceeds this global bound are unreachable and their zero placeholders cannot affect initial-reachable Bellman values.",
        "review_notes":["Streaming passes each row's true elapsed time, uses initialdt0, and masks completed rows. New observations update controls only after prior-interval propagation.",
                        "Oracle q-values enter after actor action selection; changing all labels to equal-valid leaves action/reward traces unchanged.",
                        "Count semantics distinguish actual CTMC/Brownian events from conditional expected counts in endpoint mode.",
                        "A persisted cache should be bound to its scenario file and table shape/hash on load. This audit checks completed provenance when available; missing caches are not fabricated.",
                        "No claim that this read-only audit proves every possible future scenario schema correct. The global-budget argument relies on exactly one nonnegative refill and no other budget-increasing actions."],
        "elapsed_seconds":time.perf_counter()-began}
    assert result["source_unchanged_during_audit"]
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"evaluator_streaming_audit.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({"passed":True,"states":result["reachable_states_checked"],
                      "seconds":result["elapsed_seconds"]}),flush=True)


if __name__=="__main__":main()
