"""Real-file inference with initial STOP and forkable, charged prefix snapshots.

Linux research runtime. A measured CPU/wall ledger is not a worst-case deadline
guarantee. Selected parameters are immutable; feedback is public consistency,
not a new independent observation. Prefix replay is never charged a second time.
"""

from dataclasses import dataclass, replace
import json
import math
from pathlib import Path
import time

import torch

from ..contract import digest
from ..media import write_read
from ..model import ACTIONS, tensor_digest
from ..runtime import Episode, ScoreTerm, cpu_seconds
from .model import State
from .profile import HORIZON, INITIAL_BUDGET, TARIFF, make_profile


def _clock():
    return cpu_seconds(), time.perf_counter()


def _charge(start, service):
    now = _clock()
    cpu, wall = now[0] - start[0], now[1] - start[1]
    return {"cpu_seconds": cpu, "wall_seconds": wall, "service_fee": TARIFF.get(service, 0.0),
            "amount": cpu * TARIFF["cpu_second"] + wall * TARIFF["wall_second"] + TARIFF.get(service, 0.0)}


def _copy_tree(value, detach):
    if torch.is_tensor(value):
        return value.detach().clone() if detach else value.clone()
    if isinstance(value, list):
        return [_copy_tree(x, detach) for x in value]
    if isinstance(value, dict):
        return {k: _copy_tree(v, detach) for k, v in value.items()}
    return value


@dataclass(frozen=True)
class Snapshot:
    state: State
    budget: float
    prefix_cost: float
    events: tuple
    model_hash: str
    input_hash: str
    profile_hash: str
    state_hash: str
    actor_rng: torch.Tensor
    emission_rng: torch.Tensor

    @property
    def digest(self):
        return digest({"state": self.state_hash, "budget": self.budget, "cost": self.prefix_cost,
                       "events": self.events, "model": self.model_hash, "input": self.input_hash,
                       "profile": self.profile_hash,
                       "rng": tensor_digest((self.actor_rng, self.emission_rng))})


def clone_snapshot(snapshot, *, detach=True):
    state = State(**{k: _copy_tree(v, detach) for k, v in vars(snapshot.state).items()})
    return replace(snapshot, state=state, events=tuple(dict(e) for e in snapshot.events),
                   actor_rng=snapshot.actor_rng.clone(), emission_rng=snapshot.emission_rng.clone())


def with_rng(snapshot, seed):
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError("A nonnegative signed-64 seed is required")
    return replace(snapshot, actor_rng=torch.Generator().manual_seed(seed).get_state(),
                   emission_rng=torch.Generator().manual_seed(seed ^ 0x5EED1234).get_state())


def _check(snapshot, model, public, profile):
    if (snapshot.profile_hash != profile.digest or snapshot.input_hash != tensor_digest(public)
            or snapshot.model_hash != tensor_digest(model.state_dict())
            or snapshot.state_hash != tensor_digest(snapshot.state.tensors())):
        raise ValueError("Snapshot content, model, input or profile changed")
    charge = math.fsum(e["amount"] for e in snapshot.events)
    if (not math.isfinite(snapshot.budget) or not math.isfinite(charge)
            or abs(charge - snapshot.prefix_cost) > 1e-10
            or abs(snapshot.budget + charge - profile.initial_budget) > 1e-10):
        raise ValueError("Snapshot budget does not reconcile with its complete prefix")


def start_snapshot(model, public, *, seed, context_id="", source_id="", profile=None):
    profile = profile or make_profile()
    started = _clock()
    model_hash, input_hash = tensor_digest(model.state_dict()), tensor_digest(public)
    state = model.encode(public)
    if len(state.shared) != 1:
        raise ValueError("One actual-output episode is required")
    state_hash = tensor_digest(state.tensors())
    event = {"action": "encode", "before_state": None, "after_state": state_hash,
             "context_id": context_id, "source_id": source_id, **_charge(started, "encode")}
    snapshot = Snapshot(state, profile.initial_budget - event["amount"], event["amount"],
                        (event,), model_hash, input_hash, profile.digest, state_hash,
                        torch.empty(0, dtype=torch.uint8), torch.empty(0, dtype=torch.uint8))
    return with_rng(snapshot, seed)


def advance_snapshot(model, public, snapshot, action, *, profile=None, _started=None):
    profile = profile or make_profile()
    started = _started or _clock()
    if (snapshot.state.stopped or action not in ACTIONS
            or snapshot.state.steps >= profile.horizon and action != "stop"):
        raise ValueError("Action is outside the remaining legal horizon")
    before = tensor_digest(snapshot.state.tensors())
    if before != snapshot.state_hash or tensor_digest(public) != snapshot.input_hash:
        raise ValueError("Prefix or public observation mutated before continuation")
    state, _ = model.advance(snapshot.state, action, public)
    state_hash = tensor_digest(state.tensors())
    event = {"action": action, "before_state": before, "after_state": state_hash,
             "before_budget": snapshot.budget, "step": snapshot.state.steps,
             "content_revision": state.content_revision, "verified_revision": state.verified_revision,
             **_charge(started, action)}
    return replace(snapshot, state=state, state_hash=state_hash,
                   budget=snapshot.budget - event["amount"],
                   prefix_cost=snapshot.prefix_cost + event["amount"], events=snapshot.events + (event,))


def _legal_law(model, snapshot, profile):
    law, value = model.policy(snapshot.state, snapshot.budget / profile.initial_budget, profile.horizon)
    legal = torch.isfinite(law)
    reserve = TARIFF["delivery"] + TARIFF["stop"]
    for i, action in enumerate(ACTIONS[:-1]):
        if snapshot.budget < TARIFF[action] + reserve:
            legal[:, i] = False
    law = law.masked_fill(~legal, -torch.inf)
    return law - torch.logsumexp(law, -1, keepdim=True), value


def execute(model, public, observe, directory, *, seed, context_id, source_id,
            profile=None, strategy="dynamic", prefix=(), initial_snapshot=None,
            fixed_actions=("shared", "image", "audio", "video", "text", "stop"),
            deterministic_emission=False):
    """Continue exactly one snapshot; forced prefix indices are suffix-relative.

    `stop` means execute the supplied prefix, then deliver immediately.
    `dynamic` samples the actual actor law; greedy/fixed/forced actions have no
    actor score. observe is called only after reopening actual output files.
    """
    if strategy not in {"dynamic", "greedy", "fixed", "stop"}:
        raise ValueError("Unknown executed policy")
    if (any(a not in ACTIONS for a in prefix)
            or "stop" in prefix and prefix.index("stop") != len(prefix) - 1):
        raise ValueError("Invalid forced continuation")
    profile = profile or make_profile()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    begun = _clock()
    if initial_snapshot is None:
        snapshot = start_snapshot(model, public, seed=seed, context_id=context_id,
                                  source_id=source_id, profile=profile)
        inherited_cost = 0.0
    else:
        snapshot = clone_snapshot(initial_snapshot, detach=not torch.is_grad_enabled())
        inherited_cost = snapshot.prefix_cost
    _check(snapshot, model, public, profile)
    if snapshot.state.stopped:
        raise ValueError("A terminal snapshot cannot be delivered twice")
    origin, original_events = snapshot.digest, len(snapshot.events)
    actor_rng, emission_rng = torch.Generator(), torch.Generator()
    actor_rng.set_state(snapshot.actor_rng); emission_rng.set_state(snapshot.emission_rng)
    score = snapshot.state.shared.new_zeros(())
    values, costs_before, terms, actions = [], [], [], []
    observed, artifacts, failure = -1.0, {}, None
    # Charge snapshot clone, identity checks and dispatch setup without charging
    # the already measured first encoding twice.
    setup = _charge(begun, "control")
    if initial_snapshot is None:
        encoding = snapshot.events[0]
        setup["cpu_seconds"] = max(0.0, setup["cpu_seconds"] - encoding["cpu_seconds"])
        setup["wall_seconds"] = max(0.0, setup["wall_seconds"] - encoding["wall_seconds"])
        setup["amount"] = (setup["cpu_seconds"] * TARIFF["cpu_second"]
                           + setup["wall_seconds"] * TARIFF["wall_second"])
    # Rehydration is billed at the first transition boundary. The first action
    # sees the exact frozen budget, irrespective of host-specific restore time.
    # Its resulting successor includes the actual restore cost.
    setup_billed, pending_service = False, "control"
    try:
        for index in range(profile.horizon + 1):
            started = _clock()
            pending_service = "control"
            law, value = _legal_law(model, snapshot, profile)
            values.append(value[0]); costs_before.append(snapshot.prefix_cost)
            forced = index < len(prefix) or strategy in {"fixed", "stop"} or snapshot.state.steps >= profile.horizon
            if index < len(prefix):
                selected = ACTIONS.index(prefix[index])
            elif snapshot.state.steps >= profile.horizon or strategy == "stop":
                selected = ACTIONS.index("stop")
            elif strategy == "fixed":
                selected = ACTIONS.index(fixed_actions[min(index, len(fixed_actions)-1)])
            elif strategy == "greedy":
                selected = int(law.argmax(-1).item())
            else:
                selected = int(torch.multinomial(law.exp(), 1, generator=actor_rng).item())
            if not torch.isfinite(law[0, selected]):
                raise ValueError("Forced or selected action is not legal")
            action = ACTIONS[selected]
            sampled = not forced and strategy == "dynamic"
            if sampled:
                score = score + law[0, selected]
                terms.append(ScoreTerm("action", law[0, selected], value[0].detach(), snapshot.prefix_cost))
            if action == "stop":
                stop_features = model.features(snapshot.state, snapshot.budget / profile.initial_budget).detach()
                stop_value = model.delivery_critic(stop_features)[0, 0]
                stop_cost_origin = snapshot.prefix_cost
            before = snapshot.state_hash
            pending_service = action
            snapshot = advance_snapshot(model, public, snapshot, action, profile=profile, _started=started)
            if index == 0:
                event = dict(snapshot.events[-1])
                for key in ("cpu_seconds", "wall_seconds", "amount"):
                    event[key] += setup[key]
                event["restore_control_cost"] = setup["amount"]
                snapshot = replace(snapshot, budget=snapshot.budget-setup["amount"],
                                   prefix_cost=snapshot.prefix_cost+setup["amount"],
                                   events=snapshot.events[:-1] + (event,))
                setup_billed = True
            actions.append({**snapshot.events[-1], "action": action, "before_sha256": before,
                            "after_sha256": snapshot.state_hash, "selected_probability": float(law[0, selected].exp().detach()),
                            "sampled_actor": sampled})
            started = _clock()
            pending_service = "control"
            if snapshot.budget < 0:
                raise RuntimeError("Measured budget exhausted; no free continuation")
            if snapshot.state.stopped:
                break
        if not snapshot.state.stopped:
            raise RuntimeError("Finite horizon did not execute STOP")
        started = _clock()
        pending_service = "delivery"
        sample, _, emission_score = model.sample(snapshot.state, emission_rng, deterministic=deterministic_emission)
        if not deterministic_emission:
            score = score + emission_score[0]
            terms.append(ScoreTerm("emission", emission_score[0], stop_value.detach(), stop_cost_origin))
        readback, artifacts = write_read(sample, directory / "outputs", profile.audio_rate, profile.frame_ms)
        observed = float(observe(readback))
        if not math.isfinite(observed) or not -1 <= observed <= 1:
            raise ValueError("Independent observation outside the fixed utility domain")
        delivery = {"action": "delivery", **_charge(started, "delivery")}
        snapshot = replace(snapshot, budget=snapshot.budget-delivery["amount"],
                           prefix_cost=snapshot.prefix_cost+delivery["amount"],
                           events=snapshot.events + (delivery,))
        started = _clock()
        pending_service = "control"
        values.append(stop_value); costs_before.append(stop_cost_origin)
        if snapshot.budget < 0:
            raise RuntimeError("Actual delivery exceeded the measured remaining budget")
    except Exception as error:
        # Preserve failed executed work, including any partially written files.
        event = {"action": "failure", "attempted_service": pending_service,
                 **_charge(started, pending_service)}
        if not setup_billed:
            for key in ("cpu_seconds", "wall_seconds", "amount"):
                event[key] += setup[key]
        snapshot = replace(snapshot, budget=snapshot.budget-event["amount"],
                           prefix_cost=snapshot.prefix_cost+event["amount"], events=snapshot.events+(event,))
        failure, observed = f"{type(error).__name__}: {error}", -1.0
    if tensor_digest(model.state_dict()) != snapshot.model_hash:
        raise ValueError("Selected parameters changed during the episode")
    snapshot = replace(snapshot, actor_rng=actor_rng.get_state(), emission_rng=emission_rng.get_state())
    _check(snapshot, model, public, profile)
    record = {"schema": "hepta.joint-generation.actual-trajectory.v3", "source_id": source_id,
              "context_id": context_id, "seed": seed, "profile": profile.to_dict(),
              "profile_sha256": profile.digest, "parameter_snapshot_sha256": snapshot.model_hash,
              "input_sha256": snapshot.input_hash, "initial_snapshot_sha256": origin,
              "inherited_prefix_cost": inherited_cost, "events": list(snapshot.events),
              "actions": actions, "failure": failure, "actual_cost": snapshot.prefix_cost,
              "suffix_cost": snapshot.prefix_cost-inherited_cost, "remaining_budget": snapshot.budget,
              "net_return": observed-snapshot.prefix_cost,
              "outcome": {"delivered_utility": observed, "artifact_sha256": artifacts,
                          "terminal_kind": "failed" if failure else "delivered"},
              "state_sha256": snapshot.state_hash, "rng_sha256": tensor_digest((snapshot.actor_rng, snapshot.emission_rng)),
              "resumed": initial_snapshot is not None, "prefix_event_count": original_events,
              "contract_validated": True, "semantic_qualification": False,
              "policy": strategy, "deterministic_emission": deterministic_emission}
    started = _clock()
    (directory / "AUDIT_DRAFT.json").write_text(json.dumps(record, sort_keys=True, allow_nan=False)+"\n")
    audit = {"action": "audit_draft", **_charge(started, "audit")}
    total = snapshot.prefix_cost + audit["amount"]
    record.update(actual_cost=total, suffix_cost=total-inherited_cost,
                  remaining_budget=profile.initial_budget-total, net_return=observed-total)
    record["events"].append(audit)
    started = _clock()
    (directory / "TRAJECTORY.json").write_text(json.dumps(record, sort_keys=True, indent=2, allow_nan=False)+"\n")
    seal = _charge(started, "seal")
    total += seal["amount"]
    seal.update(action="audit_close", actual_cost_through_seal=total,
                net_return_through_seal=observed-total,
                closure="This sidecar write is included in the outer run cost, not recursively billed")
    record["events"].append(seal)
    record.update(actual_cost=total, suffix_cost=total-inherited_cost,
                  remaining_budget=profile.initial_budget-total, net_return=observed-total)
    record.update(audit_close_wall_seconds=seal["wall_seconds"], audit_close_cpu_seconds=seal["cpu_seconds"],
                  net_with_audit_close=observed-total)
    (directory / "SEAL_COST.json").write_text(json.dumps(seal, sort_keys=True)+"\n")
    suffixes = [observed-(total-cost) for cost in costs_before]
    return Episode(record, observed-total, score, values, suffixes, snapshot.state, [], terms)
