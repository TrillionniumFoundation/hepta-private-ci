"""Choose using the real actor's base-policy tail under its fitted belief.

The caller supplies no true world, evaluator posterior or unread observation.
Scores force one action and follow the ORIGINAL value policy thereafter.  During
actual execution this scoring is recomputed at every prefix.  Its scores are
therefore not Qpi of the new receding policy, and local fitted improvement is not
a global true-world policy-improvement guarantee.
"""

from ..audit import clone_actor
from ..upstream.data import encode_observation
from ..upstream.task_value import choose_values


def choose_rollout(model, fitted_planner, schedule, budget):
    if len(schedule)>3:
        raise ValueError("This registered rollout candidate supports at most three intervals")
    world=fitted_planner
    p,times,budget=world._inputs(model.current,schedule,budget)

    def force(action,mass,actor,clock,reads):
        if action.startswith("STOP"):
            return float(mass@world.reward[:,int(action[-1])])
        dt,rest=clock[0],clock[1:]
        successor=mass@world.R if action=="RESET" else mass
        successor=successor@world._transition(dt)
        value=-float(mass.sum())*(world.latency_price*dt+(world.reset_cost if action=="RESET" else 0.))
        if action=="READ":
            value-=world.read_multiplier*float(successor@world.read_cost)
        tokens=range(world.E.shape[1]) if action=="READ" else (-1,)
        for token in tokens:
            branch_mass=successor*world.E[:,token] if token>=0 else successor
            if branch_mass.sum()<=0:
                continue
            branch=clone_actor(actor)
            branch.step(encode_observation(token,dt,action=="RESET"))
            next_reads=reads-(action=="READ")
            selected=world.choose(branch.current,rest,next_reads)
            value+=force(selected,branch_mass,branch,rest,next_reads)
        return value

    scores={action:force(action,p,model,times,budget)
            for action in world.legal_actions(times,budget)}
    return choose_values(scores),scores
