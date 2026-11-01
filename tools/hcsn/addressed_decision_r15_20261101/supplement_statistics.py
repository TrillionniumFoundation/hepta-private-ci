"""Supplemental fit-level statistics with explicit mean support-failure accounting.

``summarize`` consumes only its arguments. A fit seed, rather than one of its
queries or episodes, is the inferential unit. The CLI accepts a JSON bundle
with explicit training, confirmation, and optional supervisor lists.
"""

import argparse
import itertools
import json
import math
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t


DOMAINS = ("iid", "ood")
ARMS = ("A", "B", "C", "D", "hmm_same_matrix", "free_value",
        "factorized_value", "memoryless_value",
        "learned_state_confidence", "learned_stop_value", "learned_value_risk",
        "learned_ordinary_dual")
METRICS = ("utility", "reward", "fee", "all_queries_correct", "reads", "refreshes", "waits")
USES = (1, 100, 1000, 10000)
EXPECTED_FITS, EXPECTED_EPISODES, EXPECTED_QUERIES = 8, 128, 6
REGISTERED_FIT_SEEDS = (151101, 151103, 151107, 151109, 151113, 151117, 151119, 151123)


def _required(obj, field, location):
    if field not in obj:
        raise ValueError(f"Missing {location}.{field}")
    return obj[field]


def _number(value, location, nonnegative=False):
    if not isinstance(value, (int, float, np.number)) or not math.isfinite(float(value)):
        raise ValueError(f"Expected finite number at {location}")
    value = float(value)
    if nonnegative and value < 0:
        raise ValueError(f"Negative cost/count at {location}")
    return value


def _sample(values):
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or not len(array) or not np.isfinite(array).all():
        raise ValueError("Expected a nonempty finite fit-level vector")
    mean = float(array.mean())
    if len(array) == 1:
        return dict(n=1, mean=mean, sample_sd=None, standard_error=None,
                    t95_interval=[None, None], fit_values=array.tolist())
    sd = float(array.std(ddof=1))
    se = sd / math.sqrt(len(array))
    radius = float(student_t.ppf(.975, len(array) - 1) * se)
    return dict(n=len(array), mean=mean, sample_sd=sd, standard_error=se,
                t95_interval=[mean - radius, mean + radius], fit_values=array.tolist())


def exact_sign_flip(values):
    """Two-sided exhaustive paired sign randomization, including all ties.

    This is exact under the paired sign-exchangeability null, not an assumption-
    free test of every possible population mean null. No Monte Carlo or +1
    correction is used because all 2**n sign assignments are enumerated.
    """
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or not 1 <= len(array) <= 20 or not np.isfinite(array).all():
        raise ValueError("Sign enumeration requires one to twenty finite differences")
    signs = np.asarray(list(itertools.product((-1., 1.), repeat=len(array))))
    observed = abs(float(array.sum()))
    statistics = np.abs(signs @ array)
    tolerance = 16 * np.finfo(float).eps * max(float(np.abs(array).sum()), np.finfo(float).tiny)
    extreme = int(np.count_nonzero(statistics >= observed - tolerance))
    return dict(p_value=extreme / len(signs), assignments=len(signs),
                extreme_assignments=extreme, statistic="absolute sum of paired fit differences",
                null="sign-exchangeability of paired fit differences", ties="included")


def _holm(p_values):
    ordered = sorted(p_values, key=lambda name: (p_values[name], name))
    adjusted, previous = {}, 0.
    for rank, name in enumerate(ordered):
        previous = max(previous, min(1., (len(ordered) - rank) * p_values[name]))
        adjusted[name] = previous
    return adjusted


def _lower_bound(values):
    """Bonferroni lower bound for two outcomes in each of two domains."""
    result = _sample(values)
    lower = None
    if result["n"] > 1:
        critical = float(student_t.ppf(1 - .05 / 4, result["n"] - 1))
        lower = result["mean"] - critical * result["standard_error"]
    return dict(mean=result["mean"], lower=lower, confidence=.9875,
                family_alpha=.05, family_size=4,
                method="one-sided t lower bound; Bonferroni over utility/reward x IID/OOD",
                noninferiority_margin=.01,
                passes=lower is not None and lower > -.01,
                fit_values=result["fit_values"])


def _ratio(numerator, denominator):
    if denominator == 0:
        return None
    return float(numerator / denominator)


def _trace_signature(episode):
    result = []
    for query in episode["queries"]:
        location = f"episode {episode['seed']} query"
        values = tuple(_required(query, field, location)
                       for field in ("query", "key", "deadline", "answer", "target", "reward", "fee", "utility"))
        actions = tuple(tuple(_required(action, field, location + " action")
                              for field in ("action", "step", "token", "time"))
                        for action in _required(query, "actions", location))
        result.append((values, actions))
    return tuple(result)


def _records(training, confirmation):
    if not isinstance(training, list) or not training or not isinstance(confirmation, list):
        raise ValueError("training and confirmation must be explicit nonempty record lists")
    train, observed = {}, {}
    for record in training:
        seed = _required(record, "seed", "training")
        if seed in train:
            raise ValueError(f"Duplicate training fit seed {seed}")
        for field in ("calibration", "ordinary_selected", "light_pattern", "learned",
                      "selection_results", "training_cpu_seconds", "source_commit"):
            _required(record, field, f"training[{seed}]")
        _number(record["training_cpu_seconds"], "training CPU", True)
        train[seed] = record
    for record in confirmation:
        seed, domain = (_required(record, field, "confirmation") for field in ("seed", "domain"))
        if seed not in train or domain not in DOMAINS or (seed, domain) in observed:
            raise ValueError(f"Unknown or duplicate confirmation key {(seed, domain)}")
        for field in ("count", "arms", "world_cpu_seconds", "worker_cpu_seconds", "source_commit",
                      "freeze_commit", "opened_at", "freeze_sha256"):
            _required(record, field, f"confirmation[{seed},{domain}]")
        if not isinstance(record["count"], int) or record["count"] <= 0:
            raise ValueError("Confirmation count must be a positive integer")
        for field in ("world_cpu_seconds", "worker_cpu_seconds"):
            _number(record[field], field, True)
        if record["source_commit"] != train[seed]["source_commit"]:
            raise ValueError(f"Training/confirmation source mismatch for seed {seed}")
        maps = {}
        for arm in ARMS:
            row = _required(record["arms"], arm, "confirmation arms")
            for field in ("episodes", "cpu_seconds", "preparation_cpu", "checkpoint_io_cpu"):
                _required(row, field, f"arm {arm}")
            for field in ("cpu_seconds", "preparation_cpu", "checkpoint_io_cpu"):
                _number(row[field], f"{arm}.{field}", True)
            if len(row["episodes"]) != record["count"]:
                raise ValueError(f"Episode count mismatch for arm {arm}")
            mapping = {}
            for episode in row["episodes"]:
                episode_seed = _required(episode, "seed", f"arm {arm} episode")
                if episode_seed in mapping:
                    raise ValueError("Repeated episode seed within a fit/domain arm")
                _required(episode, "world", "episode")
                queries = _required(episode, "queries", "episode")
                if len(queries) != EXPECTED_QUERIES:
                    raise ValueError("R15 scores exactly six fixed-target queries per episode")
                for metric in METRICS:
                    _number(_required(episode, metric, "episode"), metric,
                            nonnegative=metric != "utility")
                if not 0 <= episode["reward"] <= 1 or not 0 <= episode["all_queries_correct"] <= 1:
                    raise ValueError("Correctness metrics must be probabilities or indicators")
                if abs(episode["utility"] - episode["reward"] + episode["fee"]) > 2e-11:
                    raise ValueError("Episode utility does not equal correctness minus fees")
                for metric in ("reward", "fee", "utility"):
                    trace_mean = float(np.mean([_number(_required(q, metric, "query trace"), metric)
                                                for q in queries]))
                    if abs(episode[metric] - trace_mean) > 2e-11:
                        raise ValueError(f"Episode {metric} disagrees with its query traces")
                if bool(episode["all_queries_correct"]) != all(q["reward"] == 1 for q in queries):
                    raise ValueError("All-query correctness disagrees with query outcomes")
                for metric, action in (("reads", "READ"), ("refreshes", "REFRESH"), ("waits", "WAIT")):
                    actual_count = sum(item["action"] == action for q in queries for item in q["actions"])
                    if episode[metric] != actual_count:
                        raise ValueError(f"Episode {metric} disagrees with its actual action trace")
                _number(_required(episode, "cpu_seconds", "episode"), "episode CPU", True)
                mapping[episode_seed] = episode
            episode_cpu = sum(ep["cpu_seconds"] for ep in mapping.values())
            if abs(row["cpu_seconds"] - episode_cpu) > max(2e-8, episode_cpu * 1e-8):
                raise ValueError(f"{arm}.cpu_seconds must sum episode CPU and exclude cold preparation/IO")
            maps[arm] = mapping
        baseline = maps["D"]
        for arm, mapping in maps.items():
            if set(mapping) != set(baseline):
                raise ValueError(f"Episode seed pairing failed for {arm}")
            for episode_seed, episode in mapping.items():
                if episode["world"] != baseline[episode_seed]["world"]:
                    raise ValueError(f"Hidden tape pairing failed for {arm}")
                actual = [(q["key"], q["deadline"], q["target"]) for q in episode["queries"]]
                expected = [(q["key"], q["deadline"], q["target"]) for q in baseline[episode_seed]["queries"]]
                if actual != expected:
                    raise ValueError(f"Fixed target pairing failed for {arm}")
        observed[seed, domain] = (record, maps)
    expected = {(seed, domain) for seed in train for domain in DOMAINS}
    if set(observed) != expected:
        raise ValueError(f"Missing paired fit/domain records: {sorted(expected - set(observed))}")
    return train, observed


def _training_costs(train, supervisor):
    if supervisor is not None and not isinstance(supervisor, list):
        raise ValueError("Supervisor receipts must be an explicit list")
    receipts = [] if supervisor is None else supervisor
    allocation = {}
    for seed, record in train.items():
        matched = [row for row in receipts if row.get("kind") == "train" and row.get("seed") == seed]
        measured, successes = 0., 0
        for row in matched:
            measured += _number(_required(row, "user_cpu_seconds", "train supervisor"), "user CPU", True)
            measured += _number(_required(row, "system_cpu_seconds", "train supervisor"), "system CPU", True)
            successes += int(_required(row, "exit_code", "train supervisor") == 0)
        function_cpu = float(record["training_cpu_seconds"])
        complete = successes > 0
        if complete and measured + max(.002, function_cpu * .001) < function_cpu:
            raise ValueError(f"Supervisor process CPU is smaller than training function CPU for seed {seed}")
        allocation[seed] = dict(
            cpu_seconds=measured if complete else function_cpu + measured,
            scope="supervisor_process_cpu" if complete else "partial_function_scope",
            function_cpu_seconds=function_cpu, observed_supervisor_cpu_seconds=measured,
            supervisor_attempts=len(matched), successful_attempts=successes,
            complete_process_scope=complete,
            source="all observed same-seed train process attempts" if complete else
                   "function CPU plus any observed failed train attempts; startup/import/final saving incomplete")
    return allocation


def _costs(train, observed, seeds, domain, allocation):
    full_scope = all(allocation[seed]["complete_process_scope"] for seed in seeds)
    by_arm = {}
    for arm in ARMS:
        rows = []
        for seed in seeds:
            record = observed[seed, domain][0]
            item = record["arms"][arm]
            online = item["cpu_seconds"] / record["count"]
            cold = item["preparation_cpu"] + item["checkpoint_io_cpu"]
            search = allocation[seed]["cpu_seconds"]
            curve = {str(n): search + cold + n * online for n in USES}
            rows.append(dict(seed=seed, online_cpu_per_episode=online,
                             preparation_cpu=item["preparation_cpu"],
                             checkpoint_io_cpu=item["checkpoint_io_cpu"],
                             whole_search_cpu_allocated=search,
                             training_cpu_scope=allocation[seed]["scope"],
                             accounted_cpu_by_uses=curve,
                             full_cpu_by_uses=curve if allocation[seed]["complete_process_scope"] else None))
        mean_curve = {str(n): float(np.mean([r["accounted_cpu_by_uses"][str(n)] for r in rows])) for n in USES}
        by_arm[arm] = dict(fits=rows,
                          mean_online_cpu_per_episode=float(np.mean([r["online_cpu_per_episode"] for r in rows])),
                          mean_accounted_cpu_by_uses=mean_curve,
                          mean_full_cpu_by_uses=mean_curve if full_scope else None)
    b, d = by_arm["B"], by_arm["D"]
    ratios = {str(n): _ratio(d["mean_accounted_cpu_by_uses"][str(n)], b["mean_accounted_cpu_by_uses"][str(n)])
              for n in USES}
    online_ratio = _ratio(d["mean_online_cpu_per_episode"], b["mean_online_cpu_per_episode"])
    return dict(arms=by_arm, D_over_B_online_cpu=online_ratio,
                D_over_B_accounted_cpu_by_uses=ratios,
                D_over_B_full_cpu_by_uses=ratios if full_scope else None,
                full_search_process_scope=full_scope,
                ratio_method="ratio of mean costs over paired fit seeds",
                cost_gate_at_1000_uses=full_scope and online_ratio is not None and online_ratio <= .9
                and ratios["1000"] is not None and ratios["1000"] <= .9,
                accounting_contract={
                    "use": "one complete six-query episode",
                    "online": "sum of run_episode CPU / episode count; includes actual owner execution",
                    "cold": "one preparation plus one local disk checkpoint fsync/read/restore; not network/crash recovery",
                    "full": "supervisor user+system CPU for whole training search, including startup/import/final write, + cold + N * online",
                    "allocation": "same entire measured fit search charged to B and D; conservative alternatives, not addends",
                    "world_generation": "reported separately as experiment infrastructure; not silently added to deployment CPU",
                    "scope": "research CPU only; not GPU/energy/communication/native Rust deployment economy"})


def _summarize_retained(training, confirmation, supervisor=None):
    """Return frozen statistics without opening any additional result files."""
    train, observed = _records(training, confirmation)
    seeds = sorted(train)
    allocation = _training_costs(train, supervisor)
    complete = (tuple(seeds) == REGISTERED_FIT_SEEDS
                and all(record.get("development") is False for record in train.values())
                and all(record.get("development") is False
                        and record["count"] == EXPECTED_EPISODES
                        for record, _ in observed.values()))
    result = dict(schema="hcsn-r15-fit-level-summary-v1", fit_seeds=seeds,
                  independent_unit="fit seed; six queries averaged per episode, then episodes per fit",
                  registered_design=dict(fits=EXPECTED_FITS, episodes_per_fit_domain=EXPECTED_EPISODES,
                                         queries_per_episode=EXPECTED_QUERIES,
                                         fit_seeds=list(REGISTERED_FIT_SEEDS),
                                         development_must_be_explicitly_false=True, complete=complete),
                  domains={}, provenance={}, missing=[], admission={})
    p_values, noninferiority = {}, {}
    equivalents = True
    secondary = {
        "D_minus_same_matrix_HMM": ("D", "hmm_same_matrix"),
        "D_minus_free_value": ("D", "free_value"),
        "D_minus_factorized": ("D", "factorized_value"),
        "D_minus_memoryless": ("D", "memoryless_value"),
        "learned_stop_value_minus_state_confidence": ("learned_stop_value", "learned_state_confidence"),
        "learned_value_risk_minus_stop_value": ("learned_value_risk", "learned_stop_value"),
        "learned_value_risk_minus_ordinary_dual": ("learned_value_risk", "learned_ordinary_dual")}
    for domain in DOMAINS:
        means = {arm: {metric: [] for metric in METRICS} for arm in ARMS}
        differences = 0
        for seed in seeds:
            _, maps = observed[seed, domain]
            for arm in ARMS:
                for metric in METRICS:
                    means[arm][metric].append(float(np.mean([ep[metric] for ep in maps[arm].values()])))
            differences += sum(_trace_signature(maps["D"][key]) !=
                               _trace_signature(maps["hmm_same_matrix"][key]) for key in maps["D"])
        equivalents &= differences == 0
        utility = {arm: np.asarray(metrics["utility"]) for arm, metrics in means.items()}
        vectors = {"B_minus_A": utility["B"] - utility["A"],
                   "D_minus_C": utility["D"] - utility["C"],
                   "C_minus_A": utility["C"] - utility["A"],
                   "D_minus_B": utility["D"] - utility["B"],
                   "interaction": utility["D"] - utility["C"] - utility["B"] + utility["A"]}
        contrasts = {name: _sample(values) for name, values in vectors.items()}
        sign = exact_sign_flip(vectors["D_minus_B"])
        p_values[domain] = sign["p_value"]
        guards = {metric: _lower_bound(np.asarray(means["D"][metric]) - np.asarray(means["B"][metric]))
                  for metric in ("utility", "reward")}
        noninferiority[domain] = all(item["passes"] for item in guards.values())
        result["domains"][domain] = dict(
            arms={arm: {metric: _sample(values) for metric, values in metrics.items()}
                  for arm, metrics in means.items()},
            primary_utility_contrasts=contrasts, D_minus_B_sign_flip=sign,
            noninferiority=guards, costs=_costs(train, observed, seeds, domain, allocation),
            secondary={name: {metric: _sample(np.asarray(means[a][metric]) - np.asarray(means[b][metric]))
                              for metric in ("utility", "reward")}
                       for name, (a, b) in secondary.items()},
            secondary_scope="descriptive; no unregistered multiplicity-adjusted efficacy claims",
            same_matrix_HMM_different_episode_traces=differences)
    adjusted = _holm(p_values)
    gain = {}
    for domain in DOMAINS:
        row = result["domains"][domain]
        row["D_minus_B_sign_flip"]["holm_adjusted_p"] = adjusted[domain]
        contrast = row["primary_utility_contrasts"]["D_minus_B"]
        low = contrast["t95_interval"][0]
        gain[domain] = contrast["mean"] >= .01 and low is not None and low > 0 and adjusted[domain] < .05
        row["quality_gain_gate"] = gain[domain]
    result["admission"] = dict(
        design_complete=complete, quality_gain=complete and all(gain.values()),
        quality_gain_rule="Both domains: mean D-B >= .01, descriptive t95 lower > 0, two-domain Holm sign-flip p < .05",
        quality_noninferiority=complete and all(noninferiority.values()),
        quality_guarded_cost=complete and all(noninferiority.values()) and all(
            result["domains"][domain]["costs"]["cost_gate_at_1000_uses"] for domain in DOMAINS),
        cost_rule="Both domains: simultaneous NI for utility and reward; online and full CPU D/B <= .90 at 1000 uses",
        same_matrix_HMM_behavior_identical=equivalents,
        HX_exclusive_operator_gain=False,
        exclusive_claim_reason="Same-matrix HMM is an available implementation of the same finite operator; selected-B gain cannot establish HX exclusivity",
        deployment_economy_admitted=False)
    identities = {field: sorted({record[field] for record, _ in observed.values()})
                  for field in ("source_commit", "freeze_commit", "freeze_sha256")}
    if any(len(values) != 1 for values in identities.values()):
        raise ValueError("Mixed source or freeze identities in one confirmation summary")
    result["provenance"] = dict(**identities,
                                opened_at=[observed[seed, domain][0]["opened_at"]
                                           for seed in seeds for domain in DOMAINS],
                                verification="recorded identities checked internally; remote history verification is separate")
    calibration = []
    accounting_fields = ("all_search_cpu_seconds", "standalone_hx_cpu_seconds", "standalone_free_cpu_seconds",
                         "standalone_same_matrix_hmm_cpu_seconds", "equal_calibration_hx_cpu_seconds",
                         "equal_calibration_hmm_cpu_seconds", "shared_reuse_hmm_incremental_cpu_seconds")
    for seed in seeds:
        accounting = train[seed]["calibration"].get("accounting", {})
        row = dict(seed=seed, ordinary_selected=train[seed]["ordinary_selected"],
                   ordinary_selection_scope="declared selection record; do not equate observed-likelihood selection with task-utility optimality")
        for field in accounting_fields:
            if field in accounting:
                row[field] = _number(accounting[field], f"calibration accounting {field}", True)
            else:
                row[field] = None
                result["missing"].append(f"training[{seed}].calibration.accounting.{field}")
        calibration.append(row)
    result["calibration_standalone_and_reuse"] = dict(
        fits=calibration,
        scope="calibration component only; full measured search plus execution appears in each domain's cost curves",
        reuse_condition="HX calibration already completed and paid; incremental HMM reuse is not independently free learning",
        standalone_columns="alternative deployment accounts, never sum them together")
    result["research_infrastructure"] = dict(
        world_generation_cpu_seconds=sum(record["world_cpu_seconds"] for record, _ in observed.values()),
        confirmation_worker_cpu_seconds=sum(record["worker_cpu_seconds"] for record, _ in observed.values()),
        training_function_cpu_seconds=sum(record["training_cpu_seconds"] for record in train.values()),
        training_allocated_cpu_seconds=sum(item["cpu_seconds"] for item in allocation.values()),
        training_cpu_scope_by_seed={str(seed): item for seed, item in allocation.items()},
        supervisor_receipts=[] if supervisor is None else supervisor,
        supervisor_available=supervisor is not None,
        note="Worker totals are envelopes containing method costs, not additional costs to add to those methods. Supervisor receipt fields are retained without guessing their inclusion semantics.")
    result["scope_limits"] = [
        "Typed addresses and typed distractors are supplied; learned semantic addressing is not established.",
        "The value planner optimizes one current query, not the whole six-query future.",
        "Learned feature comparisons share eager extraction of all features; no lazy feature-cost advantage is inferred.",
        "REFRESH buys an external noisy observation; it is not information-free internal RESET or physical repair.",
        "Confidence intervals are descriptive t intervals over fit means; eight fits do not justify a general asymptotic claim.",
        "No production communication, GPU energy, native Rust cost or continuum-model convergence is measured."]
    return result


def _mean_failure_ledger(confirmation):
    """Validate every mean attempt, retaining failed cost but no invented score."""
    fits, all_invalid = [], []
    for record in confirmation:
        seed, domain, count = record['seed'], record['domain'], record['count']
        arm = _required(record['arms'], 'mean_value', 'supplement arms')
        episodes = _required(arm, 'episodes', 'mean_value')
        if len(episodes) != count:
            raise ValueError('Mean failure ledger must retain every registered attempt')
        reference = {row['seed']: row for row in record['arms']['D']['episodes']}
        seen, invalid, completed, charged_fees = set(), [], 0, 0.
        for episode in episodes:
            episode_seed = _required(episode, 'seed', 'mean episode')
            if episode_seed in seen or episode_seed not in reference:
                raise ValueError('Mean ledger episode coverage is duplicated or mismatched')
            seen.add(episode_seed)
            if _required(episode, 'world', 'mean episode') != reference[episode_seed]['world']:
                raise ValueError('Mean failure ledger does not share the registered world')
            cpu = _number(_required(episode, 'cpu_seconds', 'mean episode'), 'mean episode CPU', True)
            status = _required(episode, 'status', 'mean episode')
            if status == 'invalid_support':
                for field in ('utility', 'reward', 'fee', 'all_queries_correct'):
                    if _required(episode, field, 'invalid mean episode') is not None:
                        raise ValueError('Invalid mean support must retain null outcomes')
                failure = _required(episode, 'failure', 'invalid mean episode')
                if _required(failure, 'observation_likelihood', 'mean failure') != 0:
                    raise ValueError('Only exact zero-support mean failures are isolated')
                query = _required(failure, 'query', 'mean failure')
                finished = _required(failure, 'completed_queries', 'mean failure')
                if not isinstance(query, int) or not 0 <= query < EXPECTED_QUERIES or len(finished) != query:
                    raise ValueError('Mean failure prefix coverage is inconsistent')
                fee_before = _number(_required(failure, 'current_query_fee_before_failed_observation', 'mean failure'), 'fee before failed observation', True)
                failed_fee = _number(_required(failure, 'failed_observation_fee', 'mean failure'), 'failed observation fee', True)
                current_fee = _number(_required(failure, 'current_query_total_incurred_fee', 'mean failure'), 'current incurred fee', True)
                if abs(current_fee - fee_before - failed_fee) > 2e-11:
                    raise ValueError('Mean failure omitted or double-counted the failed observation fee')
                incurred = current_fee + sum(_number(_required(q, 'fee', 'completed prefix query'), 'completed prefix fee', True) for q in finished)
                charged_fees += incurred
                item = dict(fit_seed=seed, domain=domain, episode_seed=episode_seed, world=episode['world'],
                            status=status, query=query,
                            key=_required(failure, 'key', 'mean failure'),
                            token=_required(failure, 'token', 'mean failure'),
                            quality=_required(failure, 'quality', 'mean failure'),
                            completed_step=_required(failure, 'completed_step', 'mean failure'),
                            cpu_seconds=cpu, incurred_prefix_fee=incurred,
                            observation_likelihood=0., performance=None)
                invalid.append(item)
                all_invalid.append(item)
            elif status == 'completed':
                completed += 1
                for metric in METRICS:
                    _number(_required(episode, metric, 'completed mean episode'), metric, metric != 'utility')
                queries = _required(episode, 'queries', 'completed mean episode')
                if len(queries) != EXPECTED_QUERIES:
                    raise ValueError('A completed mean episode must contain all six queries')
                actual = [(q['key'], q['deadline'], q['target']) for q in queries]
                expected = [(q['key'], q['deadline'], q['target']) for q in reference[episode_seed]['queries']]
                if actual != expected:
                    raise ValueError('Completed mean target pairing failed')
                _trace_signature(episode)
                charged_fees += sum(_number(q['fee'], 'completed mean query fee', True) for q in queries)
            else:
                raise ValueError(f'Unregistered mean episode status {status!r}')
        if seen != set(reference):
            raise ValueError('Mean ledger omits registered worlds')
        episode_cpu = sum(_number(ep['cpu_seconds'], 'mean CPU', True) for ep in episodes)
        total_cpu = _number(_required(arm, 'cpu_seconds', 'mean arm'), 'mean arm CPU', True)
        if abs(total_cpu - episode_cpu) > max(2e-8, episode_cpu * 1e-8):
            raise ValueError('Mean arm CPU must include successful and failed attempts')
        preparation = _number(_required(arm, 'preparation_cpu', 'mean arm'), 'mean preparation CPU', True)
        checkpoint = _number(_required(arm, 'checkpoint_io_cpu', 'mean arm'), 'mean checkpoint CPU', True)
        fits.append(dict(seed=seed, domain=domain, expected_attempts=count, attempted=len(episodes),
                         completed=completed, invalid_support=len(invalid),
                         invalid_support_rate=len(invalid) / count,
                         cpu_seconds_all_attempts=total_cpu,
                         cpu_seconds_failed_attempts=sum(item['cpu_seconds'] for item in invalid),
                         preparation_cpu=preparation, checkpoint_io_cpu=checkpoint,
                         total_measured_cpu=total_cpu + preparation + checkpoint,
                         incurred_task_fees_all_attempts=charged_fees,
                         invalid_episode_details=invalid, successful_subset_performance=None))
    by_domain = {}
    for domain in DOMAINS:
        selected = [row for row in fits if row['domain'] == domain]
        attempts = sum(row['attempted'] for row in selected)
        failures = sum(row['invalid_support'] for row in selected)
        by_domain[domain] = dict(attempted=attempts, invalid_support=failures,
                                invalid_support_rate=failures / attempts if attempts else None,
                                cpu_seconds_all_attempts=sum(row['cpu_seconds_all_attempts'] for row in selected),
                                cpu_seconds_failed_attempts=sum(row['cpu_seconds_failed_attempts'] for row in selected),
                                total_measured_cpu=sum(row['total_measured_cpu'] for row in selected),
                                incurred_task_fees_all_attempts=sum(row['incurred_task_fees_all_attempts'] for row in selected))
    return dict(any_invalid_support=bool(all_invalid), fits=fits, domains=by_domain,
                failed_attempts=len(all_invalid), attempted=sum(row['attempted'] for row in fits),
                comparison_rule='Any mean support failure makes all mean performance and D-minus-mean contrasts null in both domains',
                rate_scope='Execution failure incidence over every registered attempt; not a survivor-subset efficacy estimate')


def summarize(training, confirmation, supervisor=None):
    """Supplemental inference for twelve valid arms and a strict mean-failure ledger."""
    # Validate the retained twelve-arm experiment with unchanged formulas.
    result = _summarize_retained(training, confirmation, supervisor)
    supplements = sorted({_required(row, 'supplement_commit', 'supplement confirmation') for row in confirmation})
    manifests = sorted({_required(row, 'supplement_manifest_sha256', 'supplement confirmation') for row in confirmation})
    if len(supplements) != 1 or len(manifests) != 1:
        raise ValueError('Mixed supplemental source or manifest identities')
    if any(row['freeze_commit'] != row['supplement_commit'] for row in confirmation):
        raise ValueError('Supplemental freeze must reference the published supplement commit')
    if any(row.get('schema') != 'hcsn-r15-supplemental-confirmation-v1' for row in confirmation):
        raise ValueError('Original run_01 results cannot be pooled into supplemental efficacy')
    ledger = _mean_failure_ledger(confirmation)
    result['schema'] = 'hcsn-r15-supplement-fit-level-summary-v1'
    result['mean_failure_ledger'] = ledger
    result['provenance'].update(supplement_commit=supplements, supplement_manifest_sha256=manifests,
                                core_source_identity_matches_original_training=True,
                                original_run_01_confirmation_included=False)
    result['registered_design'].update(valid_primary_and_other_arms=list(ARMS),
                                       mean_secondary_attempts_retained=True,
                                       supplement_scope='Execution-only isolation of the declared mean support failure; original estimators and policies unchanged')
    result['admission']['unamended_original_protocol_pass'] = False
    result['admission']['all_thirteen_arms_valid'] = not ledger['any_invalid_support']
    result['admission']['mean_secondary_admissible'] = result['admission']['design_complete'] and not ledger['any_invalid_support']
    for domain in DOMAINS:
        row = result['domains'][domain]
        row['mean_execution_failure_costs'] = ledger['domains'][domain]
        if ledger['any_invalid_support']:
            row['arms']['mean_value'] = None
            row['secondary']['D_minus_mean'] = None
        else:
            records = {item['seed']: item for item in confirmation if item['domain'] == domain}
            metrics = {metric: [float(np.mean([ep[metric] for ep in records[seed]['arms']['mean_value']['episodes']]))
                                for seed in result['fit_seeds']] for metric in METRICS}
            row['arms']['mean_value'] = {metric: _sample(values) for metric, values in metrics.items()}
            row['secondary']['D_minus_mean'] = {
                metric: _sample(np.asarray(row['arms']['D'][metric]['fit_values']) - np.asarray(metrics[metric]))
                for metric in ('utility', 'reward')}
    result['scope_limits'].extend([
        'run_01 stopped in five workers after a declared secondary model lost observation support; its results are not pooled with this fresh supplemental namespace.',
        'Any invalid mean episode blocks all mean efficacy summaries; failed attempts retain actual CPU and incurred task fees without invented rewards.',
        'Original worker costs and supplemental costs must both remain in the cumulative research ledger; standalone method cost curves are not that cumulative experiment bill.'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True,
                        help="JSON bundle, or directory containing explicit summary_input.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    bundle_path = args.run / "summary_input.json" if args.run.is_dir() else args.run
    bundle = json.loads(bundle_path.read_text())
    result = summarize(_required(bundle, "training", "input bundle"),
                       _required(bundle, "confirmation", "input bundle"), bundle.get("supervisor"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(result["admission"], sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
