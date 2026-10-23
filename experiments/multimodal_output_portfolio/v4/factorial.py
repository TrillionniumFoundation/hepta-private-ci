"""Independent 2x2 heldout attribution contract; NO training is performed here."""
from collections import defaultdict
from dataclasses import dataclass
from math import isfinite

from finite_portfolio import InvalidModel, external_loss


@dataclass(frozen=True)
class ArmRow:
    world_id: str
    training: str  # baseline | ndu
    inference: str  # static | dynamic
    truth: int
    outputs: tuple[int, int, int, int]
    measured_cost: float
    cost_unit: str


def audit_factorial(rows: list[ArmRow]) -> dict:
    """Paired factorial effects and external-loss re-scoring, not a causal proof.

    Raw outputs must come from four actually executed model/policy combinations.
    Caller must independently authenticate world IDs, raw bytes and physical costs.
    """
    if not rows:
        raise InvalidModel('empty observed-output comparison')
    groups = defaultdict(dict)
    allowed = {('baseline', 'static'), ('baseline', 'dynamic'),
               ('ndu', 'static'), ('ndu', 'dynamic')}
    for r in rows:
        key = (r.training, r.inference)
        if not r.world_id or key not in allowed or key in groups[r.world_id]:
            raise InvalidModel('missing identity, unknown arm or duplicate')
        if r.cost_unit not in ('measured_wall_seconds','measured_cpu_seconds',
                               'measured_device_joules'):
            raise InvalidModel('proxy costs cannot prove physical parity')
        if not isfinite(r.measured_cost) or r.measured_cost < 0:
            raise InvalidModel('invalid physical cost')
        external_loss(r.outputs, r.truth)
        groups[r.world_id][key] = r
    effects, cost_differences = [], []
    for world_id, arms in groups.items():
        if set(arms) != allowed:
            raise InvalidModel(f'missing factorial arms: {world_id}')
        if len({a.truth for a in arms.values()}) != 1:
            raise InvalidModel('world truth changes between arms')
        if len({a.cost_unit for a in arms.values()}) != 1:
            raise InvalidModel('incomparable cost units')
        loss = {k: external_loss(a.outputs, a.truth) for k, a in arms.items()}
        # Difference-in-differences for outcome loss, not internal utility.
        effects.append((loss['ndu','dynamic'] - loss['ndu','static'])
                       - (loss['baseline','dynamic'] - loss['baseline','static']))
        cost_differences.append((arms['ndu','dynamic'].measured_cost -
                                 arms['baseline','static'].measured_cost))
    return {
        'worlds': len(groups),
        'external_loss_interaction': sum(effects) / len(effects),
        'mean_joint_vs_baseline_cost_delta': sum(cost_differences) / len(cost_differences),
        'claim': 'paired descriptive contrast only; independently observed natural neural outcomes required',
    }
