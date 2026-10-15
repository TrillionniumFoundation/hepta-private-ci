"""New-question, fixed-support development cohort; no new independent-source claim.

Reuses existing Cell fitting and prediction. Freeze every family's states before
encoding ANY evaluation question. Natural support-before-query chronology is NOT
implied by this experimental phase order. Reader outcomes, not source hits, are
needed to assess the end-to-end candidate. No default/production policy changes.
"""

from dataclasses import dataclass
import hashlib
import math
import time

import torch
from safetensors.torch import load_file, save_file

from selector_head import TrainingCut
from stem_cell import route_text
from native import digest
from system2_fewshot_cells import METHODS, delta_fit, journal, neighbor_bank, predict
from system2_linear_solver import write
from system2_margin_transfer import fit_margin

ARMS = METHODS + ("no_evidence", "ranked3")
PROTOCOL = dict(
    schema="hepta.system2.fixed-support-new-questions.v1",
    support_count=2,
    queries_per_family=8,
    arms=ARMS,
    primary_candidate="differentiated",
    primary_controls=["frozen", "shared", "local_only", "neighbor", "ranked3"],
    ordering="sha256(new-question-cohort-v1, question_id); labels excluded",
    selected_from="original TRAIN families only; all old planned question IDs excluded",
    source_overlap=True,
    independent_confirmation=False,
    natural_chronology_verified=False,
    supports_replaced_on_failure=False,
    snapshot_updates_during_evaluation=False,
    reader_adequacy_established=False,
    calibrated_ndu_utility=False,
    production_accepted=False,
)


def plan_cohort(questions, old_plan):
    """Metadata and question text only; no target/label parameter."""
    lookup = {q.identity: q for q in questions}
    if not lookup or len(lookup) != len(questions):
        raise ValueError("unique nonempty native question census required")
    old_ids = {q for ids in old_plan["question_ids"].values() for q in ids}
    families = sorted({lookup[q].family for q in old_plan["question_ids"]["train"]})
    if not 1 <= len(families) <= 16:
        raise ValueError("bounded original train families required")
    normalized = lambda text: " ".join(text.casefold().split())
    old_text = {normalized(lookup[q].content) for q in old_ids if q in lookup}
    groups, used_text = [], set(old_text)
    for family in families:
        candidates = sorted(
            (
                q
                for q in questions
                if q.family == family
                and q.identity not in old_ids
                and route_text(q.content) == "general"
            ),
            key=lambda q: (digest(("new-question-cohort-v1", q.identity)), q.identity),
        )
        chosen = []
        for q in candidates:
            text = normalized(q.content)
            if text not in used_text:
                chosen.append(q)
                used_text.add(text)
            if len(chosen) == 10:
                break
        if len(chosen) != 10:
            raise ValueError(
                "insufficient disjoint questions; do not shrink or replace family"
            )
        groups.append(
            dict(
                family=family,
                support_ids=[q.identity for q in chosen[:2]],
                query_ids=[q.identity for q in chosen[2:]],
                question_bindings={
                    q.identity: digest((q.content, q.observed_at, q.scope))
                    for q in chosen
                },
                observed_times={q.identity: q.observed_at for q in chosen},
            )
        )
    return PROTOCOL | dict(
        groups=groups,
        excluded_question_ids=sorted(old_ids),
        planned_supports=2 * len(groups),
        planned_queries=8 * len(groups),
        planned_answers=8 * len(groups) * len(ARMS),
        prior_plan_digest=digest(old_plan),
    )


@dataclass(frozen=True)
class Ports:
    """Research trial ports; native adapters own source admission and Reader calls."""

    support: object  # (group) -> (admitted rows, cut, disposition)
    encode: object  # (question_id) -> immutable Features
    answer: object  # (question_id, indices) -> original raw answer, frozen receipt
    score: object  # called ONLY after every attempted answer has been sealed
    select: object = None  # Explicit matched-budget mode; absent on the original path.


def state_seal(states):
    return digest(
        {
            family: {
                method: {
                    k: (v.tolist() if isinstance(v, torch.Tensor) else v)
                    for k, v in state.items()
                }
                for method, state in methods.items()
            }
            for family, methods in states.items()
        }
    )


def build_states(group, prior_rows, original, ports, output):
    """One shared prior and one fixed local support set per family, not per query."""
    family = group["family"]
    train = tuple(r for r in prior_rows if r.features.family != family)
    roots = frozenset(root for r in train for root in r.features.roots)
    if not train or family in roots:
        raise ValueError("shared prior must exclude target source family")
    cut = TrainingCut(
        frozenset(r.features.question_id for r in train),
        frozenset(r.features.family for r in train),
        roots,
        original.forbidden_roots | frozenset({family}),
        digest((original.admission_digest, family)),
    )
    zero = torch.zeros(prior_rows[0].features.paired.shape[1])
    identity = prior_rows[0].features.encoder_identity
    shared, shared_error = None, None
    try:
        head, receipt = fit_margin(train, cut, "squared_hinge")
        shared = head.readout.weight.detach().flatten().clone()
        journal(
            output / "fits.jsonl",
            dict(family=family, kind="shared", status="succeeded", receipt=receipt),
        )
    except Exception as exc:
        shared_error = str(exc)[:512]
    support, local, disposition, support_error = (), None, None, None
    try:
        support, local, disposition = ports.support(group)
        if (
            local.question_ids != frozenset(group["support_ids"])
            or local.question_ids.intersection(group["query_ids"])
            or local.families != frozenset({family})
            or not original.forbidden_roots <= local.forbidden_roots
            or local.allowed_roots.intersection(local.forbidden_roots)
            or any(r.features.encoder_identity != identity for r in support)
        ):
            raise ValueError("fixed local support admission mismatch")
    except Exception as exc:
        support_error = str(exc)[:512]
    states = {}
    for method in METHODS:
        stamp = time.perf_counter()
        try:
            needs_shared = method in ("shared", "differentiated", "erased_update")
            needs_support = method in (
                "local_only",
                "differentiated",
                "erased_update",
                "neighbor",
            )
            if (needs_shared and shared is None) or (needs_support and support_error):
                raise ValueError(
                    shared_error if needs_shared and shared is None else support_error
                )
            prior = shared.clone() if needs_shared else zero.clone()
            delta, bank = zero.clone(), None
            fitted_roots = set(roots) if needs_shared else set()
            receipt = dict(status="no_adaptation")
            if needs_support:
                fitted_roots.update(local.allowed_roots)
                if not support:
                    receipt = dict(
                        status="no_admitted_support", disposition=disposition
                    )
                    bank = (
                        {k: torch.empty(0, len(zero)) for k in ("positive", "negative")}
                        if method == "neighbor"
                        else None
                    )
                elif method == "neighbor":
                    bank = neighbor_bank(support, local, len(zero))
                    receipt = dict(
                        status="memory",
                        vector_bytes=sum(
                            t.numel() * t.element_size() for t in bank.values()
                        ),
                    )
                else:
                    delta, receipt = delta_fit(
                        support, local, prior, erased=method == "erased_update"
                    )
            path = output / (digest((family, method)) + ".safetensors")
            tensors = dict(prior=prior, delta=delta, **({} if bank is None else bank))
            save_file(tensors, str(path))
            saved = load_file(str(path))
            if set(saved) != set(tensors) or any(
                not torch.equal(saved[k], v) for k, v in tensors.items()
            ):
                raise ValueError("frozen snapshot reload mismatch")
            states[method] = dict(
                status="succeeded",
                identity=identity,
                roots=sorted(fitted_roots),
                **saved,
                neighbor=bank is not None,
                state_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            journal(
                output / "fits.jsonl",
                dict(
                    family=family,
                    method=method,
                    receipt=receipt,
                    support_ids=group["support_ids"],
                    disposition=disposition,
                    state_file=path.name,
                    state_sha256=states[method]["state_sha256"],
                    seconds=time.perf_counter() - stamp,
                ),
            )
        except Exception as exc:
            states[method] = dict(status="failed", error=str(exc)[:512])
            journal(
                output / "fits.jsonl",
                dict(
                    family=family,
                    method=method,
                    status="failed",
                    error=str(exc)[:512],
                    seconds=time.perf_counter() - stamp,
                ),
            )
    return states


def summarize_answers(records, plan):
    expected = {(q, a) for g in plan["groups"] for q in g["query_ids"] for a in ARMS}
    keys = [(r["query_id"], r["arm"]) for r in records]
    if len(keys) != len(set(keys)) or set(keys) != expected:
        raise ValueError("missing/duplicate/extra attempted answer")
    by_arm, comparisons = {}, {}
    for arm in ARMS:
        group = [r for r in records if r["arm"] == arm]
        values = [r.get("diagnostic_f1") for r in group]
        if any(
            v is not None
            and (type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1)
            for v in values
        ):
            raise ValueError("invalid score")
        known = [v for v in values if v is not None]
        by_arm[arm] = dict(
            planned=len(group),
            failed=sum(r["status"] != "succeeded" for r in group),
            scored=len(known),
            conditional_f1=sum(known) / len(known) if known else None,
            all_planned_f1_bounds=[
                sum(known) / len(group),
                (sum(known) + len(group) - len(known)) / len(group),
            ],
            reader_calls=sum(r["reader_attempted"] for r in group),
            elapsed_seconds=sum(r["seconds"] for r in group),
        )
    candidate = {r["query_id"]: r for r in records if r["arm"] == "differentiated"}
    for arm in PROTOCOL["primary_controls"]:
        base = {r["query_id"]: r for r in records if r["arm"] == arm}
        deltas = [
            (candidate[q].get("diagnostic_f1"), base[q].get("diagnostic_f1"))
            for q in candidate
        ]
        observed = [c - b for c, b in deltas if c is not None and b is not None]
        missing = len(deltas) - len(observed)
        comparisons[arm] = dict(
            pairs=len(deltas),
            missing=missing,
            wins=sum(d > 0 for d in observed),
            losses=sum(d < 0 for d in observed),
            delta_bounds=[
                (sum(observed) - missing) / len(deltas),
                (sum(observed) + missing) / len(deltas),
            ],
        )
    gain = all(
        c["missing"] == 0 and c["wins"] > 0 and c["losses"] == 0
        for c in comparisons.values()
    )
    return dict(
        by_arm=by_arm,
        comparisons=comparisons,
        recorded=len(records),
        failed=sum(r["status"] != "succeeded" for r in records),
        unique_queries=len(candidate),
        source_families=len(plan["groups"]),
        independent_confirmation=False,
        candidate_disposition="independent_adjudication_and_retention_required"
        if gain
        else "stop_no_controlled_end_to_end_gain",
        reader_adequacy_established=False,
        production_accepted=False,
        reasoning_superiority=False,
    )


def execute(plan, prior_rows, original, ports, output):
    if ports.select is not None:
        from system2_matched_evidence import POLICY, verify_receipt

        if (
            not callable(ports.select)
            or plan.get("evidence_selection_policy") != POLICY
        ):
            raise ValueError("unregistered matched evidence selection")
    elif plan.get("evidence_selection_policy") is not None:
        raise ValueError("matched evidence plan has no selection implementation")
    output.mkdir(exist_ok=False)
    write(output / "plan.json", plan)
    states = {
        g["family"]: build_states(g, prior_rows, original, ports, output)
        for g in plan["groups"]
    }
    seal = state_seal(states)
    write(
        output / "snapshot-freeze.json",
        dict(
            sha256=seal,
            eval_encoding_started=False,
            support_label_phase_finished=True,
            natural_chronology_verified=False,
        ),
    )
    records = []
    for group in plan["groups"]:
        for qid in group["query_ids"]:
            try:
                feature, encoding_error = ports.encode(qid), None
                feature_stamp = feature.seal()
            except Exception as exc:
                feature, encoding_error = None, str(exc)[:512]
            # Counterbalance ordering, never select a better answer after generation.
            offset = int(digest(qid)[:8], 16) % len(ARMS)
            for arm in ARMS[offset:] + ARMS[:offset]:
                row = dict(
                    query_id=qid,
                    family=group["family"],
                    arm=arm,
                    status="started",
                    reader_attempted=False,
                )
                journal(output / "starts.jsonl", row)
                stamp = time.perf_counter()
                try:
                    if feature is None and arm != "no_evidence":
                        raise ValueError("feature unavailable: " + encoding_error)
                    if ports.select is not None:
                        selected, detail = ports.select(
                            qid, feature, arm, states[group["family"]].get(arm)
                        )
                        row["evidence_selection"] = detail
                    elif arm in ("ranked3", "no_evidence"):
                        selected = (
                            sorted(
                                range(len(feature.candidate_ids)),
                                key=lambda i: (
                                    -float(feature.frozen_scores[i]),
                                    feature.candidate_ids[i],
                                ),
                            )[:3]
                            if arm == "ranked3"
                            else []
                        )
                    else:
                        state = states[group["family"]][arm]
                        if state["status"] != "succeeded":
                            raise ValueError(
                                "unavailable frozen snapshot: " + state["error"]
                            )
                        decision = predict(
                            feature,
                            state["prior"],
                            state["delta"],
                            state["identity"],
                            state["roots"],
                            bank={k: state[k] for k in ("positive", "negative")}
                            if state["neighbor"]
                            else None,
                        )
                        selected = (
                            []
                            if decision["selected"] is None
                            else [decision["selected"]]
                        )
                        row["decision"] = decision
                    row.update(
                        selected=selected,
                        feature_digest=feature_stamp if feature is not None else None,
                        reader_attempted=True,
                    )
                    answer, receipt = ports.answer(qid, selected)
                    row.update(answer=answer, receipt=receipt)
                    if not isinstance(answer, str) or not answer.strip():
                        raise ValueError("empty Reader output")
                    if ports.select is not None and detail is not None:
                        verify_receipt(detail, receipt)
                    if time.perf_counter() - stamp > 30:
                        raise ValueError(
                            "observed per-arm wall budget exceeded; output retained"
                        )
                    row["status"] = "succeeded"
                except Exception as exc:
                    row.update(
                        status="failed",
                        error_type=type(exc).__name__,
                        error=str(exc)[:512],
                    )
                row["seconds"] = time.perf_counter() - stamp
                records.append(row)
                journal(output / "answers.jsonl", row)
                if state_seal(states) != seal or (
                    feature is not None and feature.seal() != feature_stamp
                ):
                    raise ValueError(
                        "evaluation mutated frozen snapshot or feature; no scoring"
                    )
    answer_seal = hashlib.sha256((output / "answers.jsonl").read_bytes()).hexdigest()
    write(
        output / "answer-seal.json",
        dict(sha256=answer_seal, rows=len(records), scoring_started=False),
    )
    for row in records:
        # Even a failed generation retains its query and unknown-score bounds.
        row.update(
            ports.score(row)
            if row["status"] == "succeeded"
            else dict(diagnostic_f1=None, weak_source_hit=None)
        )
        journal(output / "scored.jsonl", row)
    if (
        hashlib.sha256((output / "answers.jsonl").read_bytes()).hexdigest()
        != answer_seal
    ):
        raise ValueError("scoring rewrote original answers")
    report = summarize_answers(records, plan) | dict(
        snapshot_seal=seal,
        answer_seal=answer_seal,
        source_commit=plan.get("source_commit"),
        exact_compute_matched=False,
    )
    if ports.select is not None:
        from system2_matched_evidence import summarize as summarize_budget

        report["matched_evidence"] = summarize_budget(records)
    write(output / "summary.json", report)
    if report["failed"]:
        raise RuntimeError("trial contains failed answers; full census retained")
    return report
