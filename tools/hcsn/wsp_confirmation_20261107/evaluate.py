"""Cold execution controls and a fresh evaluator cohort for the existing task."""
import time

import numpy as np

from guard import digest, file_identity
from artifact_io import canonical, read
from run_experiment import load_history
from vendor import planning as p


class ControlPolicy(p.WorldPolicy):
    def __init__(self, ctx, public, model, compiled, arm):
        super().__init__(ctx, public, model, compiled)
        self.arm, self.visited = arm, {}
        self.own = ctx.Oracle(public, p.OwnTableLaw(model, ctx), model.confusion) if arm == "MYOPIC" else None

    def scores(self, state, theta, structural):
        self.visited[canonical(state)] = state
        if self.arm == "L":
            hidden, _ = self.feature(state)
            raw = np.sum(theta * hidden[None, :], axis=1)
            belief = float(1 / (1 + np.exp(-np.clip(raw[3], -700, 700))))
            return np.r_[0., raw[:3], 1 - 2 * belief, 2 * belief - 1], belief
        if self.arm == "MYOPIC":
            belief = self.own.posterior(state)
            scores = np.array([0., 0., 0., 0., 1 - 2 * belief, 2 * belief - 1])
            for action in (1, 2, 3):
                if not self.ctx.legal(self.public, state)[action]:
                    continue
                for probability, completion in self.ctx.outcomes(self.public, state, action, self.own):
                    if not probability:
                        continue
                    after = self.ctx.successor(self.public, state, action, completion)
                    posterior = self.own.posterior(after)
                    fee = after["charges"] - state["charges"]
                    scores[action] += probability * (abs(2 * posterior - 1) - fee)
            return scores, belief
        return super().scores(state, theta, structural)


def history(upstream):
    known, schedule_hash, report = load_history(upstream)
    history_files = sorted((upstream / "execution_r1/run/worlds").glob("*.json.gz"))
    if len(history_files) != 20:
        raise ValueError("complete exposed value-edit confirmation history required")
    for path in history_files:
        for public in read(path)["worlds"]:
            known.add(schedule_hash(public))
    report.update(known_unique_schedules=len(known),
                  hashes_sha256=digest(sorted(known)),
                  exposed_value_edit_files={str(path.relative_to(upstream)): file_identity(path) for path in history_files},
                  includes_exposed_value_edit_validation_and_test=True,
                  candidate_selection_reads_historical_scores=False)
    return known, schedule_hash, report


def generate(ctx, protocol, seed, schedule_hash):
    samples = []
    for fit in protocol["fits"]:
        for domain in protocol["confirmation"]["domains"]:
            rng = np.random.Generator(np.random.PCG64(int(digest([seed, fit, domain]), 16)))
            law = ctx.protocol["ood_domain" if domain == "ood" else "train_domain"]
            for index in range(protocol["confirmation"]["worlds_per_fit_domain"]):
                public = dict(schema=ctx.ns["SCHEMA"], id=f"wsp_confirm_{fit}_{domain}_{index}",
                    deadline=6, initial_budget=3, target_tick=6,
                    duration=rng.choice(law["durations"], 6).tolist(),
                    drive=rng.choice(law["drives"], 6).tolist(),
                    reliability=rng.choice(law["reliabilities"], 6).tolist(),
                    read_price=rng.choice(law["prices"], 6).tolist(),
                    read_delay=rng.choice(law["delays"], 6).tolist(),
                    prior_distance=float(rng.choice(ctx.protocol["prior_distances"])),
                    latency_price=law["latency_price"], repair_price=law["repair_price"],
                    failure_probability=law["failure_probability"],
                    packets=[f"not_opened_{j}.json" for j in range(6)], packet_sha256=["0" * 64] * 6)
                ctx.ns["validate_public"](public)
                samples.append({"fit": fit, "domain": domain, "index": index,
                                "sha256": schedule_hash(public), "public": public})
    return samples


def score_world(ctx, sample, fit, protocol, budget, claim, record):
    public, results = sample["public"], {}
    truth = ctx.Oracle(public, ctx.law, fit["policy"].confusion)
    common_states = None
    for arm in protocol["arms"]:
        budget()
        claim(arm)
        start, wall = time.process_time(), time.perf_counter()
        try:
            compiled, planning = None, None
            if arm == "J":
                compiled, planning, _ = p.compile_own(ctx, fit["policy"], public,
                    protocol["state_caps"]["markov_per_world"])
            policy = ControlPolicy(ctx, public, fit["policy"], compiled, arm)
            result = p.evaluate(ctx, public, policy, fit["arms"][arm], "J" if arm == "J" else "head", truth)
            if arm == "C":
                common_states = list(policy.visited.values())
            preservation_start = time.process_time()
            max_belief = 0.
            agrees = []
            for state in common_states:
                q, belief = policy.scores(state, fit["arms"][arm], "J" if arm == "J" else "head")
                hidden, _ = policy.feature(state)
                base_q, base_belief = ctx.predicted(fit["arms"]["C"], hidden)
                max_belief = max(max_belief, abs(belief - base_belief))
                mask = np.asarray(ctx.legal(public, state))
                agrees.append(int(np.where(mask, q, -np.inf).argmax()) == int(np.where(mask, base_q, -np.inf).argmax()))
            result.update(planning=planning, common_C_state_count=len(common_states),
                common_C_state_belief_max_change=max_belief,
                common_C_state_action_agreement=float(np.mean(agrees)),
                preservation_cpu_seconds=time.process_time() - preservation_start,
                full_arm_cpu_seconds=time.process_time() - start,
                full_arm_wall_seconds=time.perf_counter() - wall,
                program_control=arm in ("J", "MYOPIC"), energy_joules=None)
            record(arm, result, time.process_time() - start, time.perf_counter() - wall, False)
            results[arm] = result
        except BaseException as error:
            record(arm, {"error": str(error), "type": type(error).__name__},
                   time.process_time() - start, time.perf_counter() - wall, True)
            raise
    if any(results["C"][key] != results["L"][key] for key in
           ("utility", "fees", "reads_requested", "reads_completed", "repairs", "elapsed", "correct", "submitted", "nodes")):
        raise ArithmeticError("literal execution control differs; freeze candidate, do not tune layout on confirmation")
    return results
