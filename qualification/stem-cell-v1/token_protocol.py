"""Label-blind V4 source selection and a separate, exact evidence-binding domain.

The pinned SuperGLUE-v2 MultiRC archive has no sentence-use annotations. Natural
evidence deletion is therefore diagnostic: it never creates a negative target.
The controlled domain below has an explicit generative truth rule, paired worlds
with identical question/candidate text and word counts, and separate split names.
"""

from collections import Counter, defaultdict
from hashlib import sha256
import json
import random

from multirc_data import ReaderCase, partition_cases, score_multirc


PARAGRAPH_CAPS = dict(train=64, tune=16, verifier_fit=8, critic_fit=8,
                      critic_calibration=8, final=16)
_NAMES = {
    "train": "Ada Ben Cleo Drew Esme Finn Gina Hugo".split(),
    "tune": "Iris Jori Kira Leon Mona Noel Orla Pia".split(),
    "final": "Quinn Ravi Sora Theo Uma Vera Wynn Zane".split(),
}
_OBJECTS = {
    "train": "coin bead token key button marble shell stamp".split(),
    "tune": "parcel letter book scarf cup ring ball card".split(),
    "final": "badge medal pencil spoon comb brush clip watch".split(),
}
_COLORS = "copper silver golden blue green violet".split()


def _select(cases, count):
    if type(count) is not int or count < 1:
        raise ValueError("positive paragraph count required")
    hashes = sorted({case.source_hash for case in cases})[:count]
    if len(hashes) != count:
        raise ValueError("insufficient source paragraphs")
    selected = set(hashes)
    return tuple(case for case in cases if case.source_hash in selected)


def make_partitions(train_cases, validation_cases, previous_design, *, caps=None):
    """Keep complete paragraphs and reserve all previously scored final sources.

    `final` is a new official-validation subset; `regression` is precisely V3's
    scored subset. Neither may be used for training or choosing hyperparameters.
    Caps apply within the existing source-hash partition with fixed seed 41.
    """
    train_cases, validation_cases = tuple(train_cases), tuple(validation_cases)
    if (any(case.source_split != "train" for case in train_cases)
            or any(case.source_split != "validation" for case in validation_cases)):
        raise ValueError("explicit official train/validation inputs required")
    caps = dict(PARAGRAPH_CAPS if caps is None else caps)
    if set(caps) != set(PARAGRAPH_CAPS):
        raise ValueError("exact registered paragraph-cap keys required")
    previous = tuple(previous_design["partitions"]["final"])
    if not previous or len(set(previous)) != len(previous):
        raise ValueError("unique previous final source hashes required")
    available = {case.source_hash for case in validation_cases}
    if not set(previous).issubset(available):
        raise ValueError("previous final sources absent from official validation")
    parts = partition_cases(train_cases + validation_cases, seed=41)
    result = {name: _select(cases, caps[name]) for name, cases in parts.items()
              if name != "final"}
    result["final"] = _select(tuple(case for case in validation_cases
                                     if case.source_hash not in set(previous)), caps["final"])
    result["regression"] = tuple(case for case in validation_cases if case.source_hash in set(previous))
    if "final_case_ids" in previous_design:
        old_ids = previous_design["final_case_ids"]
        if (len(old_ids) != len(set(old_ids))
                or set(old_ids) != {case.case_id for case in result["regression"]}):
            raise ValueError("previous final candidate membership is incomplete")
    return result


def protocol_manifest(parts, *, dataset_files_sha256, previous_design_sha256):
    """Public provenance only; hashes refer to exact source-file bytes."""
    if set(parts) != set(PARAGRAPH_CAPS) | {"regression"}:
        raise ValueError("all registered source partitions required")
    partitions = {name: sorted({case.source_hash for case in cases}) for name, cases in parts.items()}
    seen, identifiers = set(), set()
    for name, cases in parts.items():
        if seen.intersection(partitions[name]):
            raise ValueError("source content overlaps partitions")
        seen.update(partitions[name])
        if any(case.case_id in identifiers for case in cases):
            raise ValueError("candidate identifier overlaps partitions")
        identifiers.update(case.case_id for case in cases)
    questions = defaultdict(list)
    for case in parts["final"]:
        questions[json.dumps(case.question_key, separators=(",", ":"))].append(case.case_id)
    return dict(schema="hepta.multirc.token-protocol.v1", source_seed=41,
                partitions=partitions,
                final_case_ids=[case.case_id for case in parts["final"]],
                final_question_candidate_ids=dict(questions),
                regression_case_ids=[case.case_id for case in parts["regression"]],
                previous_final_case_ids=[case.case_id for case in parts["regression"]],
                previous_final_source_hashes=partitions["regression"],
                previous_design_sha256=previous_design_sha256,
                dataset_files_sha256=dict(dataset_files_sha256),
                natural_evidence_annotations={name: sum(bool(case.evidence_sentence_indices)
                                                      for case in cases) for name, cases in parts.items()},
                natural_deletion_labels="unchanged_diagnostic_only",
                final_subset_label_independent=True,
                regression_scope="previously_scored_v3_sources_not_fresh_holdout")


def build_binding_cases(split="train", *, groups=32, seed=41):
    """Generate ownership→storage proofs with evidence-only label reversals.

    A world contains exactly two objects, each owned by one distinct person.
    Each person stores all their possessions in one distinct box. Swapping the
    two ownership assignments reverses both candidate labels without changing
    any word's count. Split-specific people and objects are never shared.
    Evidence indices are 1-based source sentence IDs and never public features.
    """
    if split not in _NAMES or type(groups) is not int or not 1 <= groups <= 256 or type(seed) is not int:
        raise ValueError("registered split, bounded groups and integer seed required")
    rng = random.Random(f"hepta-binding-v4/{split}/{seed}")
    cases, signatures = [], set()
    for index in range(groups):
        while True:
            names = rng.sample(_NAMES[split], 2)
            objects = rng.sample(_OBJECTS[split], 2)
            colors = rng.sample(_COLORS, 2)
            signature = tuple(names + objects + colors)
            if signature not in signatures:
                signatures.add(signature)
                break
        order = rng.sample(range(4), 4)
        question = f"Where is the {objects[0]} stored?"
        for world in (0, 1):
            owners = names if world == 0 else names[::-1]
            facts = [f"The {objects[0]} belongs to {owners[0]}.",
                     f"The {objects[1]} belongs to {owners[1]}.",
                     f"{names[0]} stores all their possessions in the {colors[0]} box.",
                     f"{names[1]} stores all their possessions in the {colors[1]} box."]
            evidence = (0, 2 + world)
            facts = tuple(facts[i] for i in order)
            support = tuple(sorted(order.index(i) + 1 for i in evidence))
            source_hash = sha256("\n".join(facts).encode()).hexdigest()
            for candidate in (0, 1):
                cases.append(ReaderCase(
                    f"binding-v4/{split}/{seed}/{index}/world-{world}", "0", str(candidate),
                    question, f"The {colors[candidate]} box.", facts, int(candidate == world),
                    "validation" if split == "final" else "train", source_hash,
                    (1, 2, 3, 4), support, "synthetic-ownership-storage-v1"))
    return tuple(cases)


def score_binding(cases, predictions):
    """Require both paired worlds correct; changing an answer alone is no gain."""
    cases, predictions = tuple(cases), tuple(predictions)
    metrics = score_multirc(cases, predictions)
    pairs = defaultdict(list)
    for case, prediction in zip(cases, predictions):
        if (case.segmentation != "synthetic-ownership-storage-v1"
                or not case.paragraph_id.startswith("binding-v4/")):
            raise ValueError("controlled binding domain required")
        prefix, world = case.paragraph_id.rsplit("/world-", 1)
        if world not in ("0", "1"):
            raise ValueError("two registered worlds required")
        pairs[(prefix, case.question, case.candidate)].append((world, case, prediction))
    switched = correct = 0
    for rows in pairs.values():
        if (len(rows) != 2 or {row[0] for row in rows} != {"0", "1"}
                or {row[1].label for row in rows} != {0, 1}
                or Counter(" ".join(rows[0][1].facts).split()) != Counter(" ".join(rows[1][1].facts).split())):
            raise ValueError("complete opposite-label, equal-word-count world pairs required")
        switched += rows[0][2] != rows[1][2]
        correct += all(case.label == prediction for _, case, prediction in rows)
    metrics.update(domain="synthetic-ownership-storage-v1", paired_candidates=len(pairs),
                   evidence_switch_rate=switched / len(pairs),
                   both_worlds_correct=correct / len(pairs),
                   natural_multirc_generalization=False)
    return metrics
