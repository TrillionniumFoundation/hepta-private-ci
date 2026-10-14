"""Independent sealed three-way E-code/R-code/no-label Reader-output audit.

No model calls, no new answer labels, no policy search. This retrospective audit
never treats an E/R echo or continuation of the input JSON as a grounded answer.
The twenty questions are correlated synthetic development tasks, not new data.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile

from system2_multihop_evidence import digest
from system2_multihop_trial import evidence
from system2_native_receipt import strict_json, verified_archive
from system2_onehop_label_ablation import (
    ALL_ARMS as E_ARMS,
    READER_IDENTITY,
    SYSTEM as E_SYSTEM,
    cases,
    outcome as e_outcome,
    selected as e_selected,
)
from system2_onehop_label_lexeme import (
    ALL_ARMS as R_ARMS,
    SYSTEM as R_SYSTEM,
    score as r_score,
    selected as r_selected,
)
from system2_onehop_label_pair_audit import audit as e_archive_audit

SCHEMA = "hepta.system2.onehop-three-presentation-audit.v1"
E_ZIP_SHA256 = "a278014bae564336fc4d63335154cadbf14febc73620d958f45648b17ca0622a"
R_ZIP_SHA256 = "7341c519fc80b66a0156f0b349516ff260042dce9e5c9b94e9af49e362bf9e9b"
E_COMMIT = "24a1175958870816e40c7c62bbe1421b83e55dbd"
R_COMMIT = "838da1f54041181fb4f0aa7b1668f056789a36fb"
E_TREE = "84689f6c75dc35b8e9ff515be32094182438fa05"
R_TREE = "484bb81b5a976c5e85825d9a3a193d85a735403e"
E_RAW_SHA256 = "6f630a86d374658049377d4611f92fd6c0dd6626c267eef7c37d77f07f5aeaa2"
R_RAW_SHA256 = "1cbcdfbc6512d93ee11f9a2cafb5414f0987d0fcfd0b07b1a0d9e576b258b04b"
ARMS = ("single_fact", "target_decoy_two_first", "decoy_one")
PRESENTATIONS = ("E", "R", "unlabeled")
PLANNED_PAIRS = len(ARMS) * 20
METRICS = (
    "exact_answer_only",
    "correct_token_mentioned",
    "label_only_echo",
    "prescribed_refusal",
    "unsupported_token_output",
    "success",
    "json_input_echo",
    "at_64_token_cap",
)
LABEL_LIST = re.compile(r"\s*[ER]\d+(?:[\s,;]+[ER]\d+)*\s*", re.I)


def strict_rows(payload, *, length, label):
    lines = payload.splitlines()
    if len(lines) != length:
        raise ValueError(f"{label} complete result census changed")
    return [strict_json(x) for x in lines]


def load_zip(path, sha, generating, tree, raw_pin, planned):
    files = verified_archive(Path(path), sha)
    if (
        files["tested-commit.txt"].decode().strip() != generating
        or files["tested-tree.txt"].decode().strip() != tree
    ):
        raise ValueError("generating Git commit/tree differs from pinned receipt")
    raw = files["trial/raw-answers.jsonl"]
    seal = strict_json(files["trial/raw-seal.json"])
    if hashlib.sha256(raw).hexdigest() != raw_pin or seal != dict(
        rows=planned, scoring_started=False, sha256=raw_pin
    ):
        raise ValueError("original unmodified prediction seal mismatch")
    starts = strict_rows(files["trial/starts.jsonl"], length=planned, label="start")
    if any(row.get("status") != "started" for row in starts):
        raise ValueError("missing start journal or modified status")
    return files, strict_rows(raw, length=planned, label="answer"), starts


def audit(cardinality_zip, e_zip, r_zip):
    """Check three external archive digests and each saved model input/output."""
    # Never extract arbitrary archive member paths; write six known data names
    # only into a temporary directory for the existing full E-code scorer audit.
    efiles, erows, estarts = load_zip(
        e_zip, E_ZIP_SHA256, E_COMMIT, E_TREE, E_RAW_SHA256, 140
    )
    rfiles, rrows, rstarts = load_zip(
        r_zip, R_ZIP_SHA256, R_COMMIT, R_TREE, R_RAW_SHA256, 60
    )
    if E_SYSTEM != R_SYSTEM:
        raise ValueError("answer-only system prompt changed between E/R labels")
    with tempfile.TemporaryDirectory(prefix="hepta-label-triad-") as tmp:
        root = Path(tmp)
        for name in (
            "plan.json",
            "starts.jsonl",
            "raw-answers.jsonl",
            "raw-seal.json",
            "scored.json",
            "summary.json",
        ):
            (root / name).write_bytes(efiles["trial/" + name])
        evalidated = e_archive_audit(root, cardinality_zip, generating_commit=E_COMMIT)
    cohort = cases()
    qids = {c.question.identity for c in cohort}
    if len(cohort) != 20 or len(qids) != 20:
        raise ValueError("original 20-question synthetic cohort changed")
    eexpected = {
        (qid, arm, presentation) for qid in qids for arm, presentation in E_ARMS
    }
    rexpected = {
        (qid, arm, presentation) for qid in qids for arm, presentation in R_ARMS
    }
    ekeys = [(r["qid"], r["arm"], r["presentation"]) for r in erows]
    rkeys = [(r["qid"], r["arm"], r["presentation"]) for r in rrows]
    for keys, expected, label in ((ekeys, eexpected, "E"), (rkeys, rexpected, "R")):
        if (
            len(keys) != len(expected)
            or len(set(keys)) != len(keys)
            or set(keys) != expected
        ):
            raise ValueError(label + " planned question/arm identity drift")
    if (
        len(set((r["qid"], r["arm"], r["presentation"]) for r in estarts)) != 140
        or len(set((r["qid"], r["arm"], r["presentation"]) for r in rstarts)) != 60
    ):
        raise ValueError("start journal does not cover all planned conditions")
    eidx = dict(zip(ekeys, erows, strict=True))
    ridx = dict(zip(rkeys, rrows, strict=True))
    rplan = strict_json(rfiles["trial/plan.json"])
    if (
        rplan.get("schema") != "hepta.system2.onehop-label-lexeme.v1"
        or rplan.get("source_commit") != R_COMMIT
        or rplan.get("parent_sha256")
        != "9f4a4ed9429212b98befffca27a297780d61317eaed8be519b1cb6880037f121"
        or rplan.get("parent_commit") != "0abf776ccb577755ddba36dea3fa21a078308ad7"
        or rplan.get("planned") != 60
        or rplan.get("conditions") != [list(x) for x in R_ARMS]
        or rplan.get("task_ids") != [c.question.identity for c in cohort]
        or rplan.get("fixed_reader_identity") != READER_IDENTITY
        or rplan.get("same_answer_only_system") is not True
        or rplan.get("label_property_retained") is not True
        or rplan.get("no_weight_update") is not True
        or rplan.get("production_accepted") is not False
    ):
        raise ValueError("R-label pre-registered model/source plan changed")
    rscored, rgroups = r_score(rrows, cohort)
    if strict_json(rfiles["trial/scored.json"]) != rscored:
        raise ValueError("R-label recorded outcomes cannot be reproduced")
    rsummary = strict_json(rfiles["trial/summary.json"])
    if (
        rsummary.get("groups") != rgroups
        or rsummary.get("planned") != 60
        or rsummary.get("recorded") != 60
        or rsummary.get("failed") != sum(r["status"] == "failed" for r in rrows)
        or rsummary.get("raw_sha256") != R_RAW_SHA256
        or rsummary.get("candidate_disposition") != "lexeme_control_only_no_selection"
        or rsummary.get("production_accepted") is not False
    ):
        raise ValueError("R-label stored summary changed")
    report = []
    for arm in ARMS:
        observed = []
        for case in cohort:
            qid = case.question.identity
            versions = dict(
                E=eidx[(qid, arm, "labeled")],
                R=ridx[(qid, arm, "neutral_code")],
                unlabeled=eidx[(qid, arm, "unlabeled")],
            )
            if any(
                r["status"] not in ("succeeded", "failed") for r in versions.values()
            ):
                raise ValueError("invalid attempt status")
            row = dict(
                qid=qid,
                statuses={
                    name: version["status"] for name, version in versions.items()
                },
            )
            if all(r["status"] == "succeeded" for r in versions.values()):
                docs = e_selected(case, arm)
                if docs != r_selected(case, arm):
                    raise ValueError("selection changed between label presentations")
                bundle, _, _ = evidence(case, docs, "answer-only:" + arm)
                bound = bundle.delivered()
                for name, r in versions.items():
                    rec = r["reader"]
                    if (
                        r["selected"] != [d.identity for d in docs]
                        or rec.get("reader_identity") != READER_IDENTITY
                        or rec.get("query_digest") != digest(asdict(case.question))
                        or rec.get("bundle_digest") != bundle.seal()
                        or rec.get("delivered_evidence") != bound
                        or rec.get("token_limit") != 1024
                        or rec.get("trainable_parameters") != 0
                        or rec.get("answer_postprocessed") is not False
                        or not 1 <= rec.get("input_tokens", 0) <= 1024
                        or not 1 <= rec.get("generated_tokens", 0) <= 64
                        or not re.fullmatch(
                            "[0-9a-f]{64}", rec.get("input_ids_digest", "")
                        )
                        or not re.fullmatch(
                            "[0-9a-f]{64}", rec.get("generated_ids_digest", "")
                        )
                    ):
                        raise ValueError(
                            "source, model, or input token receipt drift: " + name
                        )
                erec = versions["E"]["reader"]
                rrec = versions["R"]["reader"]
                if (
                    rrec["reference_labeled_input_digest"] != erec["input_ids_digest"]
                    or rrec["reference_labeled_input_tokens"] != erec["input_tokens"]
                    or rrec["token_count_delta"]
                    != rrec["input_tokens"] - erec["input_tokens"]
                    or rrec["equal_input_token_counts"]
                    != (rrec["input_tokens"] == erec["input_tokens"])
                ):
                    raise ValueError(
                        "neutral-code counterfactual source input binding drift"
                    )
                outcomes = {}
                for name, r in versions.items():
                    raw = r["answer"]
                    if name == "R":
                        from system2_onehop_label_lexeme import outcome as r_outcome

                        metrics = r_outcome(case, arm, "neutral_code", raw)
                    else:
                        metrics = e_outcome(
                            case, arm, "labeled" if name == "E" else "unlabeled", raw
                        )
                    metrics.update(
                        json_input_echo=raw.lstrip().startswith('{"question"'),
                        at_64_token_cap=r["reader"]["generated_tokens"] == 64,
                        label_only_echo=bool(LABEL_LIST.fullmatch(raw)),
                    )
                    outcomes[name] = {k: bool(metrics[k]) for k in METRICS}
                row.update(
                    outcomes=outcomes,
                    input_tokens={
                        name: r["reader"]["input_tokens"]
                        for name, r in versions.items()
                    },
                    output_tokens={
                        name: r["reader"]["generated_tokens"]
                        for name, r in versions.items()
                    },
                    e_vs_r_same_input_token_count=(
                        erec["input_tokens"] == rrec["input_tokens"]
                    ),
                    e_vs_r_same_source_token_digest=(
                        erec["input_ids_digest"]
                        == rrec["reference_labeled_input_digest"]
                    ),
                    e_vs_r_distinct_actual_input_token_digest=(
                        erec["input_ids_digest"] != rrec["input_ids_digest"]
                    ),
                )
            else:
                row["unknown_result_not_imputed"] = True
            observed.append(row)
        complete = [row for row in observed if "outcomes" in row]
        count = len(complete)
        confusion = {}
        for metric in METRICS:
            patterns = Counter(
                "".join(
                    "1" if row["outcomes"][name][metric] else "0"
                    for name in PRESENTATIONS
                )
                for row in complete
            )
            confusion[metric] = dict(
                planned=20,
                observed=count,
                unknown=20 - count,
                patterns={
                    format(n, "03b"): patterns.get(format(n, "03b"), 0)
                    for n in range(8)
                },
                observed_each={
                    name: sum(row["outcomes"][name][metric] for row in complete)
                    for name in PRESENTATIONS
                },
                planned_each_bounds={
                    name: [
                        sum(row["outcomes"][name][metric] for row in complete),
                        sum(row["outcomes"][name][metric] for row in complete)
                        + 20
                        - count,
                    ]
                    for name in PRESENTATIONS
                },
            )
        report.append(
            dict(
                arm=arm,
                planned=20,
                complete=count,
                unknown=20 - count,
                metrics=confusion,
                e_r_same_input_token_count=sum(
                    row.get("e_vs_r_same_input_token_count", False) for row in complete
                ),
                e_r_different_input_token_ids=sum(
                    row["e_vs_r_distinct_actual_input_token_digest"] for row in complete
                ),
                input_token_gap_R_minus_E=[
                    row["input_tokens"]["R"] - row["input_tokens"]["E"]
                    for row in complete
                ],
                generated_token_gap_R_minus_E=[
                    row["output_tokens"]["R"] - row["output_tokens"]["E"]
                    for row in complete
                ],
                per_question=observed,
            )
        )
    return dict(
        schema=SCHEMA,
        source_model=READER_IDENTITY,
        source_arms=list(ARMS),
        presentations=list(PRESENTATIONS),
        each_arm_planned_questions=20,
        source_question_count=20,
        planned_source_model_calls=200,  # 140 E/unlabeled + 60 R; zero new inference
        paired_subjects=PLANNED_PAIRS,
        e_archive_sha256=E_ZIP_SHA256,
        r_archive_sha256=R_ZIP_SHA256,
        cardinality_parent_sha256="9f4a4ed9429212b98befffca27a297780d61317eaed8be519b1cb6880037f121",
        e_raw_sha256=E_RAW_SHA256,
        r_raw_sha256=R_RAW_SHA256,
        e_original_checked=evalidated["planned_model_calls"] == 140,
        e_verified_parent_files=evalidated["verified_parent_files"],
        r_verified_files=len(rfiles) - 1,
        by_arm=report,
        model_calls_added=0,
        no_trained_NDU_gain=True,
        distinct_input_token_strings_not_equal_compute=True,
        independently_new_questions=0,
        production_accepted=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cardinality_archive", type=Path)
    parser.add_argument("labeled_unlabeled_archive", type=Path)
    parser.add_argument("neutral_R_archive", type=Path)
    parser.add_argument("output_json", type=Path)
    args = parser.parse_args()
    result = audit(
        args.cardinality_archive, args.labeled_unlabeled_archive, args.neutral_R_archive
    )
    if args.output_json.exists():
        raise ValueError("refuse to overwrite an existing signed research outcome")
    args.output_json.write_text(
        json.dumps(result, indent=2, allow_nan=False, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            dict(
                source_model_calls=result["planned_source_model_calls"],
                zero_new_calls=result["model_calls_added"],
                paired_subjects=result["paired_subjects"],
                e_r_matched_input_tokens=sum(
                    x["e_r_same_input_token_count"] for x in result["by_arm"]
                ),
            ),
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
