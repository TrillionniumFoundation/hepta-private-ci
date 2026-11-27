"""V5 controlled binding protocol, independent grammar checks and fixed gates.

This module reads no official dataset files. Existing V4 train/tune examples are
reused exactly; new domains exclude their semantic content and V4 final content.
Fresh scores may be produced only after the caller freezes every compared model.
Labels and support indices remain training/scoring metadata, never model inputs.
"""

from collections import Counter, defaultdict
from dataclasses import asdict
from hashlib import sha256
import json
import math
import random
import re

from multirc_data import ReaderCase
from token_protocol import build_binding_cases


ROLES = ("reader_train", "internal_tune", "verifier_fit", "fresh_combinations", "fresh_vocabulary")
_TRAIN_NAMES = "Ada Ben Cleo Drew Esme Finn Gina Hugo".split()
_TRAIN_OBJECTS = "coin bead token key button marble shell stamp".split()
_NEW_NAMES = "Alden Briar Cassia Dorian Elian Freya Galen Hazel".split()
_NEW_OBJECTS = "anchor lantern ribbon pebble locket whistle prism thimble".split()
_COLORS = "copper silver golden blue green violet".split()
_OWN = re.compile(r"The (\w+) belongs to ([A-Z]\w*)\.")
_STORE = re.compile(r"([A-Z]\w*) stores all their possessions in the (\w+) box\.")
_QUESTION = re.compile(r"Where is the (\w+) stored\?")
_CANDIDATE = re.compile(r"The (\w+) box\.")


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def semantic_key(case):
    """Bind the complete public task, ignoring sentence ordering and whitespace."""
    return _digest(dict(facts=sorted(" ".join(f.split()) for f in case.facts),
                        question=" ".join(case.question.split()), candidate=" ".join(case.candidate.split())))


def _source_key(case):
    return _digest(sorted(" ".join(f.split()) for f in case.facts))


def _old_cases():
    return tuple(c for split, groups in (("train", 32), ("tune", 16), ("final", 32))
                 for c in build_binding_cases(split, groups=groups, seed=41))


def _new_domain(role, seed, excluded_tasks, excluded_sources):
    rng = random.Random(f"hepta-binding-v5/{role}/{seed}")
    vocabulary = (_NEW_NAMES, _NEW_OBJECTS) if role == "fresh_vocabulary" else (_TRAIN_NAMES, _TRAIN_OBJECTS)
    cases, accepted = [], 0
    for _ in range(10000):
        names, objects = (rng.sample(words, 2) for words in vocabulary)
        colors, order = rng.sample(_COLORS, 2), rng.sample(range(4), 4)
        group = []
        for world in (0, 1):
            owners = names if world == 0 else names[::-1]
            canonical = (f"The {objects[0]} belongs to {owners[0]}.",
                         f"The {objects[1]} belongs to {owners[1]}.",
                         f"{names[0]} stores all their possessions in the {colors[0]} box.",
                         f"{names[1]} stores all their possessions in the {colors[1]} box.")
            facts = tuple(canonical[i] for i in order)
            support = tuple(sorted(order.index(i) + 1 for i in (0, 2 + world)))
            for candidate in (0, 1):
                group.append(ReaderCase(f"binding-v5/{role}/{seed}/{accepted}/world-{world}", "0", str(candidate),
                    f"Where is the {objects[0]} stored?", f"The {colors[candidate]} box.", facts,
                    int(candidate == world), "validation" if role.startswith("fresh_") else "train",
                    sha256("\n".join(facts).encode()).hexdigest(), (1, 2, 3, 4), support,
                    "synthetic-ownership-storage-v1"))
        tasks, sources = {semantic_key(c) for c in group}, {_source_key(c) for c in group}
        if tasks & excluded_tasks or sources & excluded_sources:
            continue
        excluded_tasks.update(tasks)
        excluded_sources.update(sources)
        cases.extend(group)
        accepted += 1
        if accepted == 32:
            return tuple(cases)
    raise ValueError("bounded generation failed to find disjoint binding groups")


def build_binding_protocol(*, seed=41):
    """Return exact old train128/tune64 and three new disjoint 128-case domains."""
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError("bounded integer protocol seed required")
    old = _old_cases()
    tasks, sources = {semantic_key(c) for c in old}, {_source_key(c) for c in old}
    parts = dict(reader_train=build_binding_cases("train", groups=32, seed=41),
                 internal_tune=build_binding_cases("tune", groups=16, seed=41))
    for role in ROLES[2:]:
        parts[role] = _new_domain(role, seed, tasks, sources)
    verify_binding_protocol(parts)
    return parts


def _truth(case):
    ownership, storage, own_indices, store_indices = {}, {}, {}, {}
    if len(case.facts) != 4 or case.sentence_ids != (1, 2, 3, 4):
        raise ValueError("exact four-sentence binding grammar required")
    for index, sentence in enumerate(case.facts, 1):
        own, store = _OWN.fullmatch(sentence), _STORE.fullmatch(sentence)
        if own:
            obj, person = own.groups()
            if obj in ownership:
                raise ValueError("duplicate ownership relation")
            ownership[obj], own_indices[obj] = person, index
        elif store:
            person, color = store.groups()
            if person in storage:
                raise ValueError("duplicate storage relation")
            storage[person], store_indices[person] = color, index
        else:
            raise ValueError("unrecognized binding grammar")
    question, candidate = _QUESTION.fullmatch(case.question), _CANDIDATE.fullmatch(case.candidate)
    if (len(ownership) != 2 or len(storage) != 2 or len(set(ownership.values())) != 2
            or set(ownership.values()) != set(storage) or len(set(storage.values())) != 2
            or question is None or candidate is None or question[1] not in ownership
            or candidate[1] not in storage.values()):
        raise ValueError("complete bijective ownership/storage task required")
    obj, color = question[1], candidate[1]
    person = ownership[obj]
    support = tuple(sorted((own_indices[obj], store_indices[person])))
    return int(storage[person] == color), support


def verify_binding_cases(cases):
    """Reconstruct truth from grammar, without trusting generator labels/support."""
    cases = tuple(cases)
    if not cases or len(cases) % 4:
        raise ValueError("complete four-case binding groups required")
    groups, identifiers, semantic = defaultdict(list), set(), set()
    for case in cases:
        truth, support = _truth(case)
        if case.label != truth or case.evidence_sentence_indices != support:
            raise ValueError("label or evidence support disagrees with independent grammar")
        if (case.source_hash != sha256("\n".join(case.facts).encode()).hexdigest()
                or case.segmentation != "synthetic-ownership-storage-v1"):
            raise ValueError("binding source bytes or grammar identity mismatch")
        if case.case_id in identifiers or semantic_key(case) in semantic:
            raise ValueError("duplicate binding candidate or semantic task")
        identifiers.add(case.case_id)
        semantic.add(semantic_key(case))
        prefix, separator, world = case.paragraph_id.rpartition("/world-")
        if not separator or world not in ("0", "1") or not prefix.startswith(("binding-v4/", "binding-v5/")):
            raise ValueError("registered paired-world binding identifier required")
        groups[prefix].append((world, case))
    for rows in groups.values():
        if (len(rows) != 4 or Counter(world for world, _ in rows) != {"0": 2, "1": 2}
                or len({c.question for _, c in rows}) != 1 or len({c.question_id for _, c in rows}) != 1):
            raise ValueError("complete double-world double-candidate group required")
        by_world = {world: [c for w, c in rows if w == world] for world in ("0", "1")}
        first, second = by_world.values()
        if any(len({c.facts for c in world_cases}) != 1 or {c.label for c in world_cases} != {0, 1}
               or {c.answer_id for c in world_cases} != {"0", "1"} for world_cases in by_world.values()):
            raise ValueError("two opposite-label candidates in each identical world required")
        if ({c.candidate for c in first} != {c.candidate for c in second}
                or Counter(" ".join(first[0].facts).split()) != Counter(" ".join(second[0].facts).split())):
            raise ValueError("paired worlds must preserve query/candidates and word counts")
        storage = [{f for f in world_cases[0].facts if _STORE.fullmatch(f)} for world_cases in (first, second)]
        ownership = [{_OWN.fullmatch(f)[1]: _OWN.fullmatch(f)[2] for f in world_cases[0].facts
                      if _OWN.fullmatch(f)} for world_cases in (first, second)]
        if (storage[0] != storage[1] or ownership[0].keys() != ownership[1].keys()
                or any(person == ownership[1][obj] for obj, person in ownership[0].items())):
            raise ValueError("worlds must swap ownership while preserving storage facts")
        if any(a.label == b.label for a in first for b in second if a.candidate == b.candidate):
            raise ValueError("evidence swap must reverse each candidate's truth")
    return dict(cases=len(cases), groups=len(groups), paired_candidates=2 * len(groups),
                semantic_tasks_sha256=_digest(sorted(semantic)), independent_grammar_verified=True)


def verify_binding_protocol(parts):
    """Reject old-content reuse, lexical drift and cross-domain semantic overlap."""
    if set(parts) != set(ROLES):
        raise ValueError("exact registered V5 binding roles required")
    for role, split, size in (("reader_train", "train", 32), ("internal_tune", "tune", 16)):
        if tuple(parts[role]) != build_binding_cases(split, groups=size, seed=41):
            raise ValueError("V4 train/tune must be reused byte-for-byte")
    old = _old_cases()
    tasks, sources = {semantic_key(c) for c in old}, {_source_key(c) for c in old}
    reports = {role: verify_binding_cases(cases) for role, cases in parts.items()}
    seeds = set()
    for role in ROLES[2:]:
        cases = parts[role]
        current_tasks, current_sources = {semantic_key(c) for c in cases}, {_source_key(c) for c in cases}
        if len(cases) != 128 or current_tasks & tasks or current_sources & sources:
            raise ValueError("new domains require 32 groups with disjoint semantic tasks and sources")
        expected_split = "validation" if role.startswith("fresh_") else "train"
        names, objects = (_NEW_NAMES, _NEW_OBJECTS) if role == "fresh_vocabulary" else (_TRAIN_NAMES, _TRAIN_OBJECTS)
        identifiers = [c.paragraph_id.split("/") for c in cases]
        if (any(len(fields) != 5 or fields[:2] != ["binding-v5", role] or not fields[2].isdigit()
                or not fields[3].isdigit() for fields in identifiers)
                or {int(fields[3]) for fields in identifiers} != set(range(32))):
            raise ValueError("registered role/seed/group identifiers required")
        seeds.update(int(fields[2]) for fields in identifiers)
        if any(c.source_split != expected_split or _QUESTION.fullmatch(c.question)[1] not in objects
               or any((_OWN.fullmatch(f) and (_OWN.fullmatch(f)[1] not in objects or _OWN.fullmatch(f)[2] not in names))
                      or (_STORE.fullmatch(f) and (_STORE.fullmatch(f)[1] not in names
                                                  or _STORE.fullmatch(f)[2] not in _COLORS)) for f in c.facts) for c in cases):
            raise ValueError("declared source role or lexical domain violated")
        tasks.update(current_tasks)
        sources.update(current_sources)
    if len(seeds) != 1 or not 0 <= next(iter(seeds)) <= 2**32 - 1:
        raise ValueError("one bounded protocol seed required across new domains")
    return reports


def score_binding_probabilities(cases, probabilities):
    """Fixed raw p>0.5; observations are grouped, never independent candidates."""
    cases, probabilities = tuple(cases), tuple(probabilities)
    report = verify_binding_cases(cases)
    if len(probabilities) != len(cases) or any(type(p) not in (int, float) or not math.isfinite(p)
                                              or not 0 <= p <= 1 for p in probabilities):
        raise ValueError("one finite binary probability per binding candidate required")
    predictions, pairs, groups = [int(p > .5) for p in probabilities], defaultdict(list), defaultdict(list)
    loss, correct = 0., 0
    for case, p, prediction in zip(cases, probabilities, predictions):
        prefix = case.paragraph_id.rsplit("/world-", 1)[0]
        pairs[(prefix, case.question, case.candidate)].append((case.label, p, prediction))
        groups[prefix].append(prediction == case.label)
        correct += prediction == case.label
        loss -= math.log(max(1e-12, p if case.label else 1 - p))
    both, switches, signed, absolute = 0, 0, [], []
    for rows in pairs.values():
        positive, negative = sorted(rows, reverse=True)
        both += all(label == prediction for label, _, prediction in rows)
        switches += positive[2] != negative[2]
        signed.append(positive[1] - negative[1])
        absolute.append(abs(positive[1] - negative[1]))
    return dict(report, prediction_rule="raw_probability_strictly_greater_than_0.5", accuracy=correct / len(cases),
                probability_CE=loss / len(cases), both_worlds_correct=both / len(pairs),
                evidence_switch_rate=switches / len(pairs), all_four_correct=sum(map(all, groups.values())) / len(groups),
                mean_truth_signed_world_probability_gap=sum(signed) / len(signed),
                mean_absolute_world_probability_gap=sum(absolute) / len(absolute),
                positive_truth_gap_rate=sum(gap > 0 for gap in signed) / len(signed),
                independent_unit="paired_world_group", threshold_selected=False)


def _validate_metrics(metrics):
    if (metrics.get("cases") != 128 or metrics.get("groups") != 32 or metrics.get("paired_candidates") != 64
            or metrics.get("prediction_rule") != "raw_probability_strictly_greater_than_0.5"):
        raise ValueError("complete 128-case raw-probability training metrics required")
    for key in ("accuracy", "both_worlds_correct", "all_four_correct", "probability_CE"):
        value = metrics.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or key != "probability_CE" and value > 1:
            raise ValueError("finite complete training metrics required")


def warmup_gate(metrics):
    """Training-only engineering gate; never evidence of unseen generalization."""
    _validate_metrics(metrics)
    reasons = [key for key in ("accuracy", "both_worlds_correct", "all_four_correct") if metrics[key] != 1.]
    if metrics["probability_CE"] > .10:
        reasons.append("probability_CE_above_0.10")
    return dict(passed=not reasons, reasons=reasons, scope="complete_binding_train_only", fresh_selection=False)


def retention_gate(metrics, baseline):
    """Retain >=95% candidate/paired accuracy and lose at most five points."""
    _validate_metrics(metrics)
    _validate_metrics(baseline)
    if not warmup_gate(baseline)["passed"]:
        raise ValueError("retention reference must pass the full warmup gate")
    reasons = []
    for key in ("accuracy", "both_worlds_correct"):
        if metrics[key] + 1e-12 < .95:
            reasons.append(key + "_below_0.95")
        if baseline[key] - metrics[key] > .05 + 1e-12:
            reasons.append(key + "_drop_above_0.05")
    return dict(passed=not reasons, reasons=reasons, scope="complete_binding_train_retention_only",
                natural_internal_tune_required_separately=True, fresh_selection=False)


def binding_manifest(parts, *, dataset_files_sha256, source_files_sha256, code_files_sha256):
    """Bind caller-supplied byte digests; no dataset loading or final scoring."""
    reports = verify_binding_protocol(parts)
    digests = dict(dataset_files_sha256=dataset_files_sha256, source_files_sha256=source_files_sha256,
                   code_files_sha256=code_files_sha256)
    for inventory in digests.values():
        if not inventory or any(not isinstance(name, str) or not name or not isinstance(value, str)
                                or re.fullmatch(r"[0-9a-f]{64}", value) is None for name, value in inventory.items()):
            raise ValueError("nonempty named source-byte SHA256 inventories required")
    return dict(schema="hepta.binding-retention-protocol.v5", **digests,
        roles={role: dict(reports[role], usage="reserved_unused" if role == "verifier_fit" else "planned",
                         encoding_authorized=role != "verifier_fit", scoring_authorized=role != "verifier_fit",
                         training_authorized=role == "reader_train", case_ids=[c.case_id for c in cases],
                         source_hashes=sorted({c.source_hash for c in cases}),
                         complete_labeled_cases_sha256=_digest([asdict(c) for c in cases])) for role, cases in parts.items()},
        old_v4_exclusions_sha256=_digest(sorted(semantic_key(c) for c in _old_cases())),
        protocol_seed=int(parts["fresh_combinations"][0].paragraph_id.split("/")[2]),
        reused_v4_train_seed=41, reused_v4_train_cases=128, old_internal_tune_cases=64,
        fresh_roles=["fresh_combinations", "fresh_vocabulary"],
        fresh_scoring_requires_all_models_frozen=True, natural_tune_report_required=True,
        verifier_fit_scope="reserved_unused_not_encoded_scored_or_trained_in_v5",
        fresh_metrics_select_models=False, annotations_enter_model=False,
        official_validation_loaded=False, independent_unit="paired_world_group",
        vocabulary_novelty_scope="generator_people_and_objects_only_not_encoder_pretraining")
