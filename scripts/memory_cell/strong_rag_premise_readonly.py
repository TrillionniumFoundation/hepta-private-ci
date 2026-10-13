"""Independent, standard-library replay of 64 pinned real Qwen citation-prompt outputs.

Checks source and model artifact bytes, original evidence, unedited answers,
procedure outcomes, formal citation chains and paired costs. No model weights,
training, target access by a reader, semantic judgement or promotion authority.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

SCHEMA = "hepta.memory-cell.premise-prompt-original-replay.v1"
SOURCE_SHA = "fd7e19ccc7bee86afe6bf49f3eab9a75fc1badd9"
MODEL_SHA = "6743f0e054b44eea6a7e1eadf7e27651ced94df7885b95e6da81fd82a3075cff"
INPUT_SHA = "23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b"
PLAN_SHA = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
READER_ID = "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"
CONDITIONS = ("hybrid", "organized", "program_support", "without_prerequisite")
STYLES = ("original", "premise_chain")
IDENTIFIER = re.compile(r"\s*((?:site|mode)_[0-9a-f]{8})(?:\s*\[E[1-9][0-9]*\])*\s*\.?\s*", re.ASCII)
LABEL = re.compile(r"\[E([1-9][0-9]*)\]", re.ASCII)
CITATION_LIKE = re.compile(r"\[E[^\]\s]*\]")
TRUNCATED = re.compile(r"^\s*(?:site_|mode_)(?:\s|\[E|$)")
SCORER_FIELDS = {
    "parsed_identifier", "strict_task_success", "required_delivered",
    "required_source_count", "required_delivered_but_uncited", "required_undelivered",
    "unbound_label_occurrences", "malformed_citation_markers",
    "cited_not_program_declared", "required_premise_labels_covered",
    "complete_citation_chain", "exact_formal_support_chain",
    "formal_requirements_are_not_human_verified", "strict_success_and_complete_chain",
    "procedure_verification", "postrun_failure_retained",
}


def hashbytes(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return hashbytes(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())


def strict_json(raw):
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    def reject(value):
        raise ValueError("nonfinite JSON number: " + str(value))

    return json.loads(raw, object_pairs_hook=unique, parse_constant=reject)


def opened(path, expected, *, max_size=16_000_000, max_members=200):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_size:
        raise ValueError("bounded regular immutable ZIP required")
    raw = path.read_bytes()
    if hashbytes(raw) != expected:
        raise ValueError("original outer ZIP SHA256 pin mismatch")
    with zipfile.ZipFile(path) as source:
        records = source.infolist()
        if not 1 < len(records) <= max_members:
            raise ValueError("unexpected archived file census")
        names = set()
        for item in records:
            name = item.filename
            parts = PurePosixPath(name)
            if (
                not name or name in names or parts.is_absolute()
                or ".." in parts.parts or "\\" in name or item.is_dir()
                or stat.S_ISLNK(item.external_attr >> 16)
                or item.file_size > 8_000_000
            ):
                raise ValueError("unsafe or duplicated archive entry")
            names.add(name)
        if sum(i.file_size for i in records) > 32_000_000 or "SHA256SUMS" not in names:
            raise ValueError("archive size/manifest bound")
        manifest = source.read("SHA256SUMS").decode().splitlines()
        declared = set()
        for entry in manifest:
            m = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", entry)
            if m is None:
                raise ValueError("bad checksum record")
            h, name = m.groups()
            if name in declared or name == "SHA256SUMS" or name not in names:
                raise ValueError("archive manifest census changed")
            declared.add(name)
            if hashbytes(source.read(name)) != h:
                raise ValueError("manifest file hash mismatch")
        if declared != names - {"SHA256SUMS"}:
            raise ValueError("unlisted or missing artifact member")
        return {name: source.read(name) for name in names}


def jsonfile(files, name):
    if name not in files:
        raise ValueError("missing required archived source file: " + name)
    return strict_json(files[name].decode("utf-8"))


def procedure_outcome(recipe, identifier):
    if type(recipe) is not dict or set(recipe) != {"modes", "target", "values"}:
        raise ValueError("invalid fixed procedure recipe")
    method = recipe["modes"].get(identifier)
    if method not in ("sort", "reverse", None):
        raise ValueError("unregistered program worker mode")
    sequence = recipe["values"]
    observed = sorted(sequence) if method == "sort" else list(reversed(sequence)) if method == "reverse" else None
    return observed is not None and observed == recipe["target"], observed


def check(raw, saved, case, truth, originals, identity):
    if {k: v for k, v in saved.items() if k not in SCORER_FIELDS} != raw:
        raise ValueError("scorer modified or dropped original model answer")
    if raw["status"] != "succeeded" or raw["kind"] != truth["kind"] or raw["kind"] != case["kind"]:
        raise ValueError("original model attempt incomplete or kind drift")
    condition, style = raw["condition"], raw["style"]
    selected = case["controls"][condition]["selected"]
    if raw["selected"] != selected or raw["candidate_digest"] != case["candidate_digest"]:
        raise ValueError("frozen selection differs from original plan")
    receipt = raw["receipt"]
    if (
        receipt["reader_identity"] != identity or receipt["token_limit"] != 2048
        or receipt["trainable_parameters"] != 0 or receipt["answer_postprocessed"] is not False
        or receipt["production_accepted"] is not False
        or receipt["independent_semantic_review"] is not False
        or type(receipt["input_tokens"]) is not int or not 0 < receipt["input_tokens"] <= 2048
        or type(receipt["generated_tokens"]) is not int or not 0 < receipt["generated_tokens"] <= 64
        or not math.isfinite(receipt["seconds"]) or receipt["seconds"] < 0
        or receipt["query_digest"] != digest(case["query"])
    ):
        raise ValueError("reader, prompt, resource or training drift")
    if style not in STYLES or condition not in CONDITIONS:
        raise ValueError("unregistered condition or prompt style")
    supplied = receipt["delivered_evidence"]
    if [s["original_id"] for s in supplied] != selected:
        raise ValueError("actual delivered source list differs")
    labelmap = {}
    for i, source in enumerate(supplied, 1):
        doc = originals.get(source["original_id"])
        if doc is None or source["label"] != f"E{i}" or source["label"] in labelmap:
            raise ValueError("non-canonical or fabricated source label")
        if (
            source["excerpt"] != doc["content"]
            or source["scope"] != doc["scope"]
            or source["root"] != doc["root"]
            or source["observed_at"] != doc["observed_at"]
            or source["source_start"] != 0
            or source["source_end"] != len(doc["content"].encode())
            or source["source_digest"] != digest(doc["content"])
            or doc["scope"] != case["query"]["scope"]
        ):
            raise ValueError("model received altered source bytes")
        labelmap[source["label"]] = doc["identity"]
    audit = raw["citation_audit"]
    req = audit["request"]
    if (
        req["query_id"] != raw["question_id"] or req["scope"] != case["query"]["scope"]
        or req["question"] != case["query"]["content"]
        or req["question_time"] != case["query"]["observed_at"]
        or req["answer"] != raw["answer"]
        or req["prompt_digest"] != receipt["input_ids_digest"]
        or [s["label"] for s in req["sources"]] != list(labelmap)
        or [s["excerpt"] for s in req["sources"]] != [s["excerpt"] for s in supplied]
        or audit["judgement"] is not None or audit["production_accepted"] is not False
    ):
        raise ValueError("original citation request changed")
    answer = raw["answer"]
    marker_strings = ["E" + token for token in LABEL.findall(answer)]
    malformed = [m for m in CITATION_LIKE.findall(answer) if LABEL.fullmatch(m) is None]
    unbound = [m for m in marker_strings if m not in labelmap]
    cited = {labelmap[m] for m in marker_strings if m in labelmap}
    required = set(truth["support"])
    identifier_match = IDENTIFIER.fullmatch(answer)
    identifier = identifier_match.group(1) if identifier_match else None
    good = identifier == truth["expected"]
    if truth["kind"] == "procedure":
        good, result = procedure_outcome(truth["procedure"], identifier)
        archived = saved["procedure_verification"]
        if (
            archived["exit_code"] != (0 if good else 2)
            or archived["request"]["supplied"] != (identifier or "invalid_response")
            or strict_json(archived["stdout"])["actual_output"] != result
        ):
            raise ValueError("actual procedure output differs from original worker")
    scored_fields = {
        "parsed_identifier": identifier, "strict_task_success": good,
        "required_delivered": required <= set(selected),
        "required_source_count": len(required),
        "required_delivered_but_uncited": sorted((required & set(selected)) - cited),
        "required_undelivered": sorted(required - set(selected)),
        "unbound_label_occurrences": unbound,
        "malformed_citation_markers": malformed,
        "cited_not_program_declared": sorted(cited - required),
        "required_premise_labels_covered": required <= cited,
        "complete_citation_chain": required <= cited and not unbound and not malformed,
        "exact_formal_support_chain": cited == required and not unbound and not malformed,
        "formal_requirements_are_not_human_verified": True,
    }
    scored_fields["strict_success_and_complete_chain"] = good and scored_fields["complete_citation_chain"]
    for key, value in scored_fields.items():
        if saved[key] != value:
            raise ValueError("saved claim fails independent original answer replay: " + key)
    return {"correct": good, "complete": scored_fields["strict_success_and_complete_chain"],
            "exact": good and scored_fields["exact_formal_support_chain"],
            "input_tokens": receipt["input_tokens"], "output_tokens": receipt["generated_tokens"],
            "truncated_identifier": bool(TRUNCATED.search(answer)), "answer_changed": answer}


def replay(actual_zip, source_zip):
    model = opened(actual_zip, MODEL_SHA)
    original = opened(source_zip, INPUT_SHA)
    if model["tested-commit.txt"].decode().strip() != SOURCE_SHA:
        raise ValueError("generating source commit changed")
    if hashbytes(original["plan/plan.json"]) != PLAN_SHA:
        raise ValueError("original frozen plan pin mismatch")
    plan = jsonfile(original, "plan/plan.json")
    labels = jsonfile(original, "observations/labels.json")
    docs = jsonfile(original, "plan/source-view.json")
    execution = jsonfile(model, "evaluation/execution.json")
    report = jsonfile(model, "evaluation/report.json")
    inventory = jsonfile(model, "inventory.json")
    if (
        execution["generating_source"] != SOURCE_SHA
        or execution["exact_plan_sha256"] != PLAN_SHA
        or execution["exact_reader_inventory"] != READER_ID
        or tuple(execution["conditions"]) != CONDITIONS
        or tuple(execution["styles"]) != STYLES
        or inventory["inventory_digest"] != READER_ID
        or execution["training_steps"] != 0
        or execution["source_annotations_never_placed_in_prompt"] is not True
        or report["production_accepted"] is not False
    ):
        raise ValueError("experiment/model identities or no-training contract changed")
    cases = {case["query"]["identity"]: case for case in plan["cases"]}
    targets = {t["id"]: t for t in labels if t["phase"] == "test"}
    originals = {d["identity"]: d for d in docs}
    if len(cases) != 8 or len(targets) != 8 or set(targets) != set(cases) or len(originals) != len(docs):
        raise ValueError("original plan/question/source census drift")
    rawbytes = model["evaluation/raw-answers.jsonl"]
    raw = [strict_json(line) for line in rawbytes.splitlines()]
    scored = jsonfile(model, "evaluation/scored-answers.json")
    expected = {(qid, condition, style) for qid in cases for condition in CONDITIONS for style in STYLES}
    keys = [(r["question_id"], r["condition"], r["style"]) for r in raw]
    if len(raw) != len(scored) or len(raw) != 64 or set(keys) != expected or len(keys) != len(set(keys)):
        raise ValueError("64 original complete paired generation census changed")
    by_pair = defaultdict(dict)
    for r, s in zip(raw, scored, strict=True):
        key = (r["question_id"], r["condition"], r["style"])
        entry = check(r, s, cases[key[0]], targets[key[0]], originals, READER_ID)
        by_pair[(key[0], key[1])][key[2]] = (r, entry)
    output = {}
    for condition in CONDITIONS:
        paired = [x for key, x in by_pair.items() if key[1] == condition]
        if len(paired) != 8:
            raise ValueError("missing condition pair")
        count = Counter()
        input_totals = Counter()
        output_totals = Counter()
        kinds = Counter()
        for row in paired:
            a, ax = row["original"]
            b, bx = row["premise_chain"]
            if (
                a["selected"] != b["selected"]
                or a["receipt"]["delivered_evidence"] != b["receipt"]["delivered_evidence"]
                or a["receipt"]["derived_evidence"] != b["receipt"]["derived_evidence"]
                or a["receipt"]["reader_identity"] != b["receipt"]["reader_identity"]
                or a["receipt"]["input_ids_digest"] == b["receipt"]["input_ids_digest"]
            ):
                raise ValueError("not a matched evidence-only prompt intervention")
            for style, result in (("original", ax), ("premise_chain", bx)):
                count[style + "_correct"] += result["correct"]
                count[style + "_complete_chain"] += result["complete"]
                count[style + "_exact_chain"] += result["exact"]
                count[style + "_truncated_identifier"] += result["truncated_identifier"]
                input_totals[style] += result["input_tokens"]
                output_totals[style] += result["output_tokens"]
            count["task_wins"] += not ax["correct"] and bx["correct"]
            count["task_losses"] += ax["correct"] and not bx["correct"]
            count["changed_outputs"] += a["answer"] != b["answer"]
            kinds[a["kind"] + "_planned"] += 1
            kinds[a["kind"] + "_losses"] += ax["correct"] and not bx["correct"]
        actual = {
            "question_pairs": len(paired),
            **{k: count[k] for k in (
                "original_correct", "premise_chain_correct", "original_complete_chain",
                "premise_chain_complete_chain", "original_exact_chain", "premise_chain_exact_chain",
                "original_truncated_identifier", "premise_chain_truncated_identifier", "task_wins",
                "task_losses", "changed_outputs")},
            "input_tokens": dict(input_totals),
            "generated_tokens": dict(output_totals),
            "by_task_kind": dict(sorted(kinds.items())),
        }
        source_report = report["by_condition"][condition]
        if any((source_report[key] != actual[new]) for key, new in (
            ("original_strict_correct", "original_correct"),
            ("premise_prompt_strict_correct", "premise_chain_correct"),
            ("original_strict_and_complete_formal_chain", "original_complete_chain"),
            ("premise_prompt_strict_and_complete_formal_chain", "premise_chain_complete_chain"),
            ("original_strict_and_exact_formal_chain", "original_exact_chain"),
            ("premise_prompt_strict_and_exact_formal_chain", "premise_chain_exact_chain"),
            ("task_wins", "task_wins"), ("task_losses", "task_losses"),
            ("changed_raw_answers", "changed_outputs"),
        )):
            raise ValueError("archived paired result summary differs from independent reconstruction")
        output[condition] = actual
    if report["planned_model_attempts"] != 64 or report["successful_model_generations"] != 64:
        raise ValueError("reported original model call census changed")
    return {
        "schema": SCHEMA,
        "source_run_id": 38385138211,
        "generating_commit": SOURCE_SHA,
        "original_model_zip_sha256": MODEL_SHA,
        "original_frozen_input_zip_sha256": INPUT_SHA,
        "model_identity": READER_ID,
        "frozen_plan_sha256": PLAN_SHA,
        "actual_model_generations": len(raw),
        "matched_question_condition_pairs": len(by_pair),
        "conditions": output,
        "provenance": "original model answers, byte-pinned sources, independently replayed task/citation counters",
        "annotation_privileged_controls_not_deployable": True,
        "prompt_training_performed": False,
        "independent_semantic_entailment": False,
        "independent_future_source_families": 0,
        "prompt_promotion_qualified": False,
        "parametric_memory_training_qualified": False,
        "production_accepted": False,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("model_zip", type=Path)
    ap.add_argument("original_zip", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    result = replay(args.model_zip, args.original_zip)
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(result, out, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        out.write("\n")
    print(json.dumps({"verified_original_model_generations": result["actual_model_generations"], "disposition": "NO-GO"}))


if __name__ == "__main__":
    main()
