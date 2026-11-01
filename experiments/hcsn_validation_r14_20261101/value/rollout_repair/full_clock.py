"""Exact finite-world evaluation of the ACTUAL policy at every future branch.

Unlike rollout scores, this evaluator recomputes the repaired selector at all
future causal prefixes.  True mass never reaches that selector.  All 27 clock
schedules are later averaged uniformly; there is no latent/tape sampling here.
"""

from itertools import product
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ..audit import clone_actor,choose_actor,state_identity
from ..upstream.cell import Cell
from ..upstream.data import encode_observation
from ..upstream.estimators import restore_model
from ..upstream.task_value import ExactBeliefDP
from .controller import choose_rollout


def expected_policy(world,model,belief,schedule,budget,planner,selector):
    p,times,budget=world._inputs(belief,schedule,budget)
    before=state_identity(model)
    counts=dict(decisions=0,leaves=0)

    def follow(mass,actor,clock,reads):
        counts["decisions"]+=1
        action=selector(actor,planner,clock,reads)
        weight=float(mass.sum())
        if action not in planner.legal_actions(clock,reads):
            raise ValueError("Actual policy selected an illegal action")
        if action.startswith("STOP"):
            counts["leaves"]+=1
            return np.array([mass@world.reward[:,int(action[-1])],weight,0.,0.,0.])
        dt,rest=clock[0],clock[1:]
        successor=mass@world.R if action=="RESET" else mass
        successor=successor@world._transition(dt)
        cost=weight*(world.latency_price*dt+(world.reset_cost if action=="RESET" else 0.))
        if action=="READ":
            cost+=world.read_multiplier*float(successor@world.read_cost)
        result=np.array([-cost,0.,weight*(action=="READ"),weight*(action=="WAIT"),weight*(action=="RESET")])
        for token in (range(world.E.shape[1]) if action=="READ" else (-1,)):
            branch_mass=successor*world.E[:,token] if token>=0 else successor
            if branch_mass.sum()<=0:
                continue
            branch=clone_actor(actor)
            branch.step(encode_observation(token,dt,action=="RESET"))
            result+=follow(branch_mass,branch,rest,reads-(action=="READ"))
        return result

    result=follow(p,model,times,budget)
    if before!=state_identity(model):
        raise AssertionError("Exact policy evaluator mutated the actor")
    if abs(result[1]-1)>2e-10:
        raise AssertionError("Actual policy tree lost leaf mass")
    return dict(utility=float(result[0]),leaf_mass=float(result[1]),expected_reads=float(result[2]),
                expected_waits=float(result[3]),expected_resets=float(result[4]),**counts)


def worker(seed,domain,folder,protocol,value_root):
    start=time.process_time()
    selections=json.loads((value_root/"upstream/CANDIDATE_FREEZE.json").read_text())["selection"]
    ordinary=selections[str(seed)]["kind"]
    payloads={kind:json.loads((value_root/"upstream/checkpoints"/str(seed)/(kind+".json")).read_text())["selected_model"] for kind in (ordinary,"hx_distribution")}
    fitted=restore_model(payloads["hx_distribution"]).build_cell()
    true_cell=Cell();world=ExactBeliefDP(true_cell)
    records=[]
    for arm,(kind,control) in protocol["arms"].items():
        kind=ordinary if kind=="ordinary" else kind
        planner=ExactBeliefDP(fitted)
        model=restore_model(payloads[kind])
        selector=(lambda actor,p,clock,reads:choose_rollout(actor,p,clock,reads)[0]) if control=="actor_rollout_base_tail" else (lambda actor,p,clock,reads,c=control:choose_actor(actor,p,clock,reads,c))
        for clock in product(protocol["domains"][domain],repeat=3):
            model.start(fitted.prior)
            result=expected_policy(world,model,true_cell.prior,clock,2,planner,selector)
            records.append(dict(arm=arm,clock=list(clock),**result))
    result=dict(seed=seed,domain=domain,records=records,clock_distribution="uniform over all 3^3 public schedules",
                source_freeze_sha256=hashlib.sha256((Path(__file__).resolve().parent/"SOURCE_FREEZE.json").read_bytes()).hexdigest(),
                mean_utility={a:float(np.mean([r["utility"] for r in records if r["arm"]==a])) for a in protocol["arms"]},
                max_mass_error=max(abs(r["leaf_mass"]-1) for r in records),body_cpu_seconds=time.process_time()-start,
                scope="Finite true-world root expectation of actual receding policies; every future choice invokes the same actual selector. This is separate from base-tail scoring and from continuous-process validation.")
    (folder/"RESULT.json").write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+"\n")
