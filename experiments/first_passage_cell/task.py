"""Frozen finite-horizon maintenance task; scored outcomes follow real actions."""

from dataclasses import asdict, replace
import copy
import hashlib
import math

import numpy as np

from .cell import CellParameters, FirstPassageCell, canonical_bytes

TASK_PROFILE = "hepta-maintenance-renewal-v1"
STEP_DURATION = 0.5
DECISIONS = 4
ACTIVE_REWARD_RATE = 0.6
FAILURE_COST = 0.5
REFRACTORY = 0.06
TRAINING_SEEDS = (1103, 1151, 1201, 1213, 1223, 1231, 1237, 1249)


def true_parameters():
    """Simulator-only law; policies receive the selected fitted model instead."""
    return CellParameters(-0.55, (-0.18, 0.16), 0.32, 0.12, 0.9, REFRACTORY)


def named_seed(seed, phase, index=0):
    raw = canonical_bytes([TASK_PROFILE, int(seed), phase, int(index)])
    return int.from_bytes(hashlib.blake2b(raw, digest_size=8).digest(), "little")


def scenarios(seed, count, phase):
    if phase not in {"development", "policy_development", "confirmation", "diagnostic",
                      "stress_drift", "stress_diffusion"}:
        raise ValueError("Unknown scenario phase")
    rng = np.random.Generator(np.random.Philox(named_seed(seed, phase)))
    return [{
        "identity": f"{phase}:{seed}:{i}",
        "regime": phase if phase.startswith("stress_") else "nominal",
        "level": true_parameters().barrier + float(rng.uniform(0.08, 1.4)),
        "inputs": [float(x) for x in rng.uniform(-1, 1, size=2)],
        "repair_cost": float(rng.uniform(0.05, 0.4)),
        "noise_seed": named_seed(seed, phase + ":noise", i),
    } for i in range(count)]


def scenario_parameters(scenario):
    """Simulator-only prespecified mismatches; regime is absent from observations."""
    value = true_parameters()
    regime = scenario.get("regime", "nominal")
    if regime == "stress_drift":
        return replace(value, drift=value.drift - 0.15)
    if regime == "stress_diffusion":
        return replace(value, sigma=value.sigma * 1.25)
    if regime != "nominal":
        raise ValueError("Unknown simulator regime")
    return value


class MaintenanceTask:
    """WAIT/REPAIR/STOP decisions with a single, explicit external cost ledger."""

    def __init__(self, scenario, parameters=None):
        parameters = scenario_parameters(scenario) if parameters is None else parameters
        self.scenario = copy.deepcopy(scenario)
        self.inputs = tuple(scenario["inputs"])
        self.cost = float(scenario["repair_cost"])
        if not math.isfinite(self.cost) or self.cost < 0:
            raise ValueError("Nonnegative finite repair cost required")
        self.cell = FirstPassageCell(parameters, float(scenario["level"]),
                                     int(scenario["noise_seed"]))
        self.index = 0
        self.done = False
        self.total_reward = 0.0
        self.ledger = []

    def observation(self):
        return {
            "task_profile": TASK_PROFILE,
            "level": self.cell.level,
            "time": self.cell.time,
            "inputs": list(self.inputs),
            "repair_cost": self.cost,
            "remaining_duration": (DECISIONS - self.index) * STEP_DURATION,
            "refractory_remaining": self.cell.refractory_remaining,
            "decision_index": self.index,
            "legal_actions": ["wait", "stop"] if self.cell.refractory_remaining > 0
                             else ["wait", "repair", "stop"],
        }

    def step(self, action):
        """Execute intervention, propagation and accounting as one transaction."""
        cell = self.cell
        previous = (cell.level, cell.time, cell.refractory_remaining,
                    cell.event_count, cell.rng.counter, self.index,
                    self.done, self.total_reward, len(self.ledger))
        try:
            return self._step(action)
        except Exception:
            (cell.level, cell.time, cell.refractory_remaining,
             cell.event_count, cell.rng.counter, self.index,
             self.done, self.total_reward, ledger_length) = previous
            del self.ledger[ledger_length:]
            raise

    def _step(self, action):
        if self.done:
            raise ValueError("Cannot act after termination")
        before = self.observation()
        if action not in before["legal_actions"]:
            raise ValueError("Action is not in the current public legal set")
        intervention = []
        action_cost = 0.0
        if action == "stop":
            self.done = True
            receipt = {"elapsed_duration": 0.0, "active_duration": 0.0,
                       "failure_count": 0, "events": [],
                       "level": self.cell.level, "time": self.cell.time,
                       "refractory_remaining": self.cell.refractory_remaining,
                       "random_counter": self.cell.rng.counter}
        else:
            if action == "repair":
                action_cost = self.cost
                self.cell.repair()
                intervention = [{"time": self.cell.time, "kind": "repair"}]
            receipt = self.cell.advance(STEP_DURATION, self.inputs)
        running_reward = ACTIVE_REWARD_RATE * receipt["active_duration"]
        failure_cost = FAILURE_COST * receipt["failure_count"]
        reward = running_reward - failure_cost - action_cost
        self.total_reward += reward
        self.index += 1
        if self.index == DECISIONS:
            self.done = True
        record = {
            "task_profile": TASK_PROFILE, "scenario_id": self.scenario["identity"],
            "observation": before, "action": action, "outcome": receipt,
            "interventions": intervention, "running_reward": running_reward,
            "failure_cost": failure_cost, "action_cost": action_cost,
            "reward": reward, "cumulative_reward": self.total_reward,
            "done": self.done,
        }
        self.ledger.append(record)
        return record

    def checkpoint(self):
        payload = {"task_profile": TASK_PROFILE, "scenario": copy.deepcopy(self.scenario),
                   "cell": self.cell.checkpoint(), "index": self.index,
                   "done": self.done, "total_reward": self.total_reward,
                   "ledger": copy.deepcopy(self.ledger)}
        return {"payload": payload,
                "sha256": hashlib.sha256(canonical_bytes(payload)).hexdigest()}

    @classmethod
    def from_checkpoint(cls, checkpoint, expected_model_digest):
        if set(checkpoint) != {"payload", "sha256"}:
            raise ValueError("Malformed task checkpoint envelope")
        value = checkpoint["payload"]
        if hashlib.sha256(canonical_bytes(value)).hexdigest() != checkpoint["sha256"]:
            raise ValueError("Task checkpoint digest mismatch")
        required = {"task_profile", "scenario", "cell", "index", "done", "total_reward", "ledger"}
        if set(value) != required or value["task_profile"] != TASK_PROFILE:
            raise ValueError("Wrong task checkpoint fields/profile")
        restored = FirstPassageCell.from_checkpoint(value["cell"], expected_model_digest)
        if restored.rng.seed != value["scenario"]["noise_seed"]:
            raise ValueError("Task scenario/random stream seed mismatch")
        task = cls(value["scenario"], restored.parameters)
        task.cell = restored
        task.index = value["index"]
        task.done = value["done"]
        task.total_reward = value["total_reward"]
        task.ledger = copy.deepcopy(value["ledger"])
        if type(task.index) is not int or not 0 <= task.index <= DECISIONS:
            raise ValueError("Invalid task cursor")
        if type(task.done) is not bool or not math.isfinite(task.total_reward):
            raise ValueError("Invalid task termination or score")
        if len(task.ledger) != task.index:
            raise ValueError("Task ledger/cursor mismatch")
        total, clock, level, refractory, count, counter = 0.0, 0.0, task.scenario["level"], 0.0, 0, 0
        terminal = False
        for index, row in enumerate(task.ledger):
            expected_observation = {
                "task_profile": TASK_PROFILE, "level": level, "time": clock,
                "inputs": list(task.inputs), "repair_cost": task.cost,
                "remaining_duration": (DECISIONS - index) * STEP_DURATION,
                "refractory_remaining": refractory, "decision_index": index,
                "legal_actions": ["wait", "stop"] if refractory > 0 else ["wait", "repair", "stop"],
            }
            if terminal or row["observation"] != expected_observation:
                raise ValueError("Task ledger observation/time continuity mismatch")
            action, outcome = row["action"], row["outcome"]
            if action not in expected_observation["legal_actions"]:
                raise ValueError("Task ledger contains illegal action")
            if row["task_profile"] != TASK_PROFILE or row["scenario_id"] != task.scenario["identity"]:
                raise ValueError("Task ledger identity mismatch")
            elapsed = 0.0 if action == "stop" else STEP_DURATION
            if outcome["elapsed_duration"] != elapsed or outcome["time"] != clock + elapsed:
                raise ValueError("Task ledger elapsed time mismatch")
            active, failures = outcome["active_duration"], outcome["failure_count"]
            if not math.isfinite(active) or not 0 <= active <= elapsed + 1e-12:
                raise ValueError("Task ledger active time invalid")
            if type(failures) is not int or not 0 <= failures <= 128 or len(outcome["events"]) != failures:
                raise ValueError("Task ledger event count mismatch")
            if action == "stop" and (active != 0 or failures != 0):
                raise ValueError("Task ledger has physical work after stop")
            if action != "stop" and outcome["model_digest"] != expected_model_digest:
                raise ValueError("Task ledger model identity mismatch")
            event_floor = clock + (restored.parameters.refractory if action == "repair" else refractory)
            for event in outcome["events"]:
                count += 1
                if event["kind"] != "first_passage" or event["ordinal"] != count:
                    raise ValueError("Task ledger event kind/ordinal mismatch")
                if not event_floor - 1e-12 <= event["time"] <= clock + elapsed + 1e-12:
                    raise ValueError("Task ledger violates event/refractory timing")
                event_floor = event["time"] + restored.parameters.refractory
            initial_ref = restored.parameters.refractory if action == "repair" else refractory
            end = clock + elapsed
            lost = min(initial_ref, elapsed) + sum(
                min(restored.parameters.refractory, max(0.0, end - event["time"]))
                for event in outcome["events"])
            if not math.isclose(active, elapsed - lost, rel_tol=1e-12, abs_tol=1e-11):
                raise ValueError("Task ledger active/refractory conservation mismatch")
            expected_ref = max(0.0, initial_ref - elapsed) if not outcome["events"] else max(
                0.0, outcome["events"][-1]["time"] + restored.parameters.refractory - end)
            if not math.isclose(outcome["refractory_remaining"], expected_ref, rel_tol=1e-12, abs_tol=1e-11):
                raise ValueError("Task ledger refractory endpoint mismatch")
            if expected_ref > 1e-11 and not math.isclose(
                    outcome["level"], restored.parameters.barrier + restored.parameters.reset_gap,
                    rel_tol=1e-12, abs_tol=1e-11):
                raise ValueError("Task ledger level changed inside refractory interval")
            expected_interventions = [{"time": clock, "kind": "repair"}] if action == "repair" else []
            if row["interventions"] != expected_interventions:
                raise ValueError("Task ledger intervention mismatch")
            running = ACTIVE_REWARD_RATE * active
            failure_cost = FAILURE_COST * failures
            action_cost = task.cost if action == "repair" else 0.0
            reward = running - failure_cost - action_cost
            total += reward
            terminal = action == "stop" or index + 1 == DECISIONS
            expected_scores = (running, failure_cost, action_cost, reward, total, terminal)
            actual_scores = tuple(row[k] for k in ("running_reward", "failure_cost", "action_cost", "reward", "cumulative_reward", "done"))
            if expected_scores != actual_scores:
                raise ValueError("Task ledger score/terminal mismatch")
            if type(outcome["random_counter"]) is not int or outcome["random_counter"] < counter:
                raise ValueError("Task random counter regressed")
            clock, level = outcome["time"], outcome["level"]
            refractory, counter = outcome["refractory_remaining"], outcome["random_counter"]
        observed_state = (restored.time, restored.level, restored.refractory_remaining,
                          restored.event_count, restored.rng.counter, task.total_reward, task.done)
        expected_state = (clock, level, refractory, count, counter, total, terminal)
        if observed_state != expected_state:
            raise ValueError("Task ledger/final state mismatch")
        return task


def task_contract():
    return {"profile": TASK_PROFILE, "step_duration": STEP_DURATION,
            "decisions": DECISIONS, "active_reward_rate": ACTIVE_REWARD_RATE,
            "failure_cost": FAILURE_COST, "refractory": REFRACTORY,
            "true_parameters": asdict(true_parameters()),
            "future_input_rule": "inputs and price are public and constant within an episode",
            "action_time_rule": "failure resets continue within remaining physical time",
            "score_rule": "rate*active_duration - failure_cost*count - paid_repair_cost",
            "stop_rule": "zero future reward and zero elapsed time after stopping"}
