"""Reproducible synthetic mechanics probe, NOT a memory capability benchmark.

All arms receive identical observable type and cue fields. Single parent rank 10
and two children rank 5 have exactly matched total weight counts; update counts,
parameter-touch estimates, source provenance and limitations are all reported.
This fixture cannot replace independently sourced tasks or strong RAG baselines.
"""

from collections import defaultdict
import json
import random

from associative_cell import (
    AssociativeCell, Experience, ExperimentalBank, KINDS,
    ReadQuery, TrainingCut, propose_split, sha256,
)

DIM = 10
RANK = 5
SEED = 7341


def fixture():
    random_state = random.Random(SEED)
    train, future = [], []
    for cohort, count in (("train", 64), ("future", 32)):
        for kind in KINDS:
            for index in range(count):
                signal = tuple(random_state.uniform(-1.0, 1.0) for _ in range(DIM - 2))
                cue = ((1.0, 0.0) if kind == "semantic" else (0.0, 1.0)) + signal
                # Contrasting, continuous transformations of SAME observable cues.
                # Fixed controlled mechanics are not evidence of real-world transfer.
                if kind == "semantic":
                    payload = (signal[0], signal[1], signal[2], signal[3],
                               signal[4], signal[5], signal[6], signal[7])
                else:
                    payload = (-signal[1], signal[0], -signal[3], signal[2],
                               -signal[5], signal[4], -signal[7], signal[6])
                value = (0.0, 0.0) + payload
                row = Experience(
                    identity=f"{cohort}:{kind}:{index:04d}",
                    scope="lab:scope", family=f"{cohort}:family:{index:04d}",
                    root=f"{cohort}:root:{kind}:{index:04d}", kind=kind,
                    encoder_identity="fixture:frozen-vector-v1",
                    observed_at=20 + index if cohort == "train" else 200 + index,
                    cue=cue, value=value,
                )
                (train if cohort == "train" else future).append(row)
    cut = TrainingCut(
        scope="lab:scope", encoder_identity="fixture:frozen-vector-v1",
        through=100,
        allowed_roots=frozenset(r.root for r in train),
        allowed_families=frozenset(r.family for r in train),
        forbidden_roots=frozenset(r.root for r in future),
        forbidden_families=frozenset(r.family for r in future),
        admission_digest=sha256(b"synthetic-fixture-admission-not-an-authority"),
    )
    return tuple(train), tuple(future), cut


def mean_square(predicted, target):
    return sum((p - v) ** 2 for p, v in zip(predicted, target, strict=True)) / len(target)


def score(model, future, *, revoked=frozenset(), ablation="correct"):
    sums = defaultdict(list)
    for row in future:
        query = ReadQuery(row.scope, row.kind, row.encoder_identity, 300, row.cue)
        if isinstance(model, ExperimentalBank):
            prediction = model.read(query, revoked=revoked, ablation=ablation)
        else:
            prediction = model.read(query, revoked=revoked)
        # Gold read ONLY here, after inference. No raw example is sent to read().
        sums[row.kind].append(mean_square(prediction, row.value))
    sums["all"] = [v for values in sums.values() for v in values]
    return {kind: round(sum(values) / len(values), 8) for kind, values in sorted(sums.items())}


def run_trial(*, steps=384):
    if type(steps) is not int or not 1 <= steps <= 1024:
        raise ValueError("bounded preregistered trial steps required")
    training, future, cut = fixture()
    parent = AssociativeCell(DIM, 2 * RANK, cut.encoder_identity, cut.scope, seed=SEED)
    children = propose_split(parent)
    if parent.parameter_count() != sum(c.parameter_count() for c in children):
        raise AssertionError("not a matched parameter comparison")
    common, common_receipt = parent.propose_update(
        training, cut, revoked=set(), steps=2 * steps, lr=0.12,
    )
    compute_matched, compute_receipt = parent.propose_update(
        training, cut, revoked=set(), steps=steps, lr=0.12,
    )
    fitted = []
    child_receipts = []
    for child in children:
        rows = tuple(x for x in training if x.kind == child.kind)
        trained, receipt = child.propose_update(
            rows, cut, revoked=set(), steps=steps, lr=0.12,
        )
        fitted.append(trained)
        child_receipts.append(receipt)
    bank = ExperimentalBank(tuple(fitted))
    report = dict(
        schema="hepta.associative-cell-controlled-fixture.v1",
        fixture_seed=SEED,
        synthetic_mechanics_only=True,
        production_qualified=False,
        statistical_superiority=False,
        independent_semantic_adjudication=False,
        external_reader_executed=False,
        strong_rag_comparison_executed=False,
        shared_encoder="fixture:frozen-vector-v1 (no pretrained model loaded)",
        training_examples=len(training),
        unseen_future_example_ids=len(future),
        disjoint_source_roots=not bool({r.root for r in training} & {r.root for r in future}),
        disjoint_families=not bool({r.family for r in training} & {r.family for r in future}),
        same_observable_cue_and_kind=True,
        trainable_parameters=dict(
            shared=common.parameter_count(),
            typed=sum(c.parameter_count() for c in fitted),
            equal_touch_shared=compute_matched.parameter_count(),
        ),
        sgd_sample_updates=dict(
            shared=common_receipt["steps"],
            typed=sum(r["steps"] for r in child_receipts),
            equal_touch_shared=compute_receipt["steps"],
        ),
        trainable_parameter_touches_estimate=dict(
            shared=common.parameter_count() * common_receipt["steps"],
            typed=sum(c.parameter_count() * r["steps"]
                      for c, r in zip(fitted, child_receipts, strict=True)),
            equal_touch_shared=compute_matched.parameter_count() * compute_receipt["steps"],
        ),
        no_momentum_persistent_optimizer_bytes=0,
        evaluation="held-out vector mean-square-error; lower is better",
        arms=dict(
            frozen=score(parent, future),
            same_capacity_shared=score(common, future),
            equal_touch_shared=score(compute_matched, future),
            typed_split=score(bank, future),
            swapped_type_route=score(bank, future, ablation="swapped"),
        ),
        limitations=[
            "Generated vectors are not natural-language memory or source-grounded tasks",
            "Shared baseline sees the same explicit kind as typed route",
            "Equal total parameter budget; separate matched-update and matched-touch controls",
            "No externally verified source, reader, citation, strong RAG or real longitudinal data",
            "A router ablation is not proof of learned graph topology",
            "No evidence of independent samples or production qualification",
        ],
    )
    return report


if __name__ == "__main__":
    print(json.dumps(run_trial(), indent=2, sort_keys=True, allow_nan=False))
