"""CPU-bounded head fitting with repeated, detached policy-visit feedback.

This Linux research runner freezes each fit's initial physical cell parameters.
The timer covers candidate setup, feature encoding, collection and optimization.
Only complete optimizer updates can become the returned model.
"""
from contextlib import contextmanager
import hashlib
import json
import math
import signal
import time

import numpy as np
import torch
import torch.nn.functional as F

from ..digital_mechanisms_20261101.execution import occupancy_key, run_episode
from .factors import FactorPolicy, FactorRuntime


class CpuExpired(BaseException):
    """A planned resource stop, distinct from an unsuccessful scientific fit."""


@contextmanager
def cpu_deadline(seconds):
    """Use periodic wakeups, with process_time as the only deadline clock.

    ITIMER_PROF ticks can disagree with process_time under CPU contention.
    An early wakeup must return without interrupting or restarting the work.
    Native calls may defer Python signal delivery; actual overrun is therefore
    still measured and rejected by the caller's registered CPU tolerance.
    """
    if not hasattr(signal, "ITIMER_PROF") or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("positive CPU deadline and ITIMER_PROF platform required")
    if signal.getitimer(signal.ITIMER_PROF) != (0., 0.):
        raise RuntimeError("another process CPU timer is already active")
    previous = signal.getsignal(signal.SIGPROF)
    deadline = time.process_time() + seconds

    def expired(signum, frame):
        if time.process_time() >= deadline:
            raise CpuExpired("registered process CPU budget reached")

    signal.signal(signal.SIGPROF, expired)
    try:
        signal.setitimer(signal.ITIMER_PROF, .01, .01)
        yield
    finally:
        signal.setitimer(signal.ITIMER_PROF, 0.)
        signal.signal(signal.SIGPROF, previous)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def encode_rows(policy, rows, cache):
    """Fixed dynamics permit reuse without detaching any trained parameter.

    Independent behavior uses its exact conditional prefix law. Policy visits
    instead condition on the actual observed latent index. Neither is an
    autonomous-policy path probability or a policy-gradient estimator.
    """
    if policy.cell is not None and policy.cell.raw.requires_grad:
        raise ValueError("cached head supervision requires explicitly frozen physics")
    inputs, masses, support = [], [], []
    with torch.no_grad():
        for row in rows:
            x = policy.latent_inputs(row["public"], row["state"], cache)
            if "latent_index" in row:
                index = int(row["latent_index"])
                if not 0 <= index < len(x):
                    raise ValueError("latent index outside representation")
                mass = x.new_zeros(len(x))
                mass[index] = 1.
            else:
                mass = policy.prefix_mass(row["prefix"], cache)
            if (not bool(torch.isfinite(x).all() and torch.isfinite(mass).all())
                    or float(mass.min()) < -2e-10 or abs(float(mass.sum()) - 1) > 2e-9):
                raise FloatingPointError("invalid fixed-dynamics supervision")
            inputs.append(x.detach())
            masses.append(mass.detach())
            support.append(dict(public=row["public"], state=row["state"],
                                latent_support=torch.nonzero(mass > 0).flatten().tolist()))
    x = torch.stack(inputs)
    return dict(x=x, mass=torch.stack(masses),
                target=x.new_tensor([r["q"] for r in rows]),
                mask=torch.tensor([r["legal"] for r in rows], dtype=torch.bool),
                belief=x.new_tensor([r["posterior"] for r in rows])), support


def batch_loss(policy, batch, protocol):
    output = policy(batch["x"])
    target, mask, mass = batch["target"], batch["mask"], batch["mass"]
    error = (output[..., :6] - target[:, None]).square()
    continuation = mask.clone()
    continuation[:, [0, 4, 5]] = False
    terminal = mask & ~continuation
    q_loss = ((error * continuation[:, None]).sum(-1)
              / continuation.sum(-1).clamp_min(1)[:, None])
    terminal_loss = ((error * terminal[:, None]).sum(-1)
                     / terminal.sum(-1).clamp_min(1)[:, None])
    belief_loss = F.binary_cross_entropy_with_logits(
        output[..., 6], batch["belief"][:, None].expand_as(output[..., 6]), reduction="none")
    best = target.masked_fill(~mask, -torch.inf).argmax(-1)
    best_target = target.gather(1, best[:, None])
    target_gap = best_target - target
    comparable = mask & (target_gap > 1e-12)
    best_prediction = output[..., :6].gather(
        2, best[:, None, None].expand(-1, output.shape[1], 1))
    desired_gap = target_gap.clamp(0, protocol.get("ranking_margin", .02))
    ranking = (desired_gap[:, None] - (best_prediction - output[..., :6])).clamp_min(0).square()
    ranking = ((ranking * comparable[:, None]).sum(-1)
               / comparable.sum(-1).clamp_min(1)[:, None])
    loss = (mass * (
        protocol.get("continuation_q_weight", 1.) * q_loss
        + protocol.get("terminal_q_weight", 1.) * terminal_loss
        + protocol["belief_loss_weight"] * belief_loss
        + protocol.get("ranking_loss_weight", .2) * ranking)).sum(-1).mean()
    if not bool(torch.isfinite(loss)):
        raise FloatingPointError("nonfinite head objective")
    return loss


class HeadAdamW:
    """Small explicit AdamW update with no optimizer import/setup outside budget.

    The formula is the non-AMSGrad, non-capturable AdamW equation. Every updated
    parameter and both moments are written only inside the candidate transaction.
    Interrupted moments are discarded because interrupted fits do not resume.
    """
    def __init__(self, parameters, learning_rate, weight_decay):
        self.parameters = list(parameters)
        self.lr, self.decay, self.step_count = learning_rate, weight_decay, 0
        self.m = [torch.zeros_like(p) for p in self.parameters]
        self.v = [torch.zeros_like(p) for p in self.parameters]

    def step(self):
        self.step_count += 1
        with torch.no_grad():
            for p, m, v in zip(self.parameters, self.m, self.v):
                m.mul_(.9).add_(p.grad, alpha=.1)
                v.mul_(.999).addcmul_(p.grad, p.grad, value=.001)
                denominator = v.sqrt() / math.sqrt(1 - .999 ** self.step_count) + 1e-8
                p.mul_(1 - self.lr * self.decay)
                p.addcdiv_(m, denominator, value=-self.lr / (1 - .9 ** self.step_count))


def fit_candidate(spec, fit, data, adapter, protocol):
    """Return the last completed model, every attempt, and actual CPU compliance."""
    start, wall = time.process_time(), time.perf_counter()
    budget = float(protocol["training_cpu_seconds"])
    tolerance = float(protocol["cpu_tolerance_seconds"])
    reserve = float(protocol.get("cpu_finalize_reserve_seconds", .03))
    if not 0 < reserve < budget or not 0 < tolerance < budget:
        raise ValueError("invalid registered CPU tolerances")
    fractions = protocol.get("feedback_round_fractions", [.2, .45, .7])
    if len(fractions) < 3 or fractions != sorted(set(fractions)) or not all(0 < f < 1 for f in fractions):
        raise ValueError("multi feedback requires at least three ordered fractions")
    total_worlds = int(protocol.get("feedback_worlds_total", 12))
    max_visits = int(protocol.get("max_visits", 512))
    mode = spec["feedback"]
    if mode not in ("off", "single", "multi") or total_worlds < len(fractions) or max_visits < 1:
        raise ValueError("invalid feedback design")
    schedule = ([] if mode == "off" else [.5] if mode == "single" else fractions)
    counts = [total_worlds // len(schedule) + (i < total_worlds % len(schedule))
              for i in range(len(schedule))] if schedule else []
    visits, visit_rounds, updates, failures, interruptions = [], [], [], [], []
    phases = {k: 0. for k in ("setup", "behavior_encoding", "collection", "visit_encoding", "optimization")}
    behavior_support, initial, committed, policy = [], None, None, None
    current_phase, phase_start = "setup", start
    batch_digest = hashlib.sha256()
    stop_reason = None
    try:
        with cpu_deadline(budget - reserve):
            policy = FactorPolicy.from_spec(spec, fit)
            if policy.cell is not None:
                policy.cell.raw.requires_grad_(False)
            trained = [p for p in policy.parameters() if p.requires_grad]
            optimizer = HeadAdamW(trained, protocol["learning_rate"], protocol["weight_decay"])
            initial = {k: v.detach().clone() for k, v in policy.state_dict().items()}
            committed = (initial, 0, np.zeros(len(data["train"]["rows"]), dtype=np.int64),
                         np.zeros(max_visits, dtype=np.int64))
            rng = np.random.default_rng(protocol["batch_seed_base"] + fit)
            phases[current_phase] += time.process_time() - phase_start
            current_phase, phase_start = "behavior_encoding", time.process_time()
            cache = {}
            encoded, behavior_support = encode_rows(policy, data["train"]["rows"], cache)
            behavior_count = len(data["train"]["rows"])
            phases[current_phase] += time.process_time() - phase_start
            current_phase, phase_start = "optimization", time.process_time()
            next_round, world_cursor = 0, 0
            visited_encoded = None
            while True:
                elapsed = time.process_time() - start
                if next_round < len(schedule) and elapsed >= schedule[next_round] * budget:
                    phases[current_phase] += time.process_time() - phase_start
                    current_phase, phase_start = "collection", time.process_time()
                    round_id = next_round + 1
                    snapshot = policy.export()
                    record = dict(round_id=round_id, snapshot_sha256=digest(snapshot),
                                  snapshot=snapshot, start_update=committed[1],
                                  start_cpu_seconds=elapsed, planned_worlds=counts[next_round],
                                  rows=[], episodes=[], complete_worlds=0, status="in_progress")
                    visit_rounds.append(record)
                    runtime = FactorRuntime(policy)
                    for _ in range(counts[next_round]):
                        if len(visits) + 7 > max_visits:
                            record["status"] = "visit_memory_limit"
                            break
                        source = data["train_cohort"]["records"][world_cursor % len(data["train_cohort"]["records"])]
                        execution_seed = protocol["occupancy_seed_base"] + fit * 100000 + world_cursor
                        record["attempted_world"] = source["id"]
                        record["attempted_seed"] = execution_seed
                        episode, rows = run_episode(runtime, source, adapter, data["confusion"],
                                                    "value", execution_seed, supervised=True)
                        for row in rows:
                            row.update(round_id=round_id, snapshot_sha256=record["snapshot_sha256"])
                        # Commit the complete episode receipt together. Finalization
                        # reconstructs visits if interrupted before its cache update.
                        record.update(rows=record["rows"] + rows,
                                      episodes=record["episodes"] + [episode],
                                      complete_worlds=len(record["episodes"]) + 1)
                        visits.extend(rows)
                        world_cursor += 1
                    record.update(status="complete" if record["status"] == "in_progress" else record["status"],
                                  end_cpu_seconds=time.process_time() - start,
                                  complete_worlds=len(record["episodes"]), end_update=committed[1])
                    phases[current_phase] += time.process_time() - phase_start
                    current_phase, phase_start = "visit_encoding", time.process_time()
                    if visits:
                        visited_encoded, _ = encode_rows(policy, visits, cache)
                    phases[current_phase] += time.process_time() - phase_start
                    current_phase, phase_start = "optimization", time.process_time()
                    next_round += 1
                    continue
                size = int(protocol["batch_states"])
                off_count = (size if visited_encoded is None else
                             max(1, min(size - 1, int(size * protocol.get("offpolicy_fraction", .5)))))
                behavior_indices = rng.integers(0, behavior_count, off_count)
                visit_indices = np.empty(0, dtype=np.int64)
                batch_digest.update(behavior_indices.astype("<i8").tobytes())
                batch = {k: v[behavior_indices] for k, v in encoded.items()}
                if visited_encoded is not None:
                    visit_indices = rng.integers(0, len(visits), size - off_count)
                    batch_digest.update(visit_indices.astype("<i8").tobytes())
                    batch = {k: torch.cat((v, visited_encoded[k][visit_indices])) for k, v in batch.items()}
                for parameter in trained:
                    parameter.grad = None
                loss = batch_loss(policy, batch, protocol)
                loss.backward()
                if any(p.grad is None or not bool(torch.isfinite(p.grad).all()) for p in trained):
                    raise FloatingPointError("nonfinite/missing head gradient")
                norm = float(torch.nn.utils.clip_grad_norm_(trained, protocol["gradient_clip"]))
                optimizer.step()
                snapshot = {k: v.detach().clone() for k, v in policy.state_dict().items()}
                behavior_use, visit_use = committed[2].copy(), committed[3].copy()
                behavior_use[np.unique(behavior_indices)] += 1
                visit_use[np.unique(visit_indices)] += 1
                updates.append(dict(update=committed[1] + 1, loss=float(loss.detach()), gradient_norm=norm,
                                    visited_rows=len(visits), mixed_realized_records=size - off_count,
                                    cumulative_cpu_seconds=time.process_time() - start))
                committed = (snapshot, len(updates), behavior_use, visit_use)
    except CpuExpired as error:
        stop_reason = "cpu_deadline"
        interruptions.append(dict(phase=current_phase, reason=str(error),
                                  cpu_seconds=time.process_time() - start,
                                  last_complete_update=0 if committed is None else committed[1]))
    except Exception as error:
        stop_reason = "exception"
        failures.append(dict(phase=current_phase, kind=type(error).__name__, message=str(error),
                             cpu_seconds=time.process_time() - start))
    phases[current_phase] += time.process_time() - phase_start
    finalize_start = time.process_time()
    if policy is None or committed is None:
        raise RuntimeError(f"candidate setup failed with retained receipt: {failures or interruptions}")
    policy.load_state_dict(committed[0])
    updates = updates[:committed[1]]
    visits = [row for record in visit_rounds for row in record["rows"]]
    behavior_support = [dict(row, supervised_updates=int(count))
                        for row, count in zip(behavior_support, committed[2]) if count > 0]
    for row, count in zip(visits, committed[3]):
        row["supervised_updates"] = int(count)
    for record in visit_rounds:
        record["complete_worlds"] = len(record["episodes"])
        record.setdefault("end_cpu_seconds", time.process_time() - start)
        record.setdefault("end_update", committed[1])
        if record["status"] == "in_progress":
            record["status"] = "interrupted"
        record["supervised_rows"] = [row for row in record["rows"] if row["supervised_updates"] > 0]
    artifact = policy.export()
    changes = {k: float(torch.linalg.vector_norm(v.detach() - initial[k]))
               for k, v in policy.state_dict().items()}
    complete_rounds = sum(r["status"] == "complete" and r["complete_worlds"] > 0 for r in visit_rounds)
    supervised_rounds = sum(bool(r["supervised_rows"]) for r in visit_rounds)
    receipt = dict(schema="digital-feedback-training-v1", spec=spec, fit=fit,
                   physical_parameters_frozen=True, optimizer="explicit AdamW beta=.9,.999 eps=1e-8",
                   training_cpu_budget=budget, cpu_tolerance_seconds=tolerance,
                   cpu_finalize_reserve_seconds=reserve, stop_reason=stop_reason,
                   optimizer_updates=len(updates), updates=updates, failures=failures,
                   interruptions=interruptions, minibatch_attempt_sha256=batch_digest.hexdigest(),
                   minibatch_digest_scope="includes attempted interrupted minibatch; support counts only committed updates",
                   behavior_records=len(data["train"]["rows"]),
                   behavior_rows_sha256=digest(data["train"]["rows"]),
                   behavior_rows_with_support=behavior_support,
                   behavior_supervised_update_counts=committed[2].tolist(),
                   visit_supervised_update_counts=committed[3][:len(visits)].tolist(),
                   realized_visit_records=len(visits), visited_rows_sha256=digest(visits),
                   visit_rounds=visit_rounds, visit_collection_count=len(visit_rounds),
                   planned_feedback_rounds=len(schedule), complete_feedback_rounds=complete_rounds,
                   supervised_feedback_rounds=supervised_rounds,
                   behavior_occupancy_keys=sorted({occupancy_key(r["state"]) for r in data["train"]["rows"]}),
                   augmented_occupancy_keys=sorted({occupancy_key(r["state"]) for r in visits}),
                   capacity=policy.capacity_report(), parameter_shift_l2=changes,
                   final_update_selected=True, validation_used_for_checkpoint_selection=False,
                   policy_gradient_claim=False, budget_scope="candidate setup+encoding+collection+optimization+finalization",
                   excluded_shared_cost="shared data/content setup and returned-artifact serialization; worker measures separately",
                   returned_model_sha256=digest(artifact), max_visits=max_visits)
    elapsed = time.process_time() - start
    receipt.update(candidate_cpu_seconds=elapsed, learning_cpu_seconds=elapsed,
                   candidate_wall_seconds=time.perf_counter() - wall,
                   phase_cpu_seconds=phases, finalize_cpu_seconds=time.process_time() - finalize_start,
                   cpu_budget_overshoot=max(0., elapsed - budget),
                   cpu_budget_undershoot=max(0., budget - elapsed),
                   cpu_compliant=abs(elapsed - budget) <= tolerance,
                   training_valid=not failures and len(updates) > 0
                   and complete_rounds == len(schedule) and supervised_rounds == len(schedule))
    return policy, artifact, receipt
