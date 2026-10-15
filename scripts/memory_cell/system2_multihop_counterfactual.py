"""Causal minimal-pair multihop benchmark with disjoint ground-truth evaluation.

Synthetic relation swaps preserve the question and whole-corpus lexical inventory,
while changing which complete relation chain answers the question. No learned
NDU policy, independent human evidence judgment or natural-world accuracy claim.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict

from system2_multihop_evidence import (
    Case,
    SyntheticDoc,
    SyntheticQuestion,
    TOP_K,
    digest,
    fill_three,
    join_path,
    make_case,
    parse_relation,
    select_bm25,
    symbol,
    text_terms,
    validate_case,
    QUESTION_RE,
)

START_INDEX = 40
PAIRS = 16
ARMS = (
    "bm25_top3",
    "joined_top3",
    "reversed_join_top3",
    "missing_start_top3",
    "terminal_only_top3",
)


def swap_target(a: SyntheticDoc, b: SyntheticDoc, kind: str) -> tuple[str, str]:
    x, y = parse_relation(a), parse_relation(b)
    if not x or not y or x[0] != kind or y[0] != kind or x[2] != y[2]:
        raise ValueError("edges must share a semantic type")
    if x[1] == y[1] or x[3] == y[3]:
        raise ValueError("distinct source and target values required")
    templates = {
        ("project", "unit"): "Project {} is assigned to unit {}.",
        ("device", "token"): "Device {} requires clearance token {}.",
    }
    template = templates.get((x[0], x[2]))
    if template is None:
        raise ValueError("unregistered relation swap")
    return template.format(x[1], y[3]), template.format(y[1], x[3])


def _build(base, index: int, variant: int, rewritten: dict[str, str]) -> Case:
    qid = "cf:" + digest(("hepta-counterfactual-v1", index, variant))[:20]
    scope = "synthetic:" + qid
    q = SyntheticQuestion(
        qid,
        "synthetic-counterfactual",
        scope,
        base.question.content,
        base.question.observed_at,
    )
    docs = []
    for rank, d in enumerate(base.documents):
        content = rewritten.get(d.identity, d.content)
        docs.append(
            SyntheticDoc(
                "doc:" + digest((qid, rank, content))[:24],
                "root:" + digest((qid, rank)),
                scope,
                "session:" + qid,
                d.observed_at,
                content,
            )
        )
    path = join_path(q, docs)
    if len(path) != base.hops:
        raise ValueError("counterfactual path changed hop cardinality")
    last = parse_relation(path[-1])
    if last is None or last[2] != "token":
        raise ValueError("unrecognized generated terminal")
    case = Case(
        q,
        tuple(docs),
        tuple(d.identity for d in path),
        last[3],
        base.hops,
        base.attack_distractor,
    )
    validate_case(case)
    return case


def pair(index: int) -> tuple[Case, Case]:
    if type(index) is not int or not 0 <= index < PAIRS:
        raise ValueError("fixed bounded pair index")
    seed = START_INDEX + index
    original = make_case(seed)
    match = QUESTION_RE.fullmatch(original.question.content)
    if match is None:
        raise ValueError("unrecognized target project")
    project_a = match.group(1).upper()
    if original.hops == 3:
        target_source = project_a
        decoy_source = symbol(seed, "PRJ", "decoy0")
        type_name = "project"
    else:
        path = join_path(original.question, original.documents)
        target_source = parse_relation(path[-1])[1]
        decoy_source = symbol(seed, "DEV", "decoy0")
        type_name = "device"
    edges = {
        parse_relation(d)[1]: d
        for d in original.documents
        if parse_relation(d) and parse_relation(d)[0] == type_name
    }
    if target_source not in edges or decoy_source not in edges:
        raise ValueError("missing paired edges")
    a, b = edges[target_source], edges[decoy_source]
    new_a, new_b = swap_target(a, b, type_name)
    cases = (
        _build(original, index, 0, {}),
        _build(original, index, 1, {a.identity: new_a, b.identity: new_b}),
    )
    before, after = cases
    if (
        before.answer == after.answer
        or before.question.content != after.question.content
        or before.question.observed_at != after.question.observed_at
        or before.hops != after.hops
    ):
        raise ValueError("counterfactual did not change only desired relation")
    # Crucially, a bag-of-words classifier cannot distinguish the two corpora.
    bags = [
        Counter(t for d in case.documents for t in text_terms(d.content))
        for case in cases
    ]
    if bags[0] != bags[1]:
        raise ValueError("counterfactual leaks answer through lexical inventory")
    if len(before.documents) != len(after.documents) or any(
        len(x.content.encode()) != len(y.content.encode())
        for x, y in zip(before.documents, after.documents, strict=True)
    ):
        raise ValueError("counterfactual changed document byte sizes or order")
    return cases


def select(arm: str, question, documents) -> tuple[SyntheticDoc, ...]:
    """Selection has no access to Case.answer, required_ids or gold labels."""
    if arm not in ARMS:
        raise ValueError("unknown counterfactual arm")
    if not 1 <= len(documents) <= 16 or len({d.identity for d in documents}) != len(
        documents
    ):
        raise ValueError("invalid candidate pool")
    if any(
        d.scope != question.scope or d.observed_at > question.observed_at
        for d in documents
    ):
        raise ValueError("cross-scope or future source")
    if arm == "bm25_top3":
        return select_bm25(question, documents)
    path = join_path(question, documents)
    if len(path) not in (2, 3):
        raise ValueError("unknown complete relation path")
    if arm == "joined_top3":
        chosen = fill_three(path, question, documents)
    elif arm == "reversed_join_top3":
        chosen = tuple(reversed(fill_three(path, question, documents)))
    else:
        keep = path[1:] if arm == "missing_start_top3" else path[-1:]
        # Select context without the missing essential edges. The true terminal
        # token remains present, testing whether the Reader copies an ungrounded
        # token instead of reasoning or abstaining.
        forbidden = {d.identity for d in path if d not in keep}
        allowed = tuple(d for d in documents if d.identity not in forbidden)
        chosen = fill_three(keep, question, allowed)
        if join_path(question, chosen):
            raise ValueError("negative control unexpectedly has a complete path")
    if len(chosen) != TOP_K or len({d.identity for d in chosen}) != TOP_K:
        raise ValueError("evidence cardinality drift")
    return chosen


def cases() -> tuple[tuple[Case, Case], ...]:
    result = tuple(pair(i) for i in range(PAIRS))
    ids = [case.question.identity for item in result for case in item]
    if len(set(ids)) != 2 * PAIRS:
        raise ValueError("duplicate counterfactual query identity")
    return result


def source_manifest(case) -> str:
    return digest((asdict(case.question), [asdict(x) for x in case.documents]))
