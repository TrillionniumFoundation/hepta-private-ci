"""Independently replay 72 original Qwen replies' delivered-vs-cited sources.

No model inference, no rewriting of generated text, no gold answers in prompts.
The necessary-source set is the ORIGINAL program-authored privileged control,
NOT human-verified causal sufficiency or an online-retrieval policy.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

ORIGINAL_MODEL_ZIP_SHA256 = (
    "7a99db30fb5b1202fcd43073d22589b84315046dd34044277cc46351f1cbece8"
)
ORIGINAL_MODEL_COMMIT = "6304b451268c73f3d1a605985226b102df841bbf"
ARMS = (
    "selected_k",
    "hybrid_k4",
    "hybrid_k6",
    "hybrid_k4_reversed",
    "single_hop",
    "entity_time",
    "organized",
    "program_support",
    "empty",
)
KINDS = ("new_fact", "correction", "composition", "procedure")
MARKER = re.compile(r"\[E([1-9][0-9]*)\]")
HEX = re.compile(r"[0-9a-f]{64}")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def _unique_object(pairs):
    output = {}
    for key, value in pairs:
        require(key not in output, "duplicate original JSON member")
        output[key] = value
    return output


def _reject_constant(value):
    raise ValueError("invalid nonfinite JSON number: " + value)


def _json(value):
    return json.loads(
        value, object_pairs_hook=_unique_object, parse_constant=_reject_constant
    )


def _source_map(raw):
    receipt = raw["receipt"]
    items = receipt["delivered_evidence"]
    require(
        isinstance(items, list) and len(items) <= 8,
        "Reader evidence cardinality is unbound",
    )
    labels, originals = {}, []
    for row in items:
        label, source = row["label"], row["original_id"]
        require(
            isinstance(label, str)
            and re.fullmatch(r"E[1-9][0-9]*", label)
            and label not in labels
            and isinstance(source, str)
            and source,
            "ambiguous or invalid Reader evidence labels",
        )
        labels[label] = source
        originals.append(source)
    require(
        len(set(originals)) == len(originals), "duplicate delivered original source"
    )
    require(
        originals == raw["selected"],
        "original selected and delivered source order differ",
    )
    require(
        receipt["semantic_citation_precision"] is None
        and receipt["answer_postprocessed"] is False
        and receipt["production_accepted"] is False
        and receipt["trainable_parameters"] == 0,
        "frozen original Reader evidence mutated or promoted",
    )
    return labels


def _one(raw, formal, required):
    require(
        raw["question_id"] == formal["question_id"]
        and raw["arm"] == formal["arm"]
        and raw["kind"] == formal["kind"]
        and raw["answer"] == formal["answer"]
        and raw["status"] == formal["generation_status"] == "succeeded",
        "mismatched raw answer and postrun official record",
    )
    require(
        type(formal["strict_task_success"]) is bool, "unbound original task success"
    )
    labels = _source_map(raw)
    markers = MARKER.findall(raw["answer"])
    all_cited = [labels.get("E" + m) for m in markers]
    unbound_labels = ["E" + m for m, src in zip(markers, all_cited) if src is None]
    cited = {s for s in all_cited if s is not None}
    need = set(required)
    delivered = set(labels.values())
    require(
        len(need) == len(required)
        and 1 <= len(need) <= 2
        and all(isinstance(s, str) and s for s in need),
        "unbound original program-declared necessary sources",
    )
    require(
        set(formal["cited_source_ids"]) == cited
        and set(formal["missing_program_declared_support"]) == need - cited
        and formal["program_declared_support_cited"] is (need <= cited),
        "official citations disagree with actual generated marker mapping",
    )
    undelivered = sorted(need - delivered)
    delivered_uncited = sorted((need & delivered) - cited)
    if undelivered and delivered_uncited:
        shortfall = "both-undelivered-and-uncited"
    elif undelivered:
        shortfall = "necessary-source-not-delivered"
    elif delivered_uncited:
        shortfall = "delivered-source-not-cited"
    else:
        shortfall = "no-program-declared-chain-gap"
    return dict(
        question_id=raw["question_id"],
        kind=raw["kind"],
        arm=raw["arm"],
        strict_task_success=formal["strict_task_success"],
        required_source_count=len(need),
        actually_delivered_required_sources=len(need & delivered),
        actually_cited_required_sources=len(need & cited),
        required_undelivered_source_ids=undelivered,
        required_delivered_but_uncited_source_ids=delivered_uncited,
        unbound_output_labels=unbound_labels,
        shortfall=shortfall,
        answer_sha256=hashlib.sha256(raw["answer"].encode()).hexdigest(),
        actual_request_input_digest=raw["receipt"]["input_ids_digest"],
        independent_semantic_entailment_review=False,
    )


def reconcile(raw, report):
    """Compute a transport-vs-citation census from original saved model bytes."""
    require(
        len(raw) == len(report["formal_citation_chain"]["cases"]) == 72,
        "72 original Reader outputs and reports required",
    )
    by_key, by_question = {}, defaultdict(list)
    for item in raw:
        key = (item["question_id"], item["arm"])
        require(
            item["arm"] in ARMS and item["kind"] in KINDS and key not in by_key,
            "duplicate, unknown or malformed original arm",
        )
        by_key[key] = item
        by_question[item["question_id"]].append(item)
    require(
        len(by_question) == 8
        and all(
            len(group) == len(ARMS) and len({x["kind"] for x in group}) == 1
            for group in by_question.values()
        )
        and Counter(next(iter(group))["kind"] for group in by_question.values())
        == {k: 2 for k in KINDS},
        "missing original 8 questions x 9 arms / 4 task kinds",
    )
    require(
        all({x["arm"] for x in group} == set(ARMS) for group in by_question.values()),
        "missing Reader arm",
    )
    controls = {}
    for qid, rows in by_question.items():
        control = next(row for row in rows if row["arm"] == "program_support")
        support = control["selected"]
        require(isinstance(support, list), "no pinned privileged source program")
        controls[qid] = support
    formals = {}
    for row in report["formal_citation_chain"]["cases"]:
        key = (row["question_id"], row["arm"])
        require(
            key not in formals and key in by_key,
            "duplicate/unregistered formal citation annotation",
        )
        formals[key] = row
    require(set(by_key) == set(formals), "missing official original citation record")
    rows = [
        _one(rawrow, formals[key], controls[key[0]])
        for key, rawrow in sorted(by_key.items())
    ]
    by_arm = {}
    for arm in ARMS:
        arm_rows = [row for row in rows if row["arm"] == arm]
        correct = [row for row in arm_rows if row["strict_task_success"]]
        full = sum(x["shortfall"] == "no-program-declared-chain-gap" for x in correct)
        source_missing = sum(
            bool(x["required_undelivered_source_ids"]) for x in correct
        )
        omitted_citation = sum(
            bool(x["required_delivered_but_uncited_source_ids"]) for x in correct
        )
        official = report["formal_citation_chain"]["by_arm"][arm]
        require(
            official["attempted"] == len(arm_rows) == 8
            and official["strict_task_success"] == len(correct)
            and official["correct_with_full_program_declared_citations"] == full,
            "official original per-arm score differs from raw evidence replay",
        )
        by_arm[arm] = dict(
            planned=8,
            strict_correct=len(correct),
            correct_with_full_declared_chain=full,
            correct_but_missing_source_delivery=source_missing,
            correct_but_missing_delivered_citation=omitted_citation,
        )
    ablation = [row for row in rows if row["arm"] == "program_support"]
    multihop = [row for row in ablation if row["kind"] in ("composition", "procedure")]
    require(len(multihop) == 4, "four original multi-step Reader cases required")
    result = dict(
        schema="hepta.memory-cell.original-reader-delivery-vs-citation.v1",
        pinned_model_commit=ORIGINAL_MODEL_COMMIT,
        original_total_model_calls=72,
        scoped_original_qwen_reader=True,
        provenance="original archived model outputs; no new generation or model inference",
        program_defined_support_privileged=True,
        program_support_multistep=dict(
            actual_cases=len(multihop),
            strictly_correct_answers=sum(x["strict_task_success"] for x in multihop),
            both_declared_sources_delivered=sum(
                x["actually_delivered_required_sources"] == 2 for x in multihop
            ),
            full_declared_chain_cited=sum(
                x["strict_task_success"]
                and x["shortfall"] == "no-program-declared-chain-gap"
                for x in multihop
            ),
            complete_delivery_but_incomplete_citation=sum(
                x["strict_task_success"]
                and x["actually_delivered_required_sources"] == 2
                and bool(x["required_delivered_but_uncited_source_ids"])
                for x in multihop
            ),
        ),
        by_arm=by_arm,
        original_rows=rows,
        independent_semantic_citation_precision=None,
        parametric_memory_gain_demonstrated=False,
        independent_source_family_count=0,
        production_accepted=False,
    )
    return result


def audit_archive(path: Path):
    require(
        path.is_file()
        and not path.is_symlink()
        and 0 < path.stat().st_size <= 32 * 1024 * 1024,
        "bounded regular historical ZIP required",
    )
    verifier = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            verifier.update(block)
    actual = verifier.hexdigest()
    require(
        actual == ORIGINAL_MODEL_ZIP_SHA256, "original model transport SHA256 differs"
    )
    with zipfile.ZipFile(path) as z:
        entries = z.infolist()
        require(
            0 < len(entries) <= 256
            and sum(x.file_size for x in entries) <= 64 * 1024 * 1024,
            "bounded original archive census required",
        )
        seen = set()
        for info in entries:
            name = info.filename
            p = PurePosixPath(name)
            require(
                name not in seen
                and not p.is_absolute()
                and ".." not in p.parts
                and "\\" not in name
                and ":" not in name
                and stat.S_IFMT(info.external_attr >> 16)
                in (0, stat.S_IFREG, stat.S_IFDIR)
                and not (info.flag_bits & 1),
                "unsafe/duplicated/encrypted original ZIP member",
            )
            seen.add(name)
        manifests = z.read("SHA256SUMS").decode()
        pins = {}
        for line in manifests.splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  \./(.+)", line)
            require(match is not None, "original SHA256SUMS format differs")
            digest, name = match.groups()
            require(name not in pins, "duplicate pinned original archive member")
            pins[name] = digest
        require(
            set(pins) == seen - {"SHA256SUMS"},
            "missing or extra original archive member",
        )
        for name, pin in pins.items():
            require(
                hashlib.sha256(z.read(name)).hexdigest() == pin,
                "original archive member SHA256 mismatch",
            )
        require(
            z.read("tested-commit.txt").decode().strip() == ORIGINAL_MODEL_COMMIT,
            "generating original model SHA changed",
        )
        rawbytes = z.read("evaluation/raw-answers.jsonl")
        report = _json(z.read("evaluation/report.json"))
        require(
            hashlib.sha256(rawbytes).hexdigest() == report["raw_answers_sha256"],
            "original model raw answer byte pin differs",
        )
        raw = [_json(row) for row in rawbytes.splitlines()]
        result = reconcile(raw, report)
        result["source_archive_sha256"] = actual
        result["manifest_member_count"] = len(pins)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-model-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_archive(args.original_model_zip)
    with args.output.open("x", encoding="utf-8") as fp:
        json.dump(
            result, fp, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2
        )
        fp.write("\n")
    print(
        json.dumps(
            {
                "schema": result["schema"],
                "original_calls": result["original_total_model_calls"],
                "program_support_multistep": result["program_support_multistep"],
                "model_source_sha256": result["source_archive_sha256"],
                "production_accepted": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
