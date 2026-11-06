"""Source-only LoCoMo pilot: precommit ten genuine conversation-family proxies.

This does NOT convert published conversations into prospective observations or
certify their semantic independence. LongMemEval's one-family adapter is NOT
included, split into invented families, or counted towards this pilot.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from external_family_population import (
    LIMITS,
    MAX_PER_FAMILY,
    PROFILE,
    SOURCE_PINS,
    SPLITS,
    PublicCorpus,
    _corpus_rows,
    _rank,
    canonical,
    digest,
    publish_and_seal,
)

SCHEMA = "hepta.memorycell.locomo-family-only-pilot.v1"


def precommit_locomo(corpus, *, source_commit, limits=None):
    """Select published LoCoMo family proxies without ever accessing targets.

    Reuse the parent source-family and source-root leakage checks *unchanged*.
    No LongMemEval source is admitted; the original two-corpus gate remains red.
    """
    if (
        not isinstance(source_commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
        or corpus.name != "locomo"
        or corpus.source_sha256 != SOURCE_PINS["locomo"]
    ):
        raise ValueError("exact LoCoMo source bytes and generating commit required")
    limits = dict(LIMITS if limits is None else limits)
    if set(limits) != set(SPLITS) or any(
        type(v) is not int or not 1 <= v <= 1000 for v in limits.values()
    ):
        raise ValueError("registered per-split source-only limits required")

    # _corpus_rows rejects fewer than ten genuine groups, reused/overlapping
    # original roots, missing histories, and duplicate original identities.
    source_rows, census = _corpus_rows(corpus)
    groups = census["split_family_proxies"]
    if (
        census["family_proxy_groups"] < 10
        or groups["train"] < 1
        or groups["selection"] < 1
        or groups["evaluation"] < 2
    ):
        raise ValueError("insufficient unmerged LoCoMo source-family groups")

    selected = {}
    for split in SPLITS:
        by_group = {}
        for row in source_rows[split]:
            if row["dataset"] != "locomo":
                raise ValueError("external corpus entered LoCoMo-only selection")
            by_group.setdefault(row["family_proxy_digest"], []).append(row)
        order = sorted(by_group, key=lambda group: (_rank(split, group), group))
        for group in order:
            by_group[group].sort(
                key=lambda row: (_rank(row["question_id"]), row["question_id"])
            )
        chosen = []
        for slot in range(MAX_PER_FAMILY):
            for group in order:
                if slot < len(by_group[group]) and len(chosen) < limits[split]:
                    chosen.append(by_group[group][slot])
        if not chosen:
            raise ValueError("missing LoCoMo split observations")
        selected[split] = chosen

    qids = [r["question_id"] for rows in selected.values() for r in rows]
    if len(qids) != len(set(qids)):
        raise ValueError("a native question entered multiple partitions")
    seen_families = {}
    for split, rows in selected.items():
        for row in rows:
            group = row["family_proxy_digest"]
            if seen_families.setdefault(group, split) != split:
                raise ValueError("a native family was leaked across partitions")
    if len({r["family_proxy_digest"] for r in selected["evaluation"]}) < 2:
        raise ValueError("evaluation requires at least two distinct native groups")

    capacity = dict(
        schema=SCHEMA,
        generating_source_commit=source_commit,
        accepted_dataset="locomo",
        accepted_source_sha256=SOURCE_PINS["locomo"],
        actual_published_family_proxy_groups=census["family_proxy_groups"],
        split_family_proxy_capacity=groups,
        quarantined_dataset="longmemeval",
        quarantined_data_admitted=False,
        original_two_corpus_gate_not_overridden=True,
        target_answers_read=False,
        genuinely_independent_future_families=0,
        published_source_proxies_not_human_certified=True,
        production_accepted=False,
    )
    public = dict(
        schema=SCHEMA,
        generating_source_commit=source_commit,
        source_sha256={"locomo": SOURCE_PINS["locomo"]},
        source_capacity_sha256=sha256(canonical(capacity) + b"\n").hexdigest(),
        original_two_corpus_gate_overridden=False,
        source_family_cut="published native LoCoMo conversations; hashed 60/20/20",
        question_pick_rule="label-blind family round robin; at most 8 per family",
        limit_per_split=limits,
        census=census,
        splits=selected,
        model_input_contains_answers=False,
        published_benchmarks_are_future_observations=False,
        independent_source_authenticity_verified=False,
        independent_semantic_judgement=False,
        production_accepted=False,
    )
    return public, capacity


def seal_source_only_pilot(corpus, *, source_commit, output, target_supplier):
    """Write the admission census and public cut before invoking label supplier."""
    output = Path(output)
    if output.exists():
        raise FileExistsError("immutable output location required")
    public, capacity = precommit_locomo(corpus, source_commit=source_commit)
    capacity_path = output.with_name(output.name + "-capacity.json")
    with capacity_path.open("xb") as target:
        target.write(canonical(capacity) + b"\n")
        target.flush()
        os.fsync(target.fileno())
    manifest = publish_and_seal(public, target_supplier, output)
    if manifest["production_accepted"] is not False:
        raise ValueError("published pilot cannot grant production admission")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("locomo", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    from native import load

    benchmark = load(
        args.locomo,
        "locomo",
        SOURCE_PINS["locomo"],
        allow_unresolved_evidence=True,
        session_conflicts="retain-versioned",
        invalid_history="quarantine-question",
    )
    corpus = PublicCorpus.from_native(benchmark)

    # The supplier is not evaluated until publish_and_seal has fsynced the
    # label-blind population. The reader job must receive ONLY /public.
    def original_targets():
        public = json.loads((args.output / "public/population.json").read_text())
        selected = {
            row["question_id"] for rows in public["splits"].values() for row in rows
        }
        return {
            qid: value for qid, value in benchmark.targets.items() if qid in selected
        }

    receipt = seal_source_only_pilot(
        corpus,
        source_commit=args.source_commit,
        output=args.output,
        target_supplier=original_targets,
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
