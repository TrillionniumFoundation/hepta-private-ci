"""V9 frozen whole-world recombinations, independent truth and final-only gates.

This stdlib module neither encodes text nor reads predictions or official data.
New worlds are disjoint from historical/reserved worlds; atomic joins may recur.
"""
from dataclasses import asdict
from hashlib import sha256
import math
from pathlib import Path

from binding_protocol import (ROLES as HISTORICAL_ROLES, _COLORS, _NEW_NAMES,
    _NEW_OBJECTS, _OWN, _QUESTION, _STORE, _TRAIN_NAMES, _TRAIN_OBJECTS, _digest,
    _new_domain, _old_cases, _source_key, semantic_key, verify_binding_cases,
    verify_binding_protocol)
from retention_data import build_augmentation

ROLES = ("fresh_combinations", "fresh_vocabulary")
SEEDS = (41, 47, 53)
DATA_SEED = 2901


def _historical(historical_parts, augmentation):
    if set(historical_parts) != set(HISTORICAL_ROLES):
        raise ValueError("all V5 roles, including reserved domains, are required")
    verify_binding_protocol(historical_parts)
    augmentation = tuple(augmentation)
    expected, _ = build_augmentation(historical_parts)
    if augmentation != expected:
        raise ValueError("exact frozen V7 augmentation required")
    return (tuple(_old_cases()) + tuple(c for cases in historical_parts.values() for c in cases)
            + augmentation)


def build_grounding_protocol(historical_parts, augmentation, *, seed=DATA_SEED):
    """Return two new 32-group/128-candidate domains before any encoding."""
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("bounded integer grounding data seed required")
    old = _historical(historical_parts, augmentation)
    if any(c.paragraph_id.startswith(f"binding-v5/{role}/{seed}/") for c in old for role in ROLES):
        raise ValueError("new domains must not reuse historical role/seed identifiers")
    tasks, sources = {semantic_key(c) for c in old}, {_source_key(c) for c in old}
    parts = {role: _new_domain(role, seed, tasks, sources) for role in ROLES}
    verify_grounding_protocol(parts, historical_parts, augmentation)
    return parts


def verify_grounding_protocol(parts, historical_parts, augmentation):
    """Reconstruct grammar truth, lexical domains and complete exclusion sets."""
    if set(parts) != set(ROLES):
        raise ValueError("exact two V9 held-out roles required")
    old = _historical(historical_parts, augmentation)
    tasks, sources = {semantic_key(c) for c in old}, {_source_key(c) for c in old}
    identifiers = {c.case_id for c in old}
    reports, seeds = {}, set()
    for role in ROLES:
        cases = tuple(parts[role])
        report = verify_binding_cases(cases)
        current_tasks, current_sources = {semantic_key(c) for c in cases}, {_source_key(c) for c in cases}
        if (report["cases"] != 128 or report["groups"] != 32
                or any(c.source_split != "validation" or c.case_id in identifiers for c in cases)
                or current_tasks & tasks or current_sources & sources):
            raise ValueError("complete fresh worlds, sources and identifiers must be disjoint")
        fields = [c.paragraph_id.split("/") for c in cases]
        if any(len(f) != 5 or f[:2] != ["binding-v5", role] or not f[2].isdigit()
               or not f[3].isdigit() for f in fields) or {int(f[3]) for f in fields} != set(range(32)):
            raise ValueError("registered V9 role/seed/group identifiers required")
        role_seeds = {int(f[2]) for f in fields}
        if len(role_seeds) != 1 or not 0 <= next(iter(role_seeds)) < 2**32:
            raise ValueError("one bounded data seed required")
        seed = next(iter(role_seeds))
        seeds.add(seed)
        names, objects = ((_NEW_NAMES, _NEW_OBJECTS) if role == "fresh_vocabulary"
                          else (_TRAIN_NAMES, _TRAIN_OBJECTS))
        for case in cases:
            if _QUESTION.fullmatch(case.question)[1] not in objects:
                raise ValueError("declared controlled object vocabulary changed")
            for fact in case.facts:
                own, store = _OWN.fullmatch(fact), _STORE.fullmatch(fact)
                if ((own and (own[1] not in objects or own[2] not in names))
                        or (store and (store[1] not in names or store[2] not in _COLORS))):
                    raise ValueError("declared controlled entity vocabulary changed")
        if cases != _new_domain(role, seed, set(tasks), set(sources)):
            raise ValueError("frozen deterministic domain membership/order changed")
        tasks.update(current_tasks)
        sources.update(current_sources)
        identifiers.update(c.case_id for c in cases)
        reports[role] = report
    if len(seeds) != 1:
        raise ValueError("both panels must share one frozen data seed")
    return reports


def grounding_manifest(parts, historical_parts, augmentation, *, source_files_sha256=None,
                       code_files_sha256=None):
    reports = verify_grounding_protocol(parts, historical_parts, augmentation)
    old = _historical(historical_parts, augmentation)
    code = Path(__file__).parent
    code_files_sha256 = code_files_sha256 if code_files_sha256 is not None else {
        name: sha256((code / name).read_bytes()).hexdigest() for name in
        ("grounding_protocol.py", "binding_protocol.py", "token_protocol.py", "retention_data.py")}
    source_files_sha256 = {} if source_files_sha256 is None else source_files_sha256
    for mapping in (source_files_sha256, code_files_sha256):
        if any(not isinstance(k, str) or not k or not isinstance(v, str) or len(v) != 64
               or any(c not in "0123456789abcdef" for c in v) for k, v in mapping.items()):
            raise ValueError("named SHA256 source/code bindings required")
    return dict(schema="hepta.grounding.protocol.v9",
        data_seed=int(parts[ROLES[0]][0].paragraph_id.split("/")[2]), roles={role: dict(reports[role],
        case_ids=[c.case_id for c in cases],
        complete_labeled_cases_sha256=_digest([asdict(c) for c in cases]),
        source_keys_sha256=_digest(sorted({_source_key(c) for c in cases})))
        for role, cases in parts.items()},
        excluded_semantic_tasks_sha256=_digest(sorted({semantic_key(c) for c in old})),
        excluded_source_keys_sha256=_digest(sorted({_source_key(c) for c in old})),
        source_files_sha256=source_files_sha256, code_files_sha256=code_files_sha256,
        fresh_combinations_scope="whole_world_semantic_and_source_disjoint_not_unseen_atomic_joins",
        fresh_vocabulary_scope="untrained_controlled_names_objects_same_reserved_V5_lexicon_new_worlds",
        original_V5_reserved_domains_scored=False, longer_chains=False,
        official_validation_read=False, predictions_read=False,
        labels_and_support_are_training_or_scoring_metadata_not_forward_inputs=True)


def grounding_gate(metrics_by_role):
    """Score one seed only after final model freezing; never select a model."""
    if set(metrics_by_role) != set(ROLES):
        raise ValueError("both complete final-only panels required")
    panels, reasons = {}, []
    for role in ROLES:
        m = metrics_by_role[role]
        if (m.get("cases") != 128 or m.get("groups") != 32 or m.get("paired_candidates") != 64
                or m.get("prediction_rule") != "raw_probability_strictly_greater_than_0.5"
                or m.get("threshold_selected") is not False):
            raise ValueError("complete 128-case fixed-threshold probability metrics required")
        for key, count in (("accuracy", 128), ("both_worlds_correct", 64)):
            value = m.get(key)
            if (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1
                    or abs(value * count - round(value * count)) > 1e-9):
                raise ValueError("finite integer-count candidate and paired metrics required")
        if m["both_worlds_correct"] > m["accuracy"] + 1e-12:
            raise ValueError("paired correctness cannot exceed candidate correctness")
        failures = []
        if m["accuracy"] + 1e-12 < .85:
            failures.append("candidate_accuracy_below_0.85")
        if m["both_worlds_correct"] + 1e-12 < .75:
            failures.append("paired_accuracy_below_0.75")
        panels[role] = dict(passed=not failures, reasons=failures,
            candidate_correct=round(m["accuracy"] * 128), paired_correct=round(m["both_worlds_correct"] * 64))
        reasons.extend(role + ":" + reason for reason in failures)
    return dict(passed=not reasons, reasons=reasons, panels=panels,
        thresholds=dict(candidate=.85, paired=.75, minimum_candidates=109, minimum_pairs=48),
        legacy_joint_gate_is_separate=True, model_or_threshold_selection=False,
        automatic_downstream_authorized=False)


def grounding_campaign_gate(metrics_by_seed):
    """Recompute all three raw-metric gates instead of trusting saved pass flags."""
    if set(metrics_by_seed) != {str(s) for s in SEEDS}:
        raise ValueError("exact seeds 41/47/53 required")
    gates = {seed: grounding_gate(metrics_by_seed[seed]) for seed in map(str, SEEDS)}
    return dict(primary_all_passed=all(g["passed"] for g in gates.values()), gates=gates,
        every_seed_and_both_panels_required=True, selection_authorized=False,
        automatic_downstream_authorized=False)
