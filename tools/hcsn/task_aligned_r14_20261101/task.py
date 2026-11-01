"""Public-cost sensor-maintenance task on the unchanged R13 content process.

The state is regime-major: (clean/faulty sensor, original phase, content bit).
RESET repairs the external sensor, preserves phase and bit, and consumes a full
public interval during which the CTMC continues. It is distinct from natural
cell absorption/recovery. There is no action bonus or hidden reward shaping.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.linalg import expm

from ..unified_cell_r12_20261031.cell import Cell
from ..unified_cell_r12_20261031.task_value import ExactBeliefDP, choose_values


PROFILES = ("repairable", "clean", "unrepairable", "high_fee")


class TaskModel:
    """Finite public task definition; fault parameters are specified, not fitted.

    Actors receive only past (action, duration, raw symbol) and public prices.
    ``sample_step`` belongs to the execution owner: its latent-state return must
    never be placed in actor history. STOP is available before any observation.
    Matrix and likelihood APIs support a common generic HMM reference.
    """

    def __init__(self, cell=None, profile="repairable", fault_probability=.55,
                 fault_rate=.12):
        if profile not in PROFILES:
            raise ValueError("Unknown task profile")
        if not np.isfinite([fault_probability, fault_rate]).all():
            raise ValueError("Nonfinite fault parameters")
        if not 0 <= fault_probability <= 1 or fault_rate < 0:
            raise ValueError("Invalid public fault parameters")
        self.cell = Cell() if cell is None else cell
        self.profile = profile
        self.fault_probability = 0. if profile == "clean" else float(fault_probability)
        self.fault_rate = 0. if profile == "clean" else float(fault_rate)
        self.reset_cost = 1. if profile == "high_fee" else .025
        self.latency_price = .01
        self.read_price = .03
        self.base_states = self.cell.state_count
        self.state_count = 2 * self.base_states
        self.observation_count = 8
        self.regime_Q = np.array([[-self.fault_rate, self.fault_rate], [0., 0.]])
        self.Q = (np.kron(np.eye(2), self.cell.Q)
                  + np.kron(self.regime_Q, np.eye(self.base_states)))
        repair = np.eye(2) if profile == "unrepairable" else np.array([[1., 0.], [1., 0.]])
        self.R = np.kron(repair, np.eye(self.base_states))
        regime_prior = np.array([1 - self.fault_probability, self.fault_probability])
        self.prior = np.kron(regime_prior, self.cell.prior)
        self.E = self._emissions(self.cell.E)
        self.reward = (np.arange(self.state_count)[:, None] % 2 == np.arange(2)).astype(float)
        self.read_cost = np.full(self.state_count, self.read_price)
        derivatives = self.parameter_jacobians()
        self.dQ = derivatives["Q"][:3]
        self.dprior = derivatives["prior"][:3]
        self.dE_phys = derivatives["E"][:3]
        self.dE = self.dE_phys
        self.dE_logits = derivatives["E"][3:]
        self._transitions = {}
        self._gradient_transitions = {}
        # Public prices do not inherit latent financial value/fee bonuses.
        digest = hashlib.sha256(b"hcsn.r14.sensor-maintenance.v1")
        for matrix in (self.Q, self.E, self.R, self.prior, self.reward, self.read_cost):
            digest.update(str(matrix.shape).encode())
            digest.update(matrix.astype("<f8").tobytes())
            matrix.flags.writeable = False
        digest.update(np.asarray([self.reset_cost, self.latency_price], dtype="<f8").tobytes())
        self.identity = digest.hexdigest()

    def _emissions(self, emissions):
        # A failed sensor removes bit information while retaining phase effects.
        # Public alarm 7 occurs with probability .70 when faulty and .01 clean.
        average = np.repeat(emissions.reshape(-1, 2, 7).mean(axis=1), 2, axis=0)
        result = np.zeros((self.state_count, 8))
        result[:self.base_states, :7] = .99 * emissions
        result[:self.base_states, 7] = .01
        result[self.base_states:, :7] = .30 * average
        result[self.base_states:, 7] = .70
        return result

    def transition(self, dt, with_grad=False):
        """Exact finite transition, retaining the full physical interval."""
        dt = float(dt)
        if not np.isfinite(dt) or dt < 0:
            raise ValueError("Duration must be finite and nonnegative")
        if dt not in self._transitions:
            self._transitions[dt] = np.kron(expm(self.regime_Q * dt), self.cell.transition(dt))
        if not with_grad:
            return self._transitions[dt]
        if dt not in self._gradient_transitions:
            _, derivatives = self.cell.transition(dt, with_grad=True)
            regime_transition = expm(self.regime_Q * dt)
            self._gradient_transitions[dt] = np.stack([
                np.kron(regime_transition, derivative) for derivative in derivatives
            ])
        return self._transitions[dt], self._gradient_transitions[dt]

    def posterior(self, history, prior=None):
        """Replay only publicly observed (action, dt, token-or-None) records."""
        belief = self.prior.copy() if prior is None else np.array(prior, dtype=float, copy=True)
        if (belief.shape != (self.state_count,) or not np.isfinite(belief).all()
                or belief.min() < 0 or abs(belief.sum() - 1.) > 1e-10):
            raise ValueError("Expected a normalized task belief")
        for action, dt, token in history:
            if action not in ("WAIT", "READ", "RESET"):
                raise ValueError("History must contain nonterminal legal actions")
            if not np.isfinite(dt) or dt <= 0:
                raise ValueError("History intervals must be finite and positive")
            if action == "RESET":
                belief = belief @ self.R
            belief = belief @ self.transition(dt)
            if action == "READ":
                if not isinstance(token, (int, np.integer)) or isinstance(token, bool) or not 0 <= token < 8:
                    raise ValueError("A READ must supply a raw symbol from zero to seven")
                belief *= self.E[:, token]
                normalizer = belief.sum()
                if normalizer <= 0:
                    raise ValueError("History has zero model probability")
                belief /= normalizer
            elif token is not None:
                raise ValueError("WAIT and RESET cannot expose observations")
        return belief

    def sample_step(self, state, action, dt, rng):
        """Owner-only transition: (latent successor, raw symbol, reward, fee).

        Reward is paid only at STOP. Fee includes all action and time costs.
        The owner checks the remaining READ budget/horizon before calling.
        """
        if not isinstance(state, (int, np.integer)) or not 0 <= state < self.state_count:
            raise ValueError("Invalid owner state")
        if action in ("STOP0", "STOP1"):
            return int(state), None, float(self.reward[state, int(action[-1])]), 0.
        if action not in ("READ", "WAIT", "RESET") or not np.isfinite(dt) or dt <= 0:
            raise ValueError("A nonterminal action requires a positive finite interval")
        if action == "RESET":
            state = int(rng.choice(self.state_count, p=self.R[state]))
        successor = int(rng.choice(self.state_count, p=self.transition(dt)[state]))
        token = int(rng.choice(8, p=self.E[successor])) if action == "READ" else None
        fee = self.latency_price * dt
        if action == "READ":
            fee += self.read_price
        elif action == "RESET":
            fee += self.reset_cost
        return successor, token, 0., float(fee)

    def parameter_jacobians(self):
        """Inherited physical/emission derivatives; task constants stay fixed."""
        jac = self.cell.parameter_jacobians()
        regime_prior = np.array([1 - self.fault_probability, self.fault_probability])
        emission = np.zeros((15, self.state_count, 8))
        emission[:, :self.base_states, :7] = .99 * jac["E"]
        averaged = np.repeat(jac["E"].reshape(15, -1, 2, 7).mean(axis=2), 2, axis=1)
        emission[:, self.base_states:, :7] = .30 * averaged
        return dict(Q=np.stack([np.kron(np.eye(2), x) for x in jac["Q"]]), E=emission,
                    prior=np.stack([np.kron(regime_prior, x) for x in jac["prior"]]),
                    R=np.zeros((15, self.state_count, self.state_count)),
                    reward=np.zeros((15, self.state_count, 2)),
                    read_cost=np.zeros((15, self.state_count)))


class _NoResetDP(ExactBeliefDP):
    """Same finite controller and information, with maintenance unavailable."""

    @staticmethod
    def legal_actions(schedule, budget):
        return tuple(action for action in ExactBeliefDP.legal_actions(schedule, budget) if action != "RESET")


def run_validation():
    """Development-only witness and independent finite-transition checks."""
    witnesses = {}
    history = [("READ", .15, 7)]
    remaining = (.25, .35, .45)
    for profile in PROFILES:
        task = TaskModel(profile=profile)
        belief = task.posterior(history)
        dp = ExactBeliefDP(task, reset_cost=task.reset_cost, latency_price=task.latency_price)
        restricted = _NoResetDP(task, reset_cost=task.reset_cost, latency_price=task.latency_price)
        q = dp.action_values(belief, remaining, budget=2)
        forbidden = restricted.action_values(belief, remaining, budget=2)
        probability = float(task.prior @ task.transition(.15) @ task.E[:, 7])
        witnesses[profile] = dict(
            model_identity=task.identity, history=[list(x) for x in history],
            history_probability=probability, posterior_fault_probability=float(belief[20:].sum()),
            remaining_schedule=list(remaining), remaining_read_budget=2,
            action_values=q, chosen_action=choose_values(q), no_reset_values=forbidden,
            reset_vs_best_other=q["RESET"] - max(v for a, v in q.items() if a != "RESET"),
            available_vs_unavailable_value=max(q.values()) - max(forbidden.values()),
        )
    task = TaskModel()
    transition_error = float(np.max(np.abs(task.transition(.73) - expm(task.Q * .73))))
    split_error = float(np.max(np.abs(task.transition(.73) - task.transition(.21) @ task.transition(.52))))
    repaired = task.prior @ task.R @ task.transition(.73)
    fault_mass = float(repaired[20:].sum())
    mass_error = float(np.max(np.abs(task.transition(.73).sum(1) - 1.)))
    phase_bit_before = task.prior.reshape(2, 20).sum(0)
    phase_bit_after = (task.prior @ task.R).reshape(2, 20).sum(0)
    result = dict(schema="hcsn-r14-task-validation-v1", purpose="development-only; not confirmation",
                  witnesses=witnesses, factored_vs_independent_dense_expm_max_error=transition_error,
                  split_transition_max_error=split_error, stochastic_mass_error=mass_error,
                  repaired_then_evolved_fault_mass=fault_mass,
                  analytic_new_fault_probability=float(-np.expm1(-task.fault_rate * .73)),
                  repair_phase_bit_max_error=float(np.max(np.abs(phase_bit_before - phase_bit_after))))
    result["checks"] = dict(
        reset_strictly_useful=witnesses["repairable"]["reset_vs_best_other"] > .01,
        no_reset_decreases_value=witnesses["repairable"]["available_vs_unavailable_value"] > .01,
        clean_no_reset=witnesses["clean"]["chosen_action"] != "RESET",
        unrepairable_no_reset=witnesses["unrepairable"]["chosen_action"] != "RESET",
        high_fee_no_reset=witnesses["high_fee"]["chosen_action"] != "RESET",
        independent_transition=transition_error < 1e-12,
        segmentation=split_error < 1e-12,
        mass=mass_error < 1e-12,
        full_reset_interval=abs(fault_mass - result["analytic_new_fault_probability"]) < 1e-12,
        repair_preserves_content=result["repair_phase_bit_max_error"] < 1e-12,
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    text = json.dumps(run_validation(), indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
