"""Independent audit of serialized renewal worlds, actions and predictions.

No candidate simulator, controller, neural model, or aggregation function is
imported. Scores, information access, count mixtures and paired effects are
recomputed from raw records. This is an audit, not an additional model trial.
"""

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.special import log_ndtr, ndtr


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def independent_count_law(gap, horizon, physics, remaining, size):
    """Separate scalar first-passage/convolution reconstruction of saved laws."""
    tails = [1.0]
    for count in range(1, size + 1):
        duration = horizon - remaining - (count - 1) * physics["refractory"]
        distance = gap + (count - 1) * physics["reset"]
        if duration <= 0:
            tails.append(0.0)
            continue
        scale = physics["sigma"] * math.sqrt(duration)
        first = ndtr((-distance - physics["nu"] * duration) / scale)
        second_log = (-2 * physics["nu"] * distance / physics["sigma"] ** 2
                      + log_ndtr((-distance + physics["nu"] * duration) / scale))
        tails.append(min(1.0, max(0.0, float(first + math.exp(second_log)))))
    probabilities = np.maximum(0.0, -np.diff(tails))
    return probabilities / probabilities.sum(), tails[-1]


def audit_fit(directory):
    """Inspect the ordinary fit's saved training cohort and weight identity."""
    import torch
    directory = Path(directory)
    job, report = read(directory / "job.json"), read(directory / "training.json")
    checkpoint = torch.load(directory / "ordinary.pt", map_location="cpu", weights_only=True)
    with np.load(directory / "training.npz", allow_pickle=False) as source:
        features, labels = source["features"], source["labels"]
        physics = source["training_true_physics"]
    errors = []
    if checkpoint["report"] != report or any(job[key] != report[key] for key in
            ("seed", "train_size", "epochs", "width", "cap")):
        errors.append("Ordinary fit/checkpoint report differs from its declared job")
    if (features.shape != (job["train_size"], 7) or labels.shape != (job["train_size"],)
            or physics.shape != (job["train_size"], 4)
            or not np.isfinite(features).all() or not np.isfinite(physics).all()
            or not np.issubdtype(labels.dtype, np.integer)
            or np.any(labels < 0) or np.any(labels >= job["cap"])):
        errors.append("Ordinary fit training evidence is malformed")
    if not np.allclose(features[:, 4:6], physics[:, 2:4], rtol=1e-6, atol=1e-8):
        errors.append("Training features do not expose the declared public reset/refractory constants")
    refractory = features[:, 6] > 0
    if not np.allclose(features[refractory, 0], features[refractory, 4], rtol=1e-6, atol=1e-8):
        errors.append("Refractory training packet exposes an inconsistent reset gap")
    possible = (labels == 0) | ((labels - 1) * features[:, 5] < features[:, 1] - features[:, 6])
    if not possible.all():
        errors.append("An ordinary training label violates the common physical support")
    state = checkpoint["state_dict"]
    parameters = sum(value.numel() for value in state.values())
    if parameters != report["parameters"] or not all(bool(torch.isfinite(value).all()) for value in state.values()):
        errors.append("Ordinary learned weight count/finite values differ from declaration")
    return dict(directory=str(directory), audit_ok=not errors, errors=errors,
        training_rows=len(labels), observed_input_dimensions=features.shape[1],
        trainable_parameters=parameters, positive_refractory_packets=int(refractory.sum()),
        count_label_histogram=np.bincount(labels, minlength=job["cap"]).tolist(),
        estimated_parameter_mse=np.square(features[:, 2:4] - physics[:, :2]).mean(axis=0).tolist(),
        source_prior="Exact renewal structure is encoded in the analytic core; ordinary core fits finite sampled IG labels",
        hashes={name: digest(directory / name) for name in
                ("job.json", "training.json", "training.npz", "ordinary.pt")})


def audit_run(directory, *, allow_heldout=False):
    directory = Path(directory)
    job, selection = read(directory / "job.json"), read(directory / "selection.json")
    if job["split"] == "test" and not allow_heldout:
        raise PermissionError("Heldout mechanism records are not authorized yet")
    summary, episodes = read(directory / "summary.json"), rows(directory / "episodes.jsonl")
    config, errors = summary["config"], []
    if (not selection.get("written_before_episode_generation")
            or selection.get("test_based_selection") is not False
            or selection.get("config") != config):
        errors.append("Mechanism configuration was not frozen before episode generation")
    checkpoint_sha = digest(selection["checkpoint"])
    if checkpoint_sha != selection["checkpoint_sha256"] or checkpoint_sha != summary["checkpoint_sha256"]:
        errors.append("Ordinary propagator checkpoint identity mismatch")
    if len(episodes) != job["episodes"]:
        errors.append("Episode cohort size differs from registered job")
    grouped = {}
    for name in ("trace", "access", "predictions"):
        groups = defaultdict(list)
        for row in rows(directory / (name + ".jsonl")):
            groups[(row["episode"], row["arm"])].append(row)
        grouped[name] = groups
    declared = {(row["episode"], row["arm"]): row for row in summary["episodes"]}
    if len(declared) != len(summary["episodes"]) or set(grouped["predictions"]) != set(declared):
        errors.append("Duplicate or missing arm/episode evidence")
    dt, classes = config["dt"], config["classes"]
    matrix = np.zeros((classes, classes))
    for source in range(classes):
        matrix[source, source] = .15
        matrix[(source + 1) % classes, source] = .55
        matrix[(source - 1) % classes, source] = .30
    audited, max_mixture_error, max_score_error, max_law_error = [], 0.0, 0.0, 0.0
    expected_arms = {"ordinary_gated__lightweight", "ordinary_gated__task_value",
        "analytic__lightweight", "analytic__task_value",
        "analytic__task_value__forecast_risk_suppressed",
        "ordinary_gated__fixed_analytic_lightweight_actions",
        "frozen_content__fixed_analytic_lightweight_actions"}
    for index, episode in enumerate(episodes):
        expected_seed = int(np.random.SeedSequence([job["seed"], index,
            311 if job["split"] == "development" else 929]).generate_state(1)[0])
        if episode["seed"] != expected_seed:
            errors.append("Episode seed is outside registered split namespace")
        if {key[1] for key in declared if key[0] == index} != expected_arms:
            errors.append("Episode does not contain all seven preregistered arms")
        prescribed = [(c, v) for c in ("ordinary_gated", "analytic")
                      for v in ("lightweight", "task_value")]
        np.random.default_rng(episode["seed"] + 501).shuffle(prescribed)
        if [f"{core}__{control}" for core, control in prescribed] != episode["predetermined_arm_order"]:
            errors.append("Primary arm execution order differs from its predefined randomization")
        world = episode["path"]
        physics = episode["calibration"]["true"]
        estimated = episode["calibration"]["estimated"]
        events = world["events"]
        event_times = np.asarray([event["time"] for event in events])
        if np.any(np.diff(event_times) <= physics["refractory"]):
            errors.append("World events violate their refractory residence")
        if len(world["x"]) != config["ticks"] + 1:
            errors.append("Incomplete physical world chronology")
        for tick, (gap, remaining, content) in enumerate(zip(world["x"], world["refractory_remaining"], world["content"], strict=True)):
            now = tick * dt
            if not math.isfinite(gap) or gap <= 0 or not math.isfinite(remaining) or remaining < 0:
                errors.append("Invalid observed gap or refractory time")
            last = int(np.searchsorted(event_times, now, side="right")) - 1
            expected_rest = max(event_times[last] + physics["refractory"] - now, 0) if last >= 0 else 0
            if not math.isclose(remaining, expected_rest, abs_tol=1e-10):
                errors.append("Saved refractory state differs from event record")
            if remaining > 0 and not math.isclose(gap, physics["reset"], abs_tol=1e-10):
                errors.append("A refractory observation exposes an inconsistent reset state")
            if last >= 0 and content != events[last]["after"]:
                errors.append("Saved content differs from last actual event")
        for earlier, later in zip(events, events[1:]):
            if earlier["after"] != later["before"]:
                errors.append("Content transition chain is inconsistent")
        for key in sorted(k for k in declared if k[0] == index):
            expected = declared[key]
            trace, accesses = grouped["trace"][key], grouped["access"][key]
            predictions = grouped["predictions"][key]
            trace_by_tick = {row["tick"]: row for row in trace}
            access_by_tick = {row["reveal_tick"]: row for row in accesses}
            if len(trace_by_tick) != len(trace) or len(access_by_tick) != len(accesses):
                errors.append("Repeated action or observation at one tick")
            if [row["tick"] for row in trace] != list(range(len(trace))):
                errors.append("Control chronology omits or reorders decision ticks")
            if "__fixed_analytic_lightweight_actions" in key[1]:
                original = grouped["trace"][index, "analytic__lightweight"]
                replay = [(r["tick"], r["executed_action"], r["observed_state"]) for r in trace]
                source = [(r["tick"], r["executed_action"], r["observed_state"]) for r in original]
                if replay != source:
                    errors.append("Fixed-action core comparison changes actions or observations")
            initial = dict(time=0., x=episode["initial_x"], refractory_remaining=0.,
                           content_probs=[1 / classes] * classes, has_read=False)
            for access in accesses:
                reveal, request = access["reveal_tick"], access["request_tick"]
                if reveal != request + 1 or trace_by_tick.get(request, {}).get("executed_action") != "READ":
                    errors.append("A READ observation has no preceding paid request")
                observed = dict(time=reveal * dt, x=world["x"][reveal],
                    refractory_remaining=world["refractory_remaining"][reveal],
                    content_probs=np.eye(classes)[world["content"][reveal]].tolist(), has_read=True)
                if access["observed_state"] != observed or access["external_state_reset"] is not False:
                    errors.append("READ is not a truthful observation of the common unreset world")
            reads, stopped_at = 0, None
            for record in trace:
                tick = record["tick"]
                if stopped_at is not None:
                    errors.append("Actions continue after STOP")
                past = [time for time in access_by_tick if time <= tick]
                current = access_by_tick[max(past)]["observed_state"] if past else initial
                if record["observed_state"] != current or record["physical_estimates"] != estimated:
                    errors.append("Arm information differs from its last revealed state/shared calibration")
                if record["actual_future_available_to_policy"] is not False:
                    errors.append("Policy admits actual future access")
                action = record["executed_action"]
                reads += action == "READ"
                if action not in ("READ", "WAIT", "STOP") or record["budget_after"] != config["budget"] - reads or reads > config["budget"]:
                    errors.append("Illegal action or acquisition-budget accounting")
                if action == "READ" and tick + 1 not in access_by_tick:
                    errors.append("Paid READ did not deliver a new observation")
                if action == "STOP":
                    stopped_at = tick
                detail = record["policy_detail"]
                if "candidate_values" in detail:
                    best = max(detail["candidate_values"], key=lambda row: (row["net_value"], -row["arrival_tick"]))
                    request = "STOP" if best["net_value"] <= 0 else "READ" if best["arrival_tick"] == tick + 1 else "WAIT"
                    if request != record["requested_action"] or best["arrival_tick"] != detail["selected_arrival"]:
                        errors.append("Task-value action differs from recorded candidate argmax")
            scores = []
            if [row["tick"] for row in predictions] != config["deadlines"]:
                errors.append("STOP/READ changed the mandatory output schedule")
            for prediction in predictions:
                tick = prediction["tick"]
                past = [time for time in access_by_tick if time <= tick]
                current = access_by_tick[max(past)]["observed_state"] if past else initial
                if prediction["observed_state"] != current:
                    errors.append("Forecast condition differs from last actual observation")
                horizon = tick * dt - current["time"]
                if not math.isclose(prediction["horizon_since_read"], horizon, abs_tol=1e-12):
                    errors.append("Forecast horizon is inconsistent")
                probabilities = np.asarray(prediction["probabilities"], float)
                counts = np.asarray(prediction["count_probabilities"], float)
                if (not np.isfinite(probabilities).all() or not np.isfinite(counts).all()
                        or np.any(probabilities < 0) or np.any(counts < 0)
                        or abs(probabilities.sum() - 1) > 1e-6 or abs(counts.sum() - 1) > 1e-6):
                    errors.append("Malformed content or event-count probability law")
                if key[1].startswith("analytic__"):
                    independent, tail = independent_count_law(current["x"], horizon,
                        estimated, current["refractory_remaining"], len(counts))
                    law_error = float(np.abs(independent - counts).max())
                    max_law_error = max(max_law_error, law_error)
                    if law_error > 1e-9 or tail > 1e-8:
                        errors.append("Analytic count law differs from independent first-passage reconstruction")
                distribution = np.asarray(current["content_probs"], float)
                mixture = np.zeros(classes)
                for weight in counts:
                    mixture += weight * distribution
                    distribution = matrix @ distribution
                mixture_error = float(np.max(np.abs(mixture - probabilities)))
                max_mixture_error = max(max_mixture_error, mixture_error)
                if (mixture_error > 1e-9
                        or abs(1 - counts[0] - prediction["event_probability"]) > 1e-9
                        or abs(counts @ np.arange(len(counts)) - prediction["expected_events"]) > 1e-9):
                    errors.append("Content/count/probability/expected-count contract disagrees")
                truth = world["content"][tick]
                actual = dict(correct=int(probabilities.argmax() == truth),
                    nll=-math.log(max(probabilities[truth], 1e-12)),
                    brier=float(np.square(probabilities - np.eye(classes)[truth]).sum()))
                if prediction["truth_for_scoring_only"] != truth:
                    errors.append("Scoring target differs from the common world")
                score_error = max(abs(actual[name] - prediction[name]) for name in actual)
                max_score_error = max(max_score_error, score_error)
                if score_error > 1e-10:
                    errors.append("Saved prediction score differs from raw probabilities")
                scores.append(actual)
            recomputed = {name: float(np.mean([row[source] for row in scores])) for name, source in
                          (("accuracy", "correct"), ("nll", "nll"), ("brier", "brier"))}
            recomputed.update(reads=reads, read_cost=reads * config["read_cost"])
            recomputed["net_reward"] = recomputed["accuracy"] - recomputed["read_cost"]
            for name, value in recomputed.items():
                if not math.isclose(value, expected[name], abs_tol=1e-10):
                    errors.append("Arm summary differs from raw evidence: " + name)
            audited.append(dict(episode=index, arm=key[1], seed=episode["seed"], **recomputed))
    lookup = {(row["episode"], row["arm"]): row for row in audited}
    interaction = []
    for index in range(len(episodes)):
        a = lookup[index, "ordinary_gated__lightweight"]["net_reward"]
        b = lookup[index, "ordinary_gated__task_value"]["net_reward"]
        c = lookup[index, "analytic__lightweight"]["net_reward"]
        d = lookup[index, "analytic__task_value"]["net_reward"]
        interaction.append(dict(episode=index, core_at_lightweight=c - a,
            core_at_task_value=d - b, control_at_ordinary=b - a,
            control_at_analytic=d - c, interaction=d - b - c + a))
    return dict(schema="hcsn-independent-mechanism-audit.v2", directory=str(directory),
        job=job, errors=errors, audit_ok=not errors, metrics=audited, paired_effects=interaction,
        maximum_mixture_error=max_mixture_error, maximum_score_error=max_score_error,
        maximum_independent_law_error=max_law_error,
        hashes={name: digest(directory / name) for name in ("job.json", "selection.json", "summary.json",
            "episodes.jsonl", "trace.jsonl", "access.jsonl", "predictions.jsonl")},
        scope="Raw evidence consistency and task utility including READ fees; measured compute cost remains separate")


def audit_grid(directory):
    """Independently score every saved Monte Carlo label and variant law."""
    directory = Path(directory)
    job, selection, summary = (read(directory / name) for name in
                               ("job.json", "selection.json", "summary.json"))
    cases, predictions = rows(directory / "cases.jsonl"), rows(directory / "predictions.jsonl")
    errors, recomputed = [], []
    if not selection.get("written_before_case_generation") or not selection.get("grid_is_predeclared"):
        errors.append("Grid was not fixed before label generation")
    if digest(job["checkpoint"]) != job["checkpoint_sha256"]:
        errors.append("Grid checkpoint identity mismatch")
    if [case["case"] for case in cases] != list(range(job["cases"])):
        errors.append("Missing/duplicate grid cases")
    by_case = {case["case"]: case for case in cases}
    by_pair = {(row["case"], row["variant"]): row for row in predictions}
    if len(by_pair) != len(predictions) or len(predictions) != len(cases) * len(selection["variants"]):
        errors.append("Missing/duplicate grid variant predictions")
    matrix = np.zeros((5, 5))
    for column in range(5):
        matrix[column, column] = .15
        matrix[(column + 1) % 5, column] = .55
        matrix[(column - 1) % 5, column] = .30
    max_score_error, max_numeric_error, max_law_error = 0.0, 0.0, 0.0
    for prediction in predictions:
        case = by_case[prediction["case"]]
        counts, labels = np.asarray(case["sample_counts"]), np.asarray(case["sample_content"])
        law, content = np.asarray(prediction["count_probabilities"]), np.asarray(prediction["content_probabilities"])
        if (len(counts) != job["samples_per_case"] or len(labels) != len(counts)
                or np.any(counts < 0) or np.any(counts >= len(law)) or np.any(labels < 0) or np.any(labels >= 5)
                or not np.isfinite(law).all() or not np.isfinite(content).all()
                or np.any(law < 0) or np.any(content < 0)
                or abs(law.sum() - 1) > 1e-6 or abs(content.sum() - 1) > 1e-6):
            errors.append("Invalid raw label or predictive distribution on grid")
        current, mixture = np.eye(5)[case["initial_class"]], np.zeros(5)
        for probability in law:
            mixture += probability * current
            current = matrix @ current
        if not np.allclose(mixture, content, atol=1e-9, rtol=1e-9):
            errors.append("Grid content prediction differs from count mixture")
        mean = float(law @ np.arange(len(law)))
        actual = dict(expected_count=mean, predicted_event_probability=float(1 - law[0]),
            count_nll=float(-np.log(np.maximum(law[counts], 1e-12)).mean()),
            content_nll=float(-np.log(np.maximum(content[labels], 1e-12)).mean()),
            content_brier=float(np.square(content[None] - np.eye(5)[labels]).sum(axis=1).mean()),
            content_accuracy=float((labels == content.argmax()).mean()),
            count_mean_squared_error=float(np.square(mean - counts).mean()),
            event_brier=float(np.square(1 - law[0] - (counts > 0)).mean()))
        error = max(abs(actual[name] - prediction[name]) for name in actual)
        max_score_error = max(error, max_score_error)
        if error > 1e-10:
            errors.append("Grid score differs from saved raw labels")
        recomputed.append(dict(case=case["case"], variant=prediction["variant"], **actual))
    numeric = []
    for case in cases:
        index = case["case"]
        a = np.asarray(by_pair[index, "analytic_full_distribution"]["count_probabilities"])
        n = np.asarray(by_pair[index, "matched_numerical_integral"]["count_probabilities"])
        error = float(np.max(np.abs(a - n)))
        max_numeric_error = max(max_numeric_error, error)
        numeric.append(dict(case=index, error=error, tolerance_met=error <= 1e-8))
        if error > 1e-8:
            errors.append("Closed-form/numerical grid disagreement exceeds registered tolerance")
        reconstructed = sum(weight * independent_count_law(gap, case["horizon"],
            case["shared_calibration"]["estimated"], case["refractory_remaining"], len(a))[0]
            for gap, weight in zip(case["gaps"], case["weights"], strict=True))
        law_error = float(np.abs(reconstructed - a).max())
        max_law_error = max(max_law_error, law_error)
        if law_error > 1e-9:
            errors.append("Grid analytic law differs from independent first-passage reconstruction")
    aggregates = {}
    for variant, declared in summary["aggregate"].items():
        selected = [row for row in recomputed if row["variant"] == variant]
        actual = {name: float(np.mean([row[name] for row in selected])) for name in
                  ("content_nll", "content_brier", "content_accuracy", "event_brier", "count_nll")}
        for name, value in actual.items():
            if not math.isclose(value, declared[name], abs_tol=1e-10):
                errors.append("Grid aggregate differs from independently recomputed scores")
        aggregates[variant] = actual
    aliases = []
    if len(cases) >= 2:
        moments = []
        for case in cases[:2]:
            gaps, weights = np.asarray(case["gaps"]), np.asarray(case["weights"])
            mean = float(weights @ gaps)
            variance = float(weights @ gaps ** 2 - mean ** 2)
            moments.append((mean, variance))
        if not np.allclose(moments[0], moments[1], atol=1e-12, rtol=0):
            errors.append("Advertised equal-mean/variance posterior pair does not match")
        if cases[0]["shared_calibration"]["estimated"] != cases[1]["shared_calibration"]["estimated"]:
            errors.append("Posterior alias pair has different calibrated dynamics")
        distance = float(np.abs(np.asarray(by_pair[0, "analytic_full_distribution"]["content_probabilities"])
            - np.asarray(by_pair[1, "analytic_full_distribution"]["content_probabilities"])).sum())
        aliases.append(dict(moments=moments, content_l1_distance=distance,
                            distinct_content_despite_equal_two_moments=distance > 1e-8))
    return dict(directory=str(directory), errors=errors, audit_ok=not errors,
        raw_score_rows=len(recomputed), cases=len(cases), aggregates=aggregates,
        maximum_score_error=max_score_error, maximum_numeric_error=max_numeric_error,
        maximum_independent_law_error=max_law_error,
        matched_precision=numeric, equal_moments_witnesses=aliases,
        hashes={name: digest(directory / name) for name in
                ("job.json", "selection.json", "summary.json", "cases.jsonl", "predictions.jsonl")})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, action="append", default=[])
    parser.add_argument("--fit", type=Path, action="append", default=[])
    parser.add_argument("--diagnostics", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-heldout", action="store_true")
    args = parser.parse_args()
    if not args.run and not args.diagnostics and not args.fit:
        parser.error("Supply a mechanism run or grid diagnostics directory")
    results = [audit_run(path, allow_heldout=args.allow_heldout) for path in args.run]
    diagnostics = [audit_grid(path) for path in args.diagnostics]
    fits = [audit_fit(path) for path in args.fit]
    value = dict(audit_source_sha256=digest(__file__), runs=results, grid_diagnostics=diagnostics,
                 fits=fits, audit_ok=all(row["audit_ok"] for row in results + diagnostics + fits))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"audit_ok": value["audit_ok"], "runs": len(results)}))


if __name__ == "__main__":
    main()
