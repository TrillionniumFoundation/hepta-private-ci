"""Final-policy support and independently fitted linear readout diagnostics.

Fingerprints describe complete declared numerical task inputs, observable state
and the realized finite-cell index. Names, file locations and packet digests are
excluded: they do not enter the policy. Sparse strata enumerate an explicitly
declared Cartesian universe; an empty cell is unobserved, not proven unreachable.
Teacher calibration, actual outcome quality and finite linear recoverability are
separate quantities. These diagnostics do not select checkpoints or thresholds.
"""
import hashlib
import itertools
import json
from collections import Counter, defaultdict

import numpy as np

from ..digital_read_before_20261031.task import legal, public_features

AXES = dict(tick=list(range(7)), budget=list(range(4)), broken=[False, True],
            pending=[False, True], history_count=list(range(4)),
            last_symbol=[-1, 0, 1], latent_index=list(range(17)))
PUBLIC_KEYS = ("deadline", "initial_budget", "duration", "reliability", "read_price",
               "read_delay", "latency_price", "repair_price", "failure_probability")
STATE_KEYS = ("tick", "budget", "pending", "broken", "last_symbol", "last_reliability",
              "history", "elapsed", "charges", "terminal", "submitted")
INPUTS = dict(before_cell=12, after_cell=12, before_full=48, after_full=48)


def _canonical(value):
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        value = value.item()
    if isinstance(value, float):
        if not np.isfinite(value):
            raise ValueError("nonfinite diagnostic input")
        return {"float64": (0. if value == 0 else value).hex()}
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError("unsupported diagnostic input type")


def state_fingerprint(public, state, latent_index):
    """Exact declared input identity, without world/packet identity or rounding."""
    if latent_index is not None and (not isinstance(latent_index, (int, np.integer))
                                     or not 0 <= latent_index < 17):
        raise ValueError("latent index outside declared universe")
    value = dict(public={key: public[key] for key in PUBLIC_KEYS},
                 public_features=public_features(public, state).tolist(),
                 state={key: state[key] for key in STATE_KEYS}, latent_index=latent_index)
    payload = json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def stratum_key(state, latent_index):
    key = (state["tick"], state["budget"], state["broken"], state["pending"] is not None,
           len(state["history"]), state["last_symbol"], int(latent_index))
    if any(value not in allowed for value, allowed in zip(key, AXES.values())):
        raise ValueError("state outside declared stratum universe")
    return json.dumps(key, separators=(",", ":"))


def build_support(behavior_rows, visit_rounds):
    """Index actual supervised support; missing latent support never expands it.

    Rows require public/state and either latent_index or latent_support, the
    latter listing indices with positive mass in an actual supervised update.
    visit_rounds is {round_id: rows}. Observable-only rows remain explicitly
    unqualified for exact latent support, even when their public inputs match.
    """
    result = dict(schema="digital-feedback-support-v1", sources={})
    sources = {"behavior": behavior_rows}
    sources.update({"visit:" + str(key): rows for key, rows in visit_rounds.items()})
    for name, rows in sources.items():
        exact, observable, strata = set(), set(), Counter()
        missing = 0
        for row in rows:
            public, state = row["public"], row["state"]
            observable.add(state_fingerprint(public, state, None))
            if "latent_index" in row:
                indices = [row["latent_index"]]
            elif "latent_support" in row:
                indices = row["latent_support"]
                if not indices:
                    raise ValueError("empty claimed supervised latent support")
            else:
                missing += 1
                indices = []
            for index in sorted(set(indices)):
                exact.add(state_fingerprint(public, state, index))
                strata[stratum_key(state, index)] += 1
        result["sources"][name] = dict(rows=len(rows), missing_latent_support_rows=missing,
            fingerprints=sorted(exact), observable_fingerprints=sorted(observable),
            strata=dict(sorted(strata.items())))
    return result


def _values(public, decision, label):
    mask = np.asarray(legal(public, decision["state"]), dtype=bool)
    q = np.asarray(decision["scores"]["q"], dtype=float)
    teacher = np.asarray(decision["teacher_q"], dtype=float)
    action = decision["action"]
    prediction, target = float(decision["scores"]["belief"]), float(decision["teacher_belief"])
    if (q.shape != (6,) or teacher.shape != (6,) or not 0 <= action < 6 or not mask[action]
            or not np.isfinite(q).all() or not np.isfinite(teacher).all()
            or not 0 <= prediction <= 1 or not 0 <= target <= 1):
        raise ValueError("invalid final-policy decision")
    selected_error = q[action] - teacher[action]
    predicted_sorted, target_sorted = np.sort(q[mask]), np.sort(teacher[mask])
    regret = float(target_sorted[-1] - teacher[action])
    rankings = [(i, j) for i, j in itertools.combinations(np.flatnonzero(mask), 2)
                if abs(teacher[i] - teacher[j]) > 1e-12]
    errors = sum((teacher[i] - teacher[j]) * (q[i] - q[j]) <= 0 for i, j in rankings)
    other = mask.copy()
    other[action] = False
    values = dict(selected_q_error=float(selected_error), selected_q_mse=float(selected_error ** 2),
                  belief_prediction=prediction, belief_teacher=target,
                  belief_calibration_bias=prediction - target,
                  belief_teacher_mse=(prediction - target) ** 2,
                  belief_teacher_expected_brier=(prediction - target) ** 2 + target * (1 - target),
                  teacher_regret=regret, teacher_optimal_action=float(regret <= 1e-12),
                  predicted_margin=float(predicted_sorted[-1] - predicted_sorted[-2]),
                  teacher_margin=float(target_sorted[-1] - target_sorted[-2]),
                  chosen_prediction_margin=float(q[action] - np.max(q[other])),
                  pairwise_ranking_error=float(errors / len(rankings)) if rankings else None,
                  actual_label_brier=None if label is None else (prediction - label) ** 2)
    return values


def _means(rows):
    if not rows:
        return None
    return {name: float(np.mean([row[name] for row in rows if row[name] is not None]))
            if any(row[name] is not None for row in rows) else None for name in rows[0]}


def _calibration(records, actual):
    bins = []
    total = 0
    weighted_error = 0.
    for index in range(10):
        rows = [row for row in records if min(int(row["prediction"] * 10), 9) == index
                and (not actual or row["label"] is not None)]
        targets = [row["label"] if actual else row["target"] for row in rows]
        prediction = float(np.mean([row["prediction"] for row in rows])) if rows else None
        target = float(np.mean(targets)) if rows else None
        gap = abs(prediction - target) if rows else None
        total += len(rows)
        weighted_error += 0. if not rows else len(rows) * gap
        bins.append(dict(lower=index / 10, upper=(index + 1) / 10, count=len(rows),
                         mean_prediction=prediction, mean_target=target, absolute_gap=gap))
    return dict(kind="actual label" if actual else "fitted-law teacher soft target",
                count=total, bins=bins, ece=weighted_error / total if total else None,
                weighting="decision occupancy; decisions are not independent statistical fits")


def audit_episodes(episodes, publics, support):
    """Audit final frozen-policy episodes against every supplied training round.

    publics maps world id to the original public.json object. Actual label
    calibration is computed only when episode['label'] was recorded after task
    termination. Utility/correct/submitted come from actual terminal metrics.
    """
    sources = support["sources"]
    exact = {name: set(value["fingerprints"]) for name, value in sources.items()}
    observable = {name: set(value["observable_fingerprints"]) for name, value in sources.items()}
    strata_values, strata_episodes = defaultdict(list), defaultdict(dict)
    audit, records, values = [], [], []
    all_keys = set().union(*(set(value["strata"]) for value in sources.values()))
    for episode_index, episode in enumerate(episodes):
        if not episode["final_state"]["terminal"] or not episode.get("label_access_after_terminal"):
            raise ValueError("actual outcome requires completed terminal episode")
        public, label = publics[episode["world"]], episode.get("label")
        if label is not None and label not in (0, 1):
            raise ValueError("invalid evaluator-only label")
        for ordinal, decision in enumerate(episode["decisions"]):
            fingerprint = state_fingerprint(public, decision["state"], decision["latent_index"])
            obs = state_fingerprint(public, decision["state"], None)
            key = stratum_key(decision["state"], decision["latent_index"])
            seen = {name: fingerprint in members for name, members in exact.items()}
            metric = _values(public, decision, label)
            values.append(metric)
            strata_values[key].append(metric)
            strata_episodes[key][episode_index] = episode["metrics"]["utility"]
            all_keys.add(key)
            records.append(dict(prediction=float(decision["scores"]["belief"]),
                                target=float(decision["teacher_belief"]), label=label))
            audit.append(dict(world=episode["world"], decision=ordinal, fingerprint=fingerprint,
                              stratum=key, seen_by_source=seen, exact_unseen=not any(seen.values()),
                              observable_seen_by_source={name: obs in members for name, members in observable.items()},
                              action=decision["action"], metrics=metric))
    sparse = []
    for key in sorted(all_keys):
        utilities = list(strata_episodes[key].values())
        sparse.append(dict(key=json.loads(key), evaluation_decisions=len(strata_values[key]),
                           training_counts={name: source["strata"].get(key, 0) for name, source in sources.items()},
                           metrics=_means(strata_values[key]), unique_evaluation_episodes=len(utilities),
                           actual_episode_utility_mean=float(np.mean(utilities)) if utilities else None))
    count = len(audit)
    episodes_count = len(episodes)
    submitted = sum(int(ep["metrics"]["submitted"]) for ep in episodes)
    correct = sum(ep["metrics"]["correct"] for ep in episodes)
    universe_size = int(np.prod([len(value) for value in AXES.values()]))
    return dict(schema="digital-feedback-final-policy-audit-v1", support_scope="exact declared inputs and realized latent index",
        universe=dict(axes=AXES, size=universe_size, sparse_rows=len(sparse),
                      zero_everywhere_strata=universe_size - len(sparse),
                      zero_evaluation_strata=universe_size - sum(bool(rows) for rows in strata_values.values()),
                      missing_row_rule="Every Cartesian stratum absent from sparse_strata has all counts zero and metrics null.",
                      reachability_claim=False),
        counts=dict(episodes=episodes_count, decisions=count, unique_states=len({r["fingerprint"] for r in audit}),
                    exact_unseen=sum(r["exact_unseen"] for r in audit)),
        exact_unseen_rate=sum(r["exact_unseen"] for r in audit) / count if count else None,
        unseen_rate_by_source={name: sum(not r["seen_by_source"][name] for r in audit) / count if count else None for name in sources},
        decision_metrics=_means(values), teacher_calibration=_calibration(records, False),
        actual_label_calibration=_calibration(records, True),
        actual_outcomes=dict(utility_mean=float(np.mean([ep["metrics"]["utility"] for ep in episodes])) if episodes else None,
                             submitted=submitted, correct=correct, submission_rate=submitted / episodes_count if episodes_count else None,
                             accuracy_given_submission=correct / submitted if submitted else None,
                             correct_rate_all_episodes=correct / episodes_count if episodes_count else None),
        sparse_strata=sparse, decisions=audit,
        limitation="Exact empirical overlap and coarse counts do not certify unobserved final-policy support; no mechanism benefit or significance is inferred.")


def extract_pairs(runtime, episodes, publics):
    """Extract matched before/after features on one unchanged-belief population."""
    pairs, counts = [], Counter()
    for episode in episodes:
        public = publics[episode["world"]]
        for ordinal, (before, after) in enumerate(zip(episode["decisions"], episode["decisions"][1:])):
            flags = before["event"]
            group = "event" if flags["event"] else "recovery" if flags["recovery"] else None
            if group is None:
                continue
            if flags["event"] and flags["recovery"]:
                raise ValueError("interval-law transition cannot be both new event and recovery")
            counts["candidate_" + group] += 1
            content = before.get("content")
            if before.get("completion") is not None or (content is not None and "failure" in content):
                counts["excluded_completion_or_failure"] += 1
                continue
            if before["after"] != after["state"] or before["latent_after"] != after["latent_index"]:
                raise ValueError("readout pair is not a contiguous actual transition")
            if before["teacher_belief"] != after["teacher_belief"]:
                counts["excluded_changed_teacher"] += 1
                continue
            x0 = np.concatenate((public_features(public, before["state"]),
                                 runtime.representation(public, before["state"])[before["latent_index"]]))
            x1 = np.concatenate((public_features(public, after["state"]),
                                 runtime.representation(public, after["state"])[after["latent_index"]]))
            pairs.append(dict(id=f"{episode['world']}:{episode['seed']}:{ordinal}", fit=runtime.policy.fit,
                              world=episode["world"], group=group, teacher_before=before["teacher_belief"],
                              teacher_after=after["teacher_belief"], completion=None, content_failure=False,
                              before_cell=x0[-12:].tolist(), after_cell=x1[-12:].tolist(),
                              before_full=x0.tolist(), after_full=x1.tolist()))
            counts["eligible_" + group] += 1
    return dict(pairs=pairs, eligibility=dict(counts),
                status="eligible_pairs" if pairs else "no_eligible_pairs")


def _validate_pairs(pairs):
    identifiers = [row["id"] for row in pairs]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("duplicate decoder pair identity")
    for row in pairs:
        if (row["group"] not in ("event", "recovery") or row["completion"] is not None
                or row["content_failure"] or row["teacher_before"] != row["teacher_after"]
                or not 0 <= row["teacher_before"] <= 1):
            raise ValueError("ineligible decoder pair")
        for name, width in INPUTS.items():
            x = np.asarray(row[name], dtype=float)
            if x.shape != (width,) or not np.isfinite(x).all():
                raise ValueError("invalid decoder feature shape or values")
        if (row["before_cell"] != row["before_full"][-12:]
                or row["after_cell"] != row["after_full"][-12:]):
            raise ValueError("cell/full decoder populations or representations differ")


def train_decoders(train_pairs, ridge=1e-3):
    """Fit JSON-serializable readouts before confirmation data are generated.

    Every group fits four independent affine readouts to the exact same pairs.
    Minimize mean squared target error plus ridge times squared coefficients;
    intercepts are unpenalized, centering uses train data only, no clipping or
    hyperparameter/model selection occurs. Finite linear decodability does not
    bound nonlinear information recovery or establish event/reset causality.
    """
    if not np.isfinite(ridge) or ridge <= 0:
        raise ValueError("positive preregistered ridge required")
    _validate_pairs(train_pairs)
    fits = {p["fit"] for p in train_pairs}
    if len(fits) > 1:
        raise ValueError("decoder must be independently fitted within one model fit")
    groups = {}
    for group in ("event", "recovery", "combined"):
        train = [p for p in train_pairs if group == "combined" or p["group"] == group]
        result = dict(train_count=len(train), status="fitted" if train else "no_eligible_training_pairs", models=None)
        if train:
            target = np.asarray([p["teacher_before"] for p in train])
            models = {}
            for name, width in INPUTS.items():
                x = np.asarray([p[name] for p in train])
                mean, target_mean = x.mean(0), target.mean()
                xc = x - mean
                coefficients = np.linalg.solve(xc.T @ xc / len(x) + ridge * np.eye(width),
                                               xc.T @ (target - target_mean) / len(x))
                intercept = float(target_mean - mean @ coefficients)
                models[name] = dict(coefficients=coefficients.tolist(), intercept=intercept,
                                    training_mean=mean.tolist(), training_target_mean=float(target_mean),
                                    training_scale=[1.] * width)
            result["models"] = models
        groups[group] = result
    return dict(schema="digital-feedback-ridge-artifact-v1", fit=next(iter(fits)) if fits else None,
                ridge=ridge, groups=groups, training_pair_ids=sorted(p["id"] for p in train_pairs),
                training_worlds=sorted({p["world"] for p in train_pairs}),
                training_pairs_sha256=hashlib.sha256(json.dumps(train_pairs, sort_keys=True, allow_nan=False).encode()).hexdigest(),
                fitting_rule="mean squared target error plus ridge coefficient penalty; unpenalized intercept; no feature scaling",
                training_used_confirmation=False,
                limitation="Independently fitted linear readout on matched selected populations; no irrecoverable-information-loss or causal-utility claim.")


def evaluate_decoders(artifact, test_pairs):
    """Evaluate already frozen coefficients without fitting or recalibration."""
    if artifact["schema"] != "digital-feedback-ridge-artifact-v1" or artifact["training_used_confirmation"]:
        raise ValueError("invalid frozen decoder artifact")
    _validate_pairs(test_pairs)
    if (set(artifact["training_pair_ids"]) & {p["id"] for p in test_pairs}
            or set(artifact["training_worlds"]) & {p["world"] for p in test_pairs}):
        raise ValueError("decoder train/test identities overlap")
    fits = {p["fit"] for p in test_pairs}
    if len(fits) > 1 or (fits and artifact["fit"] is not None and fits != {artifact["fit"]}):
        raise ValueError("decoder and test pairs belong to different fits")
    groups = {}
    for group, fitted in artifact["groups"].items():
        test = [p for p in test_pairs if group == "combined" or p["group"] == group]
        status = "no_eligible_training_pairs" if fitted["models"] is None else "complete" if test else "no_eligible_pairs"
        result = dict(train_count=fitted["train_count"], test_count=len(test), status=status,
                      mse=None, paired_mse_difference_after_minus_before=None, predictions=None)
        if status == "complete":
            target = np.asarray([p["teacher_before"] for p in test])
            predictions = {}
            for name, width in INPUTS.items():
                model = fitted["models"][name]
                coefficients = np.asarray(model["coefficients"])
                if coefficients.shape != (width,) or not np.isfinite(coefficients).all():
                    raise ValueError("invalid frozen decoder coefficients")
                predictions[name] = np.asarray([p[name] for p in test]) @ coefficients + model["intercept"]
                if not np.isfinite(predictions[name]).all():
                    raise FloatingPointError("nonfinite frozen decoder prediction")
            paired = {scope: ((predictions["after_" + scope] - target) ** 2
                             - (predictions["before_" + scope] - target) ** 2) for scope in ("cell", "full")}
            result.update(mse={k: float(np.mean((v - target) ** 2)) for k, v in predictions.items()},
                          paired_mse_difference_after_minus_before={k: float(v.mean()) for k, v in paired.items()},
                          predictions=[dict(id=p["id"], group=p["group"], target=float(target[i]),
                                            predicted={k: float(v[i]) for k, v in predictions.items()},
                                            paired_mse_difference={k: float(v[i]) for k, v in paired.items()})
                                       for i, p in enumerate(test)])
        groups[group] = result
    return dict(schema="digital-feedback-independent-ridge-decoder-v1", fit=artifact["fit"],
                ridge=artifact["ridge"], groups=groups, fitted_during_evaluation=False,
                artifact_sha256=hashlib.sha256(json.dumps(artifact, sort_keys=True, allow_nan=False).encode()).hexdigest(),
                limitation=artifact["limitation"])


def fit_decoder(train_pairs, test_pairs, ridge=1e-3):
    """Development convenience; formal execution publishes train_decoders first."""
    return evaluate_decoders(train_decoders(train_pairs, ridge), test_pairs)
