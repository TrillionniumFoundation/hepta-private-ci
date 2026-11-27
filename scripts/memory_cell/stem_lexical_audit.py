"""Reproduce source-only lexical recall on the strictly pinned native index.

After original six-arm answers are sealed, compare original native-document
support with frozen index FTS5 BM25 ranks at fixed k={8,16,32,64}. No model,
training, Reader, candidate change, test-time tuning, or production admission.
"""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile

from stem_audit_archive import PinnedArchive, require

ZIP_SHA = "3bc5f45670b9cbb5fc22d1cbff5b96866443400ea42781072b9fd66ad5ea19c8"
LOC_SHA = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
SOURCE = "ad0343aee6772fec4692011f59d306c750dfd2d9"
TREE = "675a0579de6fa2f973d5247519ed206fc469a374"
PHASES = ("select", "retention", "test")
K = (8, 16, 32, 64)


def lexical_rank(db, question, maximum=64):
    """Use EXACT original query terms and deterministic FTS5 ordering."""
    terms = list(dict.fromkeys(re.findall(r"\w+", question.lower())))[:128]
    if not terms:
        return []
    expression = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
    return [
        row[0]
        for row in db.execute(
            "SELECT rowid FROM lexical WHERE lexical MATCH ? "
            "ORDER BY bm25(lexical), rowid LIMIT ?",
            (expression, maximum),
        )
    ]


def native_qa(path):
    payload = Path(path).read_bytes()
    require(
        hashlib.sha256(payload).hexdigest() == LOC_SHA,
        "original LoCoMo source bytes changed",
    )
    data = json.loads(payload)
    require(
        isinstance(data, list) and len(data) == 10,
        "unexpected original LoCoMo corpus count",
    )
    questions = {}
    for sample in data:
        scope = "locomo:" + str(sample["sample_id"])
        for i, item in enumerate(sample["qa"]):
            key = f"{scope}/q{i}"
            require(
                key not in questions and isinstance(item["question"], str),
                "duplicate native question",
            )
            questions[key] = dict(
                scope=scope,
                text=item["question"],
                support={scope + "/" + entry for entry in item.get("evidence", [])},
            )
    return questions


def audit(native_zip, native_locomo):
    source = native_qa(native_locomo)
    archive = PinnedArchive(Path(native_zip), ZIP_SHA)
    try:
        require(
            archive.read("tested-commit.txt").decode().strip() == SOURCE
            and archive.read("tested-tree.txt").decode().strip() == TREE,
            "strict native generating source/tree mismatch",
        )
        report = archive.json("comparison/report.json")
        plans = report["plan"]["questions"]
        rows = [
            row
            for row in report["retrospective_weak_source_ceiling"]["decisions"]
            if row["phase"] in PHASES and row["weak_native_support_resolved"]
        ]
        expected = {row["question_id"] for row in rows}
        require(
            len(rows) == len(expected) == 18,
            "18 original answerable questions required",
        )
        registered = {q for phase in PHASES for q in plans[phase]}
        require(expected.issubset(registered), "unregistered source-ceiling case")
        by_scope = defaultdict(list)
        for row in rows:
            q = row["question_id"]
            require(
                q in source and not row["native_source_unanswerable"],
                "source labels not from original pinned LoCoMo question",
            )
            by_scope[source[q]["scope"]].append(row)
        observed = {}
        index_count = 0
        with tempfile.TemporaryDirectory() as temp:
            for path in sorted(archive.files):
                if not path.startswith("comparison/index-") or not path.endswith(
                    ".sqlite"
                ):
                    continue
                index_count += 1
                disk = Path(temp) / Path(path).name
                disk.write_bytes(archive.read(path))
                db = sqlite3.connect(
                    disk.resolve().as_uri() + "?mode=ro&immutable=1", uri=True
                )
                try:
                    metadata = json.loads(
                        db.execute("SELECT value FROM meta").fetchone()[0]
                    )
                    scope = metadata["scope"]
                    if scope not in by_scope:
                        continue
                    document_by_rowid = {
                        rowid: json.loads(record)["identity"]
                        for rowid, record in db.execute(
                            "SELECT rowid, record FROM docs"
                        )
                    }
                    for original in by_scope[scope]:
                        qid = original["question_id"]
                        require(qid not in observed, "duplicate original scope index")
                        native = source[qid]
                        labelled = native["support"]
                        index_support = labelled.intersection(
                            document_by_rowid.values()
                        )
                        ordered = [
                            document_by_rowid[i]
                            for i in lexical_rank(db, native["text"])
                        ]
                        observed[qid] = dict(
                            phase=original["phase"],
                            question_id=qid,
                            indexed_support_count=len(index_support),
                            original_pool_has_support=(
                                original["native_support_available_in_pool"] is True
                            ),
                            lexical_first_supported_rank=next(
                                (
                                    i + 1
                                    for i, name in enumerate(ordered)
                                    if name in labelled
                                ),
                                None,
                            ),
                            lexical_hits_at_k={
                                str(k): bool(labelled.intersection(ordered[:k]))
                                for k in K
                            },
                            source_content_exported=False,
                            semantic_entailment_independently_verified=False,
                        )
                finally:
                    db.close()
        require(
            set(observed) == expected and index_count == 18,
            "missing or altered strict time-index scope",
        )
        missed = [
            item for item in observed.values() if not item["original_pool_has_support"]
        ]
        require(
            len(missed) == 8 and all(x["indexed_support_count"] > 0 for x in missed),
            "all eight original candidate misses were actually indexed",
        )
        by_phase = {}
        for phase in PHASES:
            group = [x for x in observed.values() if x["phase"] == phase]
            require(len(group) == 6, "original answerable phase denominator")
            by_phase[phase] = dict(
                answerable_questions=6,
                original_pool_has_support=sum(
                    x["original_pool_has_support"] for x in group
                ),
                source_already_indexed=sum(
                    x["indexed_support_count"] > 0 for x in group
                ),
                lexical_support_recalled_at_k={
                    str(k): sum(x["lexical_hits_at_k"][str(k)] for x in group)
                    for k in K
                },
            )
        lexical_missed = {
            str(k): sum(x["lexical_hits_at_k"][str(k)] for x in missed) for k in K
        }
        # Historical deterministic receipt: a changed value requires a new
        # independently disclosed report, not an edited claimed result.
        require(
            lexical_missed == {"8": 0, "16": 0, "32": 0, "64": 1},
            "original pinned lexical-recall contrast changed",
        )
        return dict(
            schema="hepta.stem-immutable-lexical-ceiling.v1",
            generating_source=SOURCE,
            generating_tree=TREE,
            native_zip_sha256=ZIP_SHA,
            locomo_json_sha256=LOC_SHA,
            verified_native_zip_members=archive.manifest_entries,
            registered_answerable_locomo_questions=len(observed),
            registered_pool_support_misses=len(missed),
            missing_support_but_source_already_in_asof_index=len(missed),
            frozen_lexical_hits_in_original_misses_at_k=lexical_missed,
            phase_retrieval=by_phase,
            diagnosed_questions=[observed[q] for q in sorted(observed)],
            no_encoder_head_or_reader_model_calls=True,
            readonly_fts5_queries_executed=True,
            native_test_labels_consumed_only_post_original_policy=True,
            new_independent_holdout_observations=0,
            posthoc_exploration_not_preregistered_selector=True,
            independent_semantic_support_not_verified=True,
            production_accepted=False,
        )
    finally:
        archive.close()


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--artifact", type=Path, required=True)
    cli.add_argument("--locomo", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    result = audit(args.artifact, args.locomo)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "schema": result["schema"],
                "candidate_pool_missing": result["registered_pool_support_misses"],
                "indexed_sources": result[
                    "missing_support_but_source_already_in_asof_index"
                ],
                "lexical_k": result["frozen_lexical_hits_in_original_misses_at_k"],
                "production_accepted": False,
            }
        )
    )


if __name__ == "__main__":
    main()
