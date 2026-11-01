"""Approximate policy iteration with actual-policy continuation targets."""

import itertools

import numpy as np

from experiments.hcsn_regeneration_content_20261031 import policy


def configurations(protocol, split):
    return [policy.Config(name, tuple(order), tuple(dts), qa, qb, read, skip).validate()
            for name, order, qa, qb, read, skip, dts in protocol[split]]


def evaluate_policy(graph, controller):
    """Qpi after every possible first action; no realized-future maximization."""
    values, q_values, choices, predictions = {}, {}, {}, {}
    for history in sorted(graph.nodes, key=len, reverse=True):
        node = graph.nodes[history]
        action, scores = controller.choose(graph.model, node["state"], graph.config)
        q = {"STOP": node["q"]["STOP"]}
        for name, edges in node["edges"].items():
            fee = graph.config.read_cost if name == "READ" else graph.config.skip_cost
            q[name] = -fee + sum(p * values[child] for p, child, _ in edges)
        if action not in q:
            raise ValueError("Controller requested an illegal action")
        values[history], q_values[history] = q[action], q
        choices[history], predictions[history] = action, scores
    occupancy, terminal_mass, regret_sum = {(): 1.}, 0., 0.
    for history in sorted(graph.nodes, key=len):
        node, mass = graph.nodes[history], occupancy.get(history, 0.)
        action = choices[history]
        regret_sum += mass * (node["value"] - node["q"][action])
        if action == "STOP":
            terminal_mass += mass
        for probability, child, _ in node["edges"].get(action, []):
            occupancy[child] = occupancy.get(child, 0.) + mass * probability
    exact = graph.exact_policy(controller)
    errors = {"terminal_mass": abs(terminal_mass - 1.),
              "policy_expectation": abs(exact["return"] - values[()]),
              "regret_identity": abs(graph.nodes[()]["value"] - values[()] - regret_sum)}
    if max(errors.values()) >= 2e-10:
        raise AssertionError(errors)
    return {"q": q_values, "values": values, "choices": choices,
            "predictions": predictions, "occupancy": occupancy, "errors": errors,
            "exact": exact, "terminal_mass": terminal_mass}


class DeployedRidge(policy.RidgeValue):
    """Predict continuation benefit, charge known current fees exactly."""

    def choose(self, model, state, config):
        gross = self.design(policy.public_features(model, state, config))[0] @ self.weights
        gross = np.clip(gross, -1. - len(config.dts) * max(config.read_cost, config.skip_cost), 1.)
        scores = {"STOP": 0., "READ": float(gross[0] - config.read_cost),
                  "SKIP": float(gross[1] - config.skip_cost)}
        if state.budget == 0 or state.slot == len(config.dts) - 1:
            scores["SKIP"] = -config.skip_cost
        action = max(policy.legal_actions(state, config), key=scores.__getitem__)
        return action, scores

    def payload(self):
        payload = super().payload()
        payload.update(kind="deployed_ridge", targets=["continuation_READ_minus_STOP", "continuation_SKIP_minus_STOP"],
                       exact_immediate_fees=True, exact_no_information_skip=True)
        return payload

    @classmethod
    def fit_following(cls, graphs, following, ridge, occupancy_fraction, target="qpi"):
        evaluated = [evaluate_policy(graph, following) for graph in graphs]
        features = np.stack([node["features"] for graph in graphs for node in graph.nodes.values()])
        mean, scale = features.mean(axis=0), features.std(axis=0)
        scale[scale < 1e-8] = 1.
        fitted = cls(mean, scale, np.zeros((1 + 2 * features.shape[1], 2)), ridge)
        labels = []
        for graph, result in zip(graphs, evaluated):
            for history, node in graph.nodes.items():
                labels.append({"config": graph.config.name, "history": history,
                               "state_sha256": policy.state_digest(node["state"]),
                               "q_following": result["q"][history], "q_star": node["q"],
                               "following_action": result["choices"][history],
                               "following_occupancy": result["occupancy"].get(history, 0.)})
        for column, action in enumerate(("READ", "SKIP")):
            xs, ys, ws = [], [], []
            for graph, result in zip(graphs, evaluated):
                histories = [h for h, n in graph.nodes.items() if action in n["q"]]
                if not histories:
                    continue
                occupation = np.array([result["occupancy"].get(h, 0.) for h in histories])
                if occupation.sum() > 0:
                    weight = (1 - occupancy_fraction) / len(histories) + occupancy_fraction * occupation / occupation.sum()
                else:
                    weight = np.full(len(histories), 1 / len(histories))
                fee = graph.config.read_cost if action == "READ" else graph.config.skip_cost
                q = result["q"] if target == "qpi" else {h: n["q"] for h, n in graph.nodes.items()}
                xs.extend(graph.nodes[h]["features"] for h in histories)
                ys.extend(q[h][action] - q[h]["STOP"] + fee for h in histories)
                ws.extend(weight)
            design, weights = fitted.design(np.stack(xs)), np.asarray(ws)
            weights *= len(weights) / weights.sum()
            penalty = ridge * np.eye(design.shape[1]); penalty[0, 0] = 0.
            fitted.weights[:, column] = np.linalg.solve(
                design.T @ (weights[:, None] * design) + penalty,
                design.T @ (weights * np.asarray(ys)))
        return fitted, labels


def metrics(graph, result):
    """Value errors and ranks are measured against Qpi and Qstar separately."""
    rows, rank_rows, improvement, mass_sum = [], [], 0., 0.
    for history, node in graph.nodes.items():
        q = result["q"][history]
        scores = result["predictions"][history]
        mass = result["occupancy"].get(history, 0.)
        action = result["choices"][history]
        improvement += mass * (max(q.values()) - q[action])
        mass_sum += mass
        if not scores or any(a not in scores for a in q):
            continue
        for candidate in q:
            if candidate == "STOP":
                continue
            rows.append({"action": candidate, "prediction": scores[candidate] - scores["STOP"],
                         "qpi": q[candidate] - q["STOP"], "qstar": node["q"][candidate] - node["q"]["STOP"],
                         "occupancy": mass})
        for left, right in itertools.combinations(q, 2):
            truth = q[left] - q[right]
            if abs(truth) > 1e-10:
                rank_rows.append((mass, (scores[left] > scores[right]) == (truth > 0)))
    calibration = {}
    for target in ("qpi", "qstar"):
        calibration[target] = {}
        for weighting in ("uniform", "occupancy"):
            heads = {}
            for head in ("all", "READ", "SKIP"):
                selected = [r for r in rows if head == "all" or r["action"] == head]
                w = np.array([1. if weighting == "uniform" else r["occupancy"] for r in selected])
                error = np.array([r["prediction"] - r[target] for r in selected])
                sign = np.array([(r["prediction"] > 0) == (r[target] > 0) for r in selected])
                denom = float(w.sum())
                heads[head] = {"pairs": len(selected), "weight": denom,
                               "rmse": None if not denom else float(np.sqrt(w @ (error * error) / denom)),
                               "bias": None if not denom else float(w @ error / denom),
                               "sign_accuracy": None if not denom else float(w @ sign / denom)}
            calibration[target][weighting] = heads
    rank_mass = sum(row[0] for row in rank_rows)
    return {"calibration": calibration,
            "qpi_pairwise_rank_accuracy_uniform": None if not rank_rows else float(np.mean([r[1] for r in rank_rows])),
            "qpi_pairwise_rank_accuracy_occupancy": None if not rank_mass else sum(w * right for w, right in rank_rows) / rank_mass,
            "rank_occupancy_denominator": rank_mass,
            "qpi_one_step_improvement_regret_sum": improvement,
            "qpi_one_step_improvement_regret_mean": improvement / mass_sum,
            "expected_decision_count": mass_sum, "global_oracle_gap": result["exact"]["gap"],
            "identity_errors": result["errors"]}
