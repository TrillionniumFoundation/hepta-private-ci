"""Read-only, source-pinned LoCoMo QA/refusal and retrieved-support attribution.

This is a diagnostic sensitivity calculation over ORIGINAL frozen Qwen outputs.
No model inference, label-aware retrieval, citation repair or production decision.
The registered exact-refusal/token-F1 score is retained unchanged. A prefix
refusal is *not* certified semantically safe when extra text follows it.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import string
import zipfile

PROFILE = "hepta.memorycell.locomo-original-reader-refusal-strata.v1"
EXPECTED_ZIPS = {
    "public": "51e18514c68f31220f4dcd072914f6e015aa9733b6c5b4a4d4e3b14dac25ec37",
    "decisions": "3fb1c3272314d31b42ece1c74aa0250e2ecb06c6060cb011071d4654fef6f097",
    "targets": "d09823324003ab431301e60fbbb280e216ca03b686e178d4f36fb6d492981978",
    "reader": "7160ede72114b04135e544fb687a804dc0c4852834cf1695440a75b85214bf48",
    "score": "5c36103c506367de2ba42ea242bc81b53ad9734f1417132ce2945d0473ed391e",
}
GENERATING_COMMIT = "96b5ec37b82f87d445740403e07e3705e9850955"
MODEL_ID = "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"
RAW_SHA = "b13f70b5b8ff0664d7a446b11b2a474702d61a50348534ca1b26cc295a0e9bb2"
POPULATION_SHA = "f53ee0986825f30ec4503b1698639e230832d1c05351c689cb55ebdc4f01d6de"
HISTORY_SHA = "b42a90e01df2eb8d2da8a77e6218dc1124b7c19005f52d23ef8c1acd0aeed5cc"
ARMS = ("lexical_k4", "lexical_k8")
REFUSAL = "I do not have enough evidence."
MARKER = re.compile(r"\[E[1-9][0-9]*\]")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def pairs(items):
        result = {}
        for k, value in items:
            if k in result:
                raise ValueError("duplicate JSON field")
            result[k] = value
        return result

    def fail(value):
        raise ValueError("nonfinite JSON token: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=fail)


def checked_zip(path, pin):
    """Reject changed/unsafe archives; original public/target ZIPs lack manifests."""
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16_777_216:
        raise ValueError("missing/oversized/symlinked original archive")
    payload = path.read_bytes()
    if sha(payload) != pin:
        raise ValueError("original entire ZIP SHA256 differs")
    files = {}
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if (
            not 1 <= len(members) <= 100
            or sum(m.file_size for m in members) > 32_000_000
        ):
            raise ValueError("unbounded original ZIP members")
        for m in members:
            p = PurePosixPath(m.filename)
            if (
                p.is_absolute()
                or ".." in p.parts
                or "." in p.parts
                or "\\" in m.filename
                or p.as_posix() != m.filename
                or m.filename in files
                or m.is_dir()
                or stat.S_ISLNK(m.external_attr >> 16)
            ):
                raise ValueError("unsafe original ZIP path")
            files[m.filename] = archive.read(m)
    if "SHA256SUMS" in files:
        declared = {}
        for line in files.pop("SHA256SUMS").decode().splitlines():
            m = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
            if m is None or m[2] in declared:
                raise ValueError("invalid original SHA256SUMS")
            declared[m[2]] = m[1]
        if set(declared) != set(files) or any(
            sha(files[k]) != value for k, value in declared.items()
        ):
            raise ValueError("original ZIP member manifest mismatch")
    return files


def normalize(text):
    """EXACT registered LoCoMo scorer grammar (not improved post-hoc)."""
    without_citations = MARKER.sub("", text).lower()
    unpunctuated = "".join(c for c in without_citations if c not in string.punctuation)
    return " ".join(re.sub(r"\b(a|an|the)\b", " ", unpunctuated).split())


def answer_f1(answer, target):
    if target["unanswerable"]:
        return float(answer.strip() == REFUSAL)
    gold = target["answer"]
    if not isinstance(gold, str) or not gold.strip():
        raise ValueError("answerable query missing published answer")
    first, second = normalize(answer).split(), normalize(gold).split()
    common = sum((Counter(first) & Counter(second)).values())
    return (
        2 * common / (len(first) + len(second))
        if first and second
        else float(first == second)
    )


def refusal_shape(answer):
    """Prefix match is a formatting sensitivity, NEVER an entailment judgement."""
    if not isinstance(answer, str):
        raise ValueError("original decoder answer required")
    if answer.strip() == REFUSAL:
        return "strict_exact"
    if answer.startswith(REFUSAL):
        return "canonical_prefix_plus_unreviewed_content"
    return "not_canonical_refusal"


def _rows(payload, *, max_rows):
    lines = payload.splitlines()
    if not 1 <= len(lines) <= max_rows or any(not x.strip() for x in lines):
        raise ValueError("incomplete/blank original rows")
    return [strict_json(x) for x in lines]


def _originals(artifacts):
    # Publisher QA labels are opened only after every immutable source,
    # retrieval decision and original model receipt has been checked.
    a = {
        key: checked_zip(artifacts[key], EXPECTED_ZIPS[key])
        for key in ("public", "decisions", "reader", "score")
    }
    if sha(a["public"]["population.json"]) != POPULATION_SHA:
        raise ValueError("published population was replaced")
    if sha(a["public"]["histories.jsonl"]) != HISTORY_SHA:
        raise ValueError("published original histories changed")
    if sha(a["reader"]["run/raw-answers.jsonl"]) != RAW_SHA:
        raise ValueError("published original answer journal changed")
    ready = strict_json(a["reader"]["run/READY.json"])
    if (
        ready["generating_commit"] != GENERATING_COMMIT
        or ready["model_identity"] != MODEL_ID
        or ready["labels_seen_during_generation"] is not False
        or ready["original_answers_rewritten"] is not False
        or ready["raw_journal_sha256"] != RAW_SHA
        or ready["original_source_sha256"] != EXPECTED_ZIPS["public"]
        or ready["original_six_decisions_sha256"] != EXPECTED_ZIPS["decisions"]
        or ready["planned_model_calls"] != 32
        or ready["actual_model_calls"] != 32
        or ready["weight_updates"] != 0
    ):
        raise ValueError("original Qwen generation run is not frozen")
    report = strict_json(a["score"]["result/report.json"])
    if (
        report["generating_commit"] != GENERATING_COMMIT
        or report["original_raw_answers_sha256"] != RAW_SHA
        or report["reference_model_inventory_identity"] != MODEL_ID
        or report["production_accepted"] is not False
    ):
        raise ValueError("separately hosted score differs from generating source")
    population = strict_json(a["public"]["population.json"])
    history = _rows(a["public"]["histories.jsonl"], max_rows=10000)
    docs = {d["identity"]: d for d in history}
    if len(history) != 5882 or len(docs) != len(history):
        raise ValueError("original history census changed")
    all_decisions = _rows(a["decisions"]["decisions.jsonl"], max_rows=1000)
    if len(all_decisions) != 480:
        raise ValueError("original six-arm decisions changed")
    originals = _rows(a["reader"]["run/raw-answers.jsonl"], max_rows=32)
    if len(originals) != 32:
        raise ValueError("missing actual original model generation")
    decisions = {(d["question_id"], d["arm"]): d for d in all_decisions}
    if len(decisions) != 480:
        raise ValueError("duplicate frozen decisions")
    cases = population["splits"]["evaluation"]
    questions = {c["question_id"]: c for c in cases}
    if (
        len(cases) != 16
        or len(questions) != 16
        or len({c["family_proxy_digest"] for c in cases}) != 2
    ):
        raise ValueError("original fixed LoCoMo evaluation census drift")
    if {(r["question_id"], r["arm"]) for r in originals} != {
        (qid, arm) for qid in questions for arm in ARMS
    } or len(originals) != 32:
        raise ValueError("missing, duplicate or substituted real model arm")
    if len({(r["question_id"], r["arm"]) for r in originals}) != 32:
        raise ValueError("duplicate real model execution")
    for q in cases:
        qid = q["question_id"]
        low = decisions[(qid, "lexical_k4")]["selected"]
        high = decisions[(qid, "lexical_k8")]["selected"]
        if len(low) != 4 or len(high) != 8 or low != high[:4]:
            raise ValueError("original retrieval policy/order drift")
    for r in originals:
        key = r["question_id"], r["arm"]
        if r["status"] != "succeeded" or r["selected"] != decisions[key]["selected"]:
            raise ValueError("unavailable/altered original model evidence")
        q = questions[key[0]]
        receipt = r["receipt"]
        if (
            r["family_proxy_digest"] != q["family_proxy_digest"]
            or r["source_census_sha256"] != q["source_census_sha256"]
            or receipt["reader_identity"] != MODEL_ID
            or receipt["token_limit"] != 2048
            or receipt["trainable_parameters"] != 0
            or receipt["answer_postprocessed"] is not False
            or type(receipt["input_tokens"]) is not int
            or not 1 <= receipt["input_tokens"] <= 2048
            or type(receipt["generated_tokens"]) is not int
            or not 1 <= receipt["generated_tokens"] <= 64
            or len(receipt["delivered_evidence"]) != len(r["selected"])
        ):
            raise ValueError("reader identity/budget/delivered census drift")
        for expected, evidence in zip(
            r["selected"], receipt["delivered_evidence"], strict=True
        ):
            if (
                expected not in docs
                or evidence["original_id"] != expected
                or evidence["excerpt"] != docs[expected]["content"]
                or evidence["source_digest"]
                != _native_digest(docs[expected]["content"])
            ):
                raise ValueError("original UTF-8 delivered evidence differs")
    targets = strict_json(
        checked_zip(artifacts["targets"], EXPECTED_ZIPS["targets"])["targets.json"]
    )
    if set(targets) != set(questions):
        raise ValueError("original evaluation targets missing or substituted")
    for qid, t in targets.items():
        if type(t.get("unanswerable")) is not bool or not isinstance(
            t.get("support"), list
        ):
            raise ValueError("unregistered original target")
        if not set(t["support"]).issubset(questions[qid]["source_ids"]):
            raise ValueError("publisher support outside original question history")
    return questions, docs, decisions, originals, targets, report


def _native_digest(value):
    return sha(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    )


def _rollup(rows):
    return dict(
        planned=len(rows),
        f1_sum=sum(r["f1"] for r in rows),
        mean_f1=(sum(r["f1"] for r in rows) / len(rows)) if rows else None,
        prompt_tokens=sum(r["prompt_tokens"] for r in rows),
        answer_with_any_valid_label=sum(r["valid_label_count"] > 0 for r in rows),
    )


def compute(questions, originals, targets, hosted_score):
    """Keep exact preregistered F1; alternate refusal is explicitly post hoc."""
    byarm = defaultdict(list)
    for row in originals:
        t = targets[row["question_id"]]
        refs = set(t["support"])
        selected = set(row["selected"])
        if t["unanswerable"]:
            group = "unanswerable"
        elif refs <= selected:
            group = "publisher_support_all_retrieved"
        elif refs & selected:
            group = "publisher_support_partially_retrieved"
        else:
            group = "publisher_support_missing"
        labels = {e["label"] for e in row["receipt"]["delivered_evidence"]}
        cited = MARKER.findall(row["answer"])
        if any(mark[1:-1] not in labels for mark in cited):
            raise ValueError("unoriginal citation label in real answer")
        byarm[row["arm"]].append(
            dict(
                question_id=row["question_id"],
                family_proxy_digest=questions[row["question_id"]][
                    "family_proxy_digest"
                ],
                f1=answer_f1(row["answer"], t),
                unanswerable=t["unanswerable"],
                group=group,
                publisher_support_count=len(refs),
                prompt_tokens=row["receipt"]["input_tokens"],
                valid_label_count=len(cited),
                refusal_shape=refusal_shape(row["answer"])
                if t["unanswerable"]
                else None,
            )
        )
    if set(byarm) != set(ARMS) or any(len(v) != 16 for v in byarm.values()):
        raise ValueError("original 16-by-2 answered population differs")
    arm_reports = {}
    for arm in ARMS:
        records = byarm[arm]
        official = hosted_score["arms"][arm]
        total = _rollup(records)
        if (
            not math.isclose(total["mean_f1"], official["diagnostic_f1"], abs_tol=1e-12)
            or total["prompt_tokens"] != official["actual_input_tokens"]
            or official["succeeded"] != 16
            or official["failed"] != 0
        ):
            raise ValueError("rescore differs from hosted original reference score")
        groups = {
            name: _rollup([r for r in records if r["group"] == name])
            for name in (
                "publisher_support_all_retrieved",
                "publisher_support_partially_retrieved",
                "publisher_support_missing",
                "unanswerable",
            )
        }
        unans = [r for r in records if r["unanswerable"]]
        arm_reports[arm] = dict(
            original_official=_rollup(records),
            original_hosted_f1=official["diagnostic_f1"],
            cohorts=groups,
            refusal_strict_exact=sum(
                r["refusal_shape"] == "strict_exact" for r in unans
            ),
            refusal_prefix_with_extra_unreviewed_content=sum(
                r["refusal_shape"] == "canonical_prefix_plus_unreviewed_content"
                for r in unans
            ),
            refusal_not_canonical=sum(
                r["refusal_shape"] == "not_canonical_refusal" for r in unans
            ),
            diagnostic_prefix_refusal_macro_f1=(
                sum(r["f1"] for r in records if not r["unanswerable"])
                + sum(
                    r["refusal_shape"]
                    in ("strict_exact", "canonical_prefix_plus_unreviewed_content")
                    for r in unans
                )
            )
            / 16,
        )
    first = {r["question_id"]: r for r in byarm["lexical_k4"]}
    second = {r["question_id"]: r for r in byarm["lexical_k8"]}
    if set(first) != set(second):
        raise ValueError("original paired question census mismatch")
    groups = defaultdict(list)
    for qid in first:
        a, b = first[qid], second[qid]
        if a["unanswerable"] != b["unanswerable"]:
            raise ValueError("paired target changed")
        cohort = (
            "unanswerable"
            if a["unanswerable"]
            else (
                "support_retrieved_by_both"
                if a["group"] == "publisher_support_all_retrieved"
                else "additional_support_retrieved_by_k8"
                if b["group"] == "publisher_support_all_retrieved"
                else "support_missing_both"
            )
        )
        groups[cohort].append(
            dict(
                qid=qid,
                delta=b["f1"] - a["f1"],
                tokens=b["prompt_tokens"] - a["prompt_tokens"],
            )
        )
    paired = {}
    for name in (
        "unanswerable",
        "support_retrieved_by_both",
        "additional_support_retrieved_by_k8",
        "support_missing_both",
    ):
        items = groups[name]
        paired[name] = dict(
            questions=len(items),
            mean_original_delta=sum(x["delta"] for x in items) / len(items)
            if items
            else None,
            sum_original_delta=sum(x["delta"] for x in items),
            extra_prompt_tokens=sum(x["tokens"] for x in items),
        )
    orig_delta = (
        arm_reports["lexical_k8"]["original_official"]["f1_sum"]
        - arm_reports["lexical_k4"]["original_official"]["f1_sum"]
    ) / 16
    prefix_delta = (
        arm_reports["lexical_k8"]["diagnostic_prefix_refusal_macro_f1"]
        - arm_reports["lexical_k4"]["diagnostic_prefix_refusal_macro_f1"]
    )
    if not math.isclose(
        orig_delta, hosted_score["paired"]["observed_mean_f1_delta"], abs_tol=1e-12
    ):
        raise ValueError("the original preregistered paired effect changed")
    if not math.isclose(
        orig_delta,
        sum(r["sum_original_delta"] for r in paired.values()) / 16,
        abs_tol=1e-12,
    ):
        raise ValueError("missing paired effect components")
    return dict(
        schema=PROFILE,
        generating_commit=GENERATING_COMMIT,
        originals={k: EXPECTED_ZIPS[k] for k in EXPECTED_ZIPS},
        original_model_runs=32,
        question_count=16,
        source_family_proxies=2,
        publisher_annotation_is_not_human_certified_sufficient=True,
        official_scoring_preserved=True,
        by_arm=arm_reports,
        paired_support_cohorts=paired,
        exact_registered_k8_minus_k4_f1=orig_delta,
        sensitivity_prefix_refusal_k8_minus_k4_f1=prefix_delta,
        sensitivity_has_no_human_semantic_validation=True,
        independent_future_families=0,
        semantic_citation_precision=None,
        retrieval_policy_promotion_qualified=False,
        parameter_memory_qualified=False,
        production_accepted=False,
    )


def audit(artifacts):
    questions, _docs, _decisions, originals, targets, report = _originals(artifacts)
    return compute(questions, originals, targets, report)


def stable_wire_numbers(value):
    """Only serialization quantizes numeric output after exact original checks.

    Saved CPython 3.11 / 3.12 aggregate sums can differ by one floating ULP.
    The mathematical comparisons against the hosted metric occur *before*
    this twelve-decimal display normalization. Booleans are never numbers.
    """
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("nonfinite metric would enter exported report")
        return round(value, 12)
    if type(value) is dict:
        return {key: stable_wire_numbers(part) for key, part in value.items()}
    if type(value) is list:
        return [stable_wire_numbers(part) for part in value]
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in EXPECTED_ZIPS:
        parser.add_argument(name, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = stable_wire_numbers(
        audit({name: getattr(args, name) for name in EXPECTED_ZIPS})
    )
    with args.out.open("x", encoding="utf-8") as f:
        json.dump(
            result, f, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
        )
        f.write("\n")
    print(
        json.dumps(
            {
                "original_qa_f1_delta": result["exact_registered_k8_minus_k4_f1"],
                "posthoc_prefix_refusal_delta": result[
                    "sensitivity_prefix_refusal_k8_minus_k4_f1"
                ],
                "production_accepted": False,
            },
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
