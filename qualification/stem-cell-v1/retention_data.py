"""V7 diverse train-only relations and explicit joint learning qualifications."""
from dataclasses import asdict
import math

from binding_protocol import (_digest, _new_domain, _old_cases, _source_key,
    retention_gate, semantic_key, verify_binding_cases)
from multirc_data import score_multirc


def build_augmentation(parts):
    """Generate 256 new groups, excluding every historical/reserved task and source."""
    excluded = tuple(_old_cases()) + tuple(c for cases in parts.values() for c in cases)
    tasks = {semantic_key(c) for c in excluded}
    sources = {_source_key(c) for c in excluded}
    cases = tuple(c for shard in range(8) for c in _new_domain(
        f"retention-v7-augmentation-{shard}", 1701, tasks, sources))
    report = verify_binding_cases(cases)
    if (report["cases"] != 1024 or report["groups"] != 256
            or any(c.source_split != "train" for c in cases)
            or {semantic_key(c) for c in cases} & {semantic_key(c) for c in excluded}
            or {_source_key(c) for c in cases} & {_source_key(c) for c in excluded}):
        raise ValueError("complete, disjoint, train-only augmentation required")
    return cases, dict(report, complete_labeled_cases_sha256=_digest([asdict(c) for c in cases]),
        excluded_tasks_sha256=_digest(sorted({semantic_key(c) for c in excluded})),
        excluded_sources_sha256=_digest(sorted({_source_key(c) for c in excluded})),
        labels_reconstructed_by_grammar=True, fresh_scores_used=False,
        vocabulary="same_generator_people_objects_colors_as_old_train",
        chain_structure="two_hop_ownership_storage", longer_chain=False)


def natural_metrics(cases, probabilities):
    """Score complete natural questions with fixed raw p>0.5 and saved-probability CE."""
    cases, probabilities = tuple(cases), tuple(probabilities)
    if not cases or len(cases) != len(probabilities) or any(
            type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1
            for p in probabilities):
        raise ValueError("complete aligned finite natural probabilities required")
    result = score_multirc(cases, [int(p > .5) for p in probabilities])
    result["probability_CE"] = -sum(math.log(max(1e-12, p if c.label else 1 - p))
                                   for c, p in zip(cases, probabilities)) / len(cases)
    return result


def natural_baselines(cases):
    """Constants are fitted using only the complete natural training partition."""
    cases = tuple(cases)
    if not cases or any(c.source_split != "train" for c in cases):
        raise ValueError("nonempty natural training partition required")
    prior = sum(c.label for c in cases) / len(cases)
    if not 0 < prior < 1:
        raise ValueError("both natural training classes required")
    return dict(positive_prior=prior, majority_class=int(prior > .5),
        prior_constant_CE=-prior * math.log(prior) - (1-prior) * math.log(1-prior),
        always_negative=natural_metrics(cases, [0.] * len(cases)),
        always_positive=natural_metrics(cases, [1.] * len(cases)),
        training_only=True, threshold_selected=False)


def joint_gate(old_train, old_baseline, relation_internal, natural_train,
               natural_start, constants):
    """Require retention, internal relation transfer and actual natural-task learning."""
    retained = retention_gate(old_train, old_baseline)
    if (relation_internal.get("cases") != 64 or relation_internal.get("groups") != 16
            or relation_internal.get("paired_candidates") != 32
            or natural_train.get("candidates") != natural_start.get("candidates")
            or natural_train.get("questions") != natural_start.get("questions")
            or natural_train.get("candidates", 0) <= 0):
        raise ValueError("complete old internal and identical natural-training panels required")
    checks = ((relation_internal, ("accuracy", "both_worlds_correct")),
              (natural_train, ("f1_m", "f1_a", "exact_match", "probability_CE")),
              (natural_start, ("f1_a",)),
              (constants["always_negative"], ("f1_m",)),
              (constants["always_positive"], ("f1_m",)))
    if any(type(m.get(k)) not in (int, float) or not math.isfinite(m[k])
           or m[k] < 0 or k != "probability_CE" and m[k] > 1 for m, keys in checks for k in keys):
        raise ValueError("finite bounded complete gate metrics required")
    if (type(constants.get("prior_constant_CE")) not in (int, float)
            or not math.isfinite(constants["prior_constant_CE"]) or constants["prior_constant_CE"] <= 0):
        raise ValueError("positive finite training-prior entropy required")
    cheap = max(constants[k]["f1_m"] for k in ("always_negative", "always_positive"))
    requirements = dict(relation_candidate=.75, relation_pairs=.50,
        natural_F1m_over_best_constant=.05, natural_F1a_over_start=.05,
        natural_EM=.05, natural_CE_ratio_to_prior=.95)
    reasons = ["retention:" + r for r in retained["reasons"]]
    for passed, reason in (
        (relation_internal["accuracy"] + 1e-12 >= .75, "relation_candidate_below_0.75"),
        (relation_internal["both_worlds_correct"] + 1e-12 >= .50, "relation_pairs_below_0.50"),
        (natural_train["f1_m"] + 1e-12 >= cheap + .05, "natural_F1m_gain_below_0.05"),
        (natural_train["f1_a"] + 1e-12 >= natural_start["f1_a"] + .05, "natural_F1a_gain_below_0.05"),
        (natural_train["exact_match"] + 1e-12 >= .05, "natural_EM_below_0.05"),
        (natural_train["probability_CE"] <= constants["prior_constant_CE"] * .95 + 1e-12,
         "natural_CE_not_5percent_below_prior")):
        if not passed:
            reasons.append(reason)
    return dict(passed=not reasons, reasons=reasons, retention=retained,
        requirements=requirements, scope="V7_training_and_previously_exposed_internal_qualification",
        fresh_scores_used=False, generalization_established=False)
