"""Independent correctness and experiment-integrity audits.

Numerical differentiation checks only establish local implementation accuracy.
They are not evidence of task benefit, a continuous diffusion theorem, sampled
task execution equivalence, or native Hepta production readiness.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.linalg import expm_frechet
from scipy.special import expit

from .cells import recurrent_features
from .task import save

ACTIONS = ("STOP", "SKIP", "READ", "FIRE")
ARMS = ("ordinary_myopic", "ordinary_value", "analytic_myopic", "analytic_value")


def scalar_generator(theta, driver, direction=None):
    """Independent scalar five-state construction and parameter differential.

    This intentionally does not call propagation.generator/flow or cells.physical.
    The fitted domain has positive drift and reset between active centers 0/1.
    """
    theta = np.asarray(theta, float)
    direction = np.zeros(6) if direction is None else np.asarray(direction, float)
    s = expit(theta)
    ds = s*(1-s)*direction
    z = float(expit(theta[0]+theta[1]*driver))
    mu, dmu = .1+.8*z, .8*z*(1-z)*(direction[0]+direction[1]*driver)
    sigma, dsigma = .25+.25*s[2], .25*ds[2]
    boundary, dboundary = .8+.4*s[3], .4*ds[3]
    reset, dreset = -.3+.2*s[4], .2*ds[4]
    refractory, drefractory = .3+.5*s[5], .5*ds[5]
    width, dwidth = (boundary+1)/3, dboundary/3
    location = (reset+1)/width-.5
    dlocation = dreset/width-(reset+1)*dwidth/width**2
    if not 0 < location < 1:
        raise ValueError("Independent audit is restricted to the frozen interior reset cell")
    initial, dinitial = np.zeros(5), np.zeros(5)
    initial[:2], dinitial[:2] = [1-location, location], [-dlocation, dlocation]
    diffusion = sigma*sigma/(2*width*width)
    ddiffusion = sigma*dsigma/width**2-sigma*sigma*dwidth/width**3
    up, dup = diffusion+mu/width, ddiffusion+dmu/width-mu*dwidth/width**2
    rate, drate = 2/refractory, -2*drefractory/refractory**2
    q, dq, event, devent = np.zeros((5, 5)), np.zeros((5, 5)), np.zeros(5), np.zeros(5)

    def edge(a, b, value, derivative):
        q[a, b] += value
        q[a, a] -= value
        dq[a, b] += derivative
        dq[a, a] -= derivative

    for i in range(3):
        if i:
            edge(i, i-1, diffusion, ddiffusion)
        edge(i, i+1 if i < 2 else 4, up, dup)
    event[2], devent[2] = up, dup
    edge(4, 3, rate, drate)
    edge(3, 0, rate*(1-location), drate*(1-location)-rate*dlocation)
    edge(3, 1, rate*location, drate*location+rate*dlocation)
    return q, dq, event, devent, initial, dinitial


def scalar_replay(theta, records, direction=None):
    """Independent complete recurrence, including parameter-dependent reset."""
    rows, derivatives = [], []
    for record in records:
        _, _, _, _, origin, dorigin = scalar_generator(theta, 0., direction)
        p, dp = origin.copy(), dorigin.copy()
        for segment in record["history"]:
            q, dq, _, _, _, _ = scalar_generator(theta, segment["driver"], direction)
            transition, dtransition = expm_frechet(segment["duration"]*q,
                                                  segment["duration"]*dq)
            dp, p = dp@transition+p@dtransition, p@transition
            if segment["reset"]:
                p, dp = origin.copy(), dorigin.copy()
        q, dq, rate, drate, _, _ = scalar_generator(theta, record["driver"], direction)
        horizon = record["horizon"]
        matrix, dmatrix = np.zeros((6, 6)), np.zeros((6, 6))
        matrix[:5, :5], matrix[:5, 5] = q, rate
        dmatrix[:5, :5], dmatrix[:5, 5] = dq, drate
        integral, dintegral = expm_frechet(horizon*matrix, horizon*dmatrix)
        count = float(p@integral[:5, 5])
        dcount = float(dp@integral[:5, 5]+p@dintegral[:5, 5])
        killed, dkilled = q.copy(), dq.copy()
        killed[2, 4] = 0.
        dkilled[2, 4] = 0.
        survival, dsurvival = expm_frechet(horizon*killed, horizon*dkilled)
        first_hit = float(1-p@survival@np.ones(5))
        dfirst_hit = -float((dp@survival+p@dsurvival)@np.ones(5))
        position = np.array([1/6, 1/2, 5/6])
        rows.append([float(p[:3]@position), float(p[3:].sum()), count/(1+count), first_hit])
        derivatives.append([float(dp[:3]@position), float(dp[3:].sum()),
                            dcount/(1+count)**2, dfirst_hit])
    return np.asarray(rows), np.asarray(derivatives)


def recurrent_audit():
    """Frozen local correctness fixtures, with no task outcomes or selection."""
    wall, cpu = time.perf_counter(), time.process_time()
    theta = np.array([.12, -.23, .31, -.17, .22, -.4])
    histories = [[], [dict(driver=.7, duration=.2, reset=False),
                      dict(driver=-.4, duration=.45, reset=False)],
                 [dict(driver=-.5, duration=.33, reset=False),
                  dict(driver=.9, duration=.7, reset=True),
                  dict(driver=.3, duration=.11, reset=False)]]
    records = [dict(history=h, driver=d, horizon=t) for h, d, t in
               zip(histories, (.2, -.7, .6), (.13, .47, .21))]
    actual = recurrent_features("analytic", theta, records)
    independent, _ = scalar_replay(theta, records)
    checks = []

    def check(name, passed, **details):
        checks.append(dict(name=name, passed=bool(passed), **details))

    error = float(np.max(np.abs(actual-independent)))
    check("independent_scalar_recurrence", error < 2e-12, maximum_error=error)
    directions = []
    for index in range(6):
        direction = np.eye(6)[index]
        _, derivative = scalar_replay(theta, records, direction)
        steps = []
        for epsilon in (2e-5, 4e-6):
            plus = recurrent_features("analytic", theta+epsilon*direction, records)
            minus = recurrent_features("analytic", theta-epsilon*direction, records)
            finite = (plus-minus)/(2*epsilon)
            error = float(np.max(np.abs(finite-derivative)/(1+np.abs(derivative))))
            steps.append(dict(epsilon=epsilon, scaled_error=error, finite_difference=finite.tolist()))
            check(f"whole_history_parameter_{index}_step_{epsilon}", error < 3e-8,
                  maximum_scaled_error=error)
        directions.append(dict(parameter_index=index, frechet=derivative.tolist(), comparisons=steps))
    reset_history = records[2]["history"]
    truncated = dict(records[2], history=reset_history[2:])
    for family in ("ordinary", "analytic"):
        full = recurrent_features(family, theta, [records[2]])
        short = recurrent_features(family, theta, [truncated])
        error = float(np.max(np.abs(full-short)))
        check(f"task_reset_discards_prior_history_{family}", error < 2e-14, maximum_error=error)
    before = json.dumps(records, sort_keys=True)
    for family in ("ordinary", "analytic"):
        recurrent_features(family, theta, records)
    check("feature_queries_do_not_mutate_causal_records", json.dumps(records, sort_keys=True) == before)
    return dict(schema="hcsn.factorial.recurrent-independent-audit.v1",
                passed=all(row["passed"] for row in checks), checks=checks,
                parameters=theta.tolist(), fixtures=records, gradient_directions=directions,
                actual_features=actual.tolist(), independent_features=independent.tolist(),
                cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall,
                source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                scope="Finite recurrent implementation correctness only; no task benefit or production claim")


def require(condition, message):
    if not bool(condition):
        raise ValueError(message)


def close(actual, expected, name):
    require(np.shape(actual) == np.shape(expected)
            and np.allclose(actual, expected, atol=2e-10, rtol=2e-11), name)


def public_vector(public, job, tick, budget, posterior, confusion, multiplier, latency_price):
    """Independently reconstruct the promised 62 public information coordinates."""
    deadline = public["deadline"]
    reliability, prices, duration = np.zeros((2, 10)), np.zeros((2, 10)), np.zeros(10)
    reliability[:, :deadline], prices[:, :deadline] = public["reliability"], public["price"]
    duration[:deadline] = public["duration"]
    return np.r_[[job, tick, budget, posterior, deadline, public["budget"], multiplier, latency_price],
                 reliability.ravel(), prices.ravel(), duration, np.asarray(confusion).ravel()]


def audit_episode(row, public, confusion, labels, packet_root, protocol):
    """Recompute the realized task from immutable evidence, without Owner/Bellman.

    Evaluator labels are used only for this post-confirmation audit. Their absence
    from controller inputs is checked independently of the terminal score flag.
    """
    confusion = np.asarray(confusion, float)
    require(confusion.shape == (2, 2) and np.all(confusion > 0), "calibrated law domain")
    close(confusion.sum(1), np.ones(2), "calibrated law mass")
    multiplier, latency_price = protocol["multiplier"], protocol["latency_price"]
    job, tick, budget, posterior, reads_in_job = 0, 0, public["budget"], .5, 0
    query, latency, task_elapsed, payload_bytes = 0., 0., 0., 0
    history, answers = [], []
    counts = {a: 0 for a in ACTIONS}
    events, decisions = row["events"], row["decision_trace"]
    require(len(events) == len(decisions) and len(events) > 0, "one decision per executed event")
    terminal = False
    for index, (event, decision) in enumerate(zip(events, decisions)):
        require(not terminal, "no actions after terminal")
        record = decision["record"]
        require(not ({"q", "q_myopic", "next_observation", "labels", "evaluator_labels"} & set(record)),
                "test record must not expose training targets or labels")
        close(record["features"], public_vector(public, job, tick, budget, posterior,
                                               confusion, multiplier, latency_price), "complete public input")
        active = job < 2 and tick < public["deadline"]
        legal = np.array([True, active and tick+1 < public["deadline"],
                          active and budget > 0 and tick+1 < public["deadline"], active])
        require(np.array_equal(record["feasible"], legal), "feasibility agreement")
        reliability = public["reliability"][job][tick]
        driver = .8*(2*posterior-1)+.2*(2*reliability-1)
        close(record["driver"], driver, "causal pre-action driver")
        close(record["horizon"], public["duration"][tick], "public pre-action horizon")
        require(record["history"] == history, "history must contain exactly completed earlier actions")
        action = decision["picked_action"]
        if isinstance(action, int):
            action = ACTIONS[action]
        require(action in ACTIONS and event["action"] == action, "decision executed unchanged")
        require(legal[ACTIONS.index(action)], "executed action legal")
        if row["policy"] in ARMS:
            prediction = np.asarray(decision["q"], float)
            require(prediction.shape == (4,) and np.all(np.isfinite(prediction)), "finite learned Q values")
            require(action == ACTIONS[int(np.argmax(np.where(legal, prediction, -np.inf)))],
                    "masked argmax drives execution")
        require(event["job"] == job and event["tick"] == tick and event["budget_before"] == budget,
                "event begins from current discrete state")
        close(event["posterior_before"], posterior, "event begins from current belief")
        steps = 0 if action == "STOP" else 2 if action == "FIRE" else 1
        duration = float(sum(public["duration"][tick:min(tick+steps, public["deadline"])]))
        task_elapsed += duration
        latency += latency_price*duration
        counts[action] += 1
        if action == "STOP":
            terminal = True
        elif action == "SKIP":
            tick += 1
            require("observation" not in event and "payload_sha256" not in event, "SKIP has no content read")
        elif action == "READ":
            packet = public["packets"][job][tick]
            require(event["packet"] == packet and event["observation"] in (0, 1), "observed requested packet")
            raw = packet_root(packet) if callable(packet_root) else (Path(packet_root)/packet).read_bytes()
            require(hashlib.sha256(raw).hexdigest() == event["payload_sha256"], "actual packet hash")
            require(len(raw) == event["payload_bytes"], "actual packet byte count")
            if "logits" in event:
                require(int(np.argmax(np.asarray(event["logits"])[:2])) == event["observation"],
                        "decoder logits select reported bit")
            payload_bytes += len(raw)
            observation = event["observation"]
            chance = reliability*confusion[:, observation]+(1-reliability)*confusion[::-1, observation]
            denominator = (1-posterior)*chance[0]+posterior*chance[1]
            posterior = posterior*chance[1]/denominator
            query += multiplier*public["price"][job][tick]
            tick, budget, reads_in_job = tick+1, budget-1, reads_in_job+1
        else:
            answer = dict(job=job, prediction=int(posterior >= .5), posterior=posterior,
                          tick=tick, reads=reads_in_job)
            for key in ("job", "prediction", "tick", "reads"):
                require(event["answer"][key] == answer[key], "FIRE submits the current decision")
            close(event["answer"]["posterior"], posterior, "FIRE uses the current belief")
            answers.append(answer)
            job, tick, posterior, reads_in_job = job+1, tick+2, .5, 0
        terminal = terminal or job >= 2 or tick >= public["deadline"]
        close(event["duration"], duration, "declared task duration")
        close(event["charged_cost"], query+latency, "same per-action objective charge")
        close(event["posterior_after"], posterior, "belief update/reset")
        require(event["budget_after"] == budget and event["next_job"] == job
                and event["next_tick"] == tick and event["terminal"] == terminal, "next state agreement")
        history.append(dict(driver=float(record["driver"]), duration=duration, reset=action == "FIRE"))
    require(terminal, "complete terminal execution")
    correct = sum(a["prediction"] == labels[a["job"]] for a in answers)
    reward = 2*correct-len(answers)
    expected_score = dict(utility=reward-query-latency, reward=reward, charged_cost=query+latency,
                          query_cost=query, latency_cost=latency, completed_jobs=len(answers), correct_jobs=correct)
    for key, expected in expected_score.items():
        close(row["score"][key], expected, "terminal score "+key)
    require(row["score"].get("label_access_after_terminal") is True, "terminal evaluator boundary recorded")
    for name, count in counts.items():
        require(row["counts"][name] == count, "action count "+name)
    require(row["counts"]["packet_file_reads"] == counts["READ"]
            and row["counts"]["content_invocations"] == counts["READ"], "one actual inference per READ")
    require(row["counts"]["metadata_file_reads"] == 1 and row["counts"]["payload_bytes"] == payload_bytes,
            "metadata and payload accounting")
    close(row["task_elapsed"], task_elapsed, "declared task time, independent of measured CPU")
    for prefix in ("cpu", "wall"):
        total, controller = row[prefix+"_seconds"], row["controller_"+prefix+"_seconds"]
        require(np.isfinite(total+controller) and total >= 0 and 0 <= controller <= total+1e-6,
                "nested actual "+prefix+" accounting")
    return dict(events=len(events), packet_reads=counts["READ"], payload_bytes=payload_bytes,
                answers=len(answers), utility=float(expected_score["utility"]))


def weights_hash(weights):
    return hashlib.sha256(b"".join(np.asarray(weights[k], dtype="<f8").tobytes()
                                  for k in ("w", "b", "v", "c"))).hexdigest()


def audit_model(model, seed, protocol, train, validation):
    """Check shared information, frozen fitting stages and equal critic budgets."""
    raw = np.array([r["features"] for r in train], float)
    standard = raw.std(0)
    standard[standard < 1e-8] = 1.
    close(model["norm"]["mean"], raw.mean(0), "TRAIN-only normalization mean")
    close(model["norm"]["scale"], standard, "TRAIN-only normalization scale")
    require(all(r["split"] == "train" for r in train), "training split provenance")
    require(all(r["split"] == "validation" and "next_observation" not in r for r in validation),
            "validation does not expose next-READ fitting labels")
    targets = [r["next_observation"] for r in train if "next_observation" in r]
    require(all(r["chosen_action"] == "READ" for r in train if "next_observation" in r),
            "cell supervision is only actual TRAIN reads")
    optimizer = np.random.default_rng(seed+protocol["batch_seed_base"])
    stream = np.concatenate([optimizer.integers(0, len(train), protocol["batch_size"])
                             for _ in range(protocol["critic_updates"])])
    batch_hash = hashlib.sha256(stream.astype("<i8").tobytes()).hexdigest()
    rng = np.random.default_rng(seed+protocol["critic_init_seed_base"])
    width = protocol["critic_width"]
    initial = dict(w=rng.normal(0., 1/np.sqrt(67), (67, width)), b=np.zeros(width),
                   v=rng.normal(0., 1/np.sqrt(width), (width, 4)), c=np.zeros(4))
    initial_hash = weights_hash(initial)
    count = sum(a.size for a in initial.values())
    cell_initial = np.random.default_rng(seed+protocol["cell_init_seed_base"]).normal(0., .15, 11)
    cell_rows = []
    for family in ("ordinary", "analytic"):
        fitted = model["cellfits"][family]
        receipt, parameters = fitted["receipt"], np.asarray(fitted["parameters"], float)
        require(receipt["family"] == family and receipt["seed"] == seed, "cell fit identity")
        require(parameters.shape == (11,) and np.all(np.abs(parameters) <= 3+1e-12), "same bounded cell parameter budget")
        close(receipt["initial_parameters"], cell_initial, "matched cell initialization")
        close(receipt["parameters"], parameters, "frozen fitted cell parameters")
        require(receipt["parameter_count"] == 11 and receipt["train_read_rows"] == len(targets), "cell train sample budget")
        require(receipt["train_labels"] == targets, "cell labels are the declared TRAIN observations")
        require(receipt["nfev"] == len(receipt["evaluations"]), "retain every cell objective evaluation")
        require([e["index"] for e in receipt["evaluations"]] == list(range(receipt["nfev"])), "ordered optimizer evaluations")
        require(receipt["iterations"] <= protocol["cell_maxiter"], "same declared optimizer iteration cap")
        require(np.all(np.isfinite([e["loss"] for e in receipt["evaluations"]])), "finite cell objective trace")
        cell_rows.append(dict(family=family, nfev=receipt["nfev"], converged=receipt["converged"],
                              soft_maxfun_overshoot=max(0, receipt["nfev"]-protocol["cell_maxfun"])))
    for arm in ARMS:
        fitted = model["controllers"][arm]
        receipt, weights = fitted["receipt"], fitted["weights"]
        require(receipt["initial_sha256"] == initial_hash, "matched critic initialization")
        require(receipt["minibatch_sha256"] == batch_hash, "matched critic minibatch stream")
        require(receipt["parameter_count"] == count and receipt["updates"] == protocol["critic_updates"],
                "matched critic capacity and updates")
        require(len(receipt["losses"]) == protocol["critic_updates"]
                and np.all(np.isfinite(receipt["losses"])), "retain every critic update")
        candidates = receipt["candidates"]
        require([c["update"] for c in candidates] == protocol["checkpoint_updates"], "matched candidate checkpoints")
        selected = min(candidates, key=lambda candidate: candidate["validation_regret"])
        require(receipt["selected_update"] == selected["update"], "development-only earliest best selection")
        for candidate in candidates:
            require(weights_hash(candidate["weights"]) == candidate["parameter_sha256"], "retained checkpoint hash")
        require(weights_hash(weights) == selected["parameter_sha256"] == receipt["selected_sha256"], "selected model identity")
        require(receipt["target"] == ("q" if arm.endswith("value") else "q_myopic"), "declared continuation contrast")
        require(receipt["train_states"] == len(train) and receipt["validation_states"] == len(validation), "matched states")
    return dict(seed=seed, train_states=len(train), validation_states=len(validation),
                train_read_labels=len(targets), critic_parameter_count=count,
                critic_initial_sha256=initial_hash, minibatch_sha256=batch_hash, cell_optimizers=cell_rows)


def critic_gradient_audit():
    """Independent directional loss derivatives and invalid-target isolation."""
    from .controller import loss_and_gradient, parameters
    rng = np.random.default_rng(76091)
    weights = parameters(76091, 67, 24)
    x, target = rng.normal(size=(9, 67)), rng.normal(size=(9, 4))
    legal = rng.random((9, 4)) > .3
    legal[:, 0] = True
    loss, gradients = loss_and_gradient(weights, x, target, legal, .0001)
    checks = []
    changed = target.copy()
    changed[~legal] = 713.5
    other_loss, other_gradients = loss_and_gradient(weights, x, changed, legal, .0001)
    checks.append(dict(name="invalid_targets_have_no_training_effect", passed=loss == other_loss
                       and all(np.array_equal(gradients[k], other_gradients[k]) for k in gradients)))
    for index in range(3):
        direction = {k: rng.normal(size=v.shape) for k, v in weights.items()}
        norm = np.sqrt(sum(float(np.square(v).sum()) for v in direction.values()))
        direction = {k: v/norm for k, v in direction.items()}
        expected = sum(float(np.sum(gradients[k]*direction[k])) for k in weights)
        epsilon = 2e-5
        plus = {k: v+epsilon*direction[k] for k, v in weights.items()}
        minus = {k: v-epsilon*direction[k] for k, v in weights.items()}
        finite = (loss_and_gradient(plus, x, target, legal, .0001)[0]
                  -loss_and_gradient(minus, x, target, legal, .0001)[0])/(2*epsilon)
        error = abs(finite-expected)/(1+abs(expected))
        checks.append(dict(name=f"critic_direction_{index}", passed=error < 2e-8,
                           scaled_error=error, analytic=expected, finite_difference=finite))
    return dict(passed=all(c["passed"] for c in checks), checks=checks,
                scope="Masked-regression implementation correctness only")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    result = recurrent_audit()
    critic = critic_gradient_audit()
    result["critic"] = critic
    result["checks"].extend(critic["checks"])
    result["passed"] = result["passed"] and critic["passed"]
    save(arguments.output, result)
    print(json.dumps(dict(passed=result["passed"], checks=len(result["checks"]),
                          failed=[r["name"] for r in result["checks"] if not r["passed"]])))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
