"""Read-only diagnosis of literal-answer and strict-grammar failures.

A gold identifier appearing in text is NOT counted as an answer success.
Original trained-model responses, sources, metrics and decisions are immutable.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

SOURCE_SHA = "23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b"
MODELS = {
    "qwen-3b": "831ce9658bafcbaf04f4a15879982e58317322f7cd5137724498d7d20df7bb98",
    "smol-1.7b": "67d46247bd1881c8fb3f73ec6122415d0d15a0ec24b02f193fb1294e7ea63bae",
}
GENERATING_SOURCE = "59f9eadd5cc919359079e04442f7343838a60057"
PLAN_SHA = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
ARMS = (
    "empty",
    "hybrid",
    "entity_time",
    "organized",
    "program_support",
    "without_prerequisite",
)
IDENTIFIER = re.compile(
    r"(?<![A-Za-z0-9_-])(?:site|mode)_[A-Za-z0-9_-]+(?![A-Za-z0-9_-])"
)


def sealed_zip(path, pin):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > 32_000_000:
        raise ValueError("archive size or symlink")
    if hashlib.sha256(path.read_bytes()).hexdigest() != pin:
        raise ValueError("wrong immutable archive")
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if len(members) > 256 or sum(x.file_size for x in members) > 64_000_000:
            raise ValueError("unbounded inner archive")
        by_name = {}
        for member in members:
            name = PurePosixPath(member.filename)
            if (
                str(name) != member.filename
                or name.is_absolute()
                or ".." in name.parts
                or member.is_dir()
                or stat.S_ISLNK(member.external_attr >> 16)
                or member.filename in by_name
            ):
                raise ValueError("invalid inner archive member")
            by_name[member.filename] = archive.read(member)
        if "SHA256SUMS" not in by_name:
            raise ValueError("missing inner manifest")
        manifest = {}
        for line in by_name["SHA256SUMS"].decode().splitlines():
            hit = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
            if hit is None:
                raise ValueError("invalid manifest entry")
            wanted, name = hit.groups()
            if name in manifest or name not in by_name:
                raise ValueError("duplicate or unknown manifest member")
            manifest[name] = wanted
            if hashlib.sha256(by_name[name]).hexdigest() != wanted:
                raise ValueError("tampered manifest member")
        if set(manifest) != set(by_name) - {"SHA256SUMS"}:
            raise ValueError("incomplete manifest")
        return by_name


def classify(row, gold):
    """A secondary *description* of output, never a change to strict scoring."""
    if row["status"] == "failed":
        return "unobserved_generation"
    if row["status"] != "succeeded" or type(row.get("strict_task_success")) is not bool:
        raise ValueError("invalid or missing original model outcome")
    if row["strict_task_success"]:
        return "strict_correct"
    answer = row["answer"]
    tokens = IDENTIFIER.findall(answer)
    if not tokens:
        return (
            "explicit_abstention"
            if answer.strip() == "I do not have enough evidence."
            else "no_identifier"
        )
    if len(tokens) == 1 and tokens[0] == gold:
        return (
            "gold_literal_with_failed_procedure"
            if row.get("parsed_identifier") == gold
            else "gold_literal_without_strict_grammar"
        )
    if len(tokens) == 1:
        return "wrong_identifier"
    return "multiple_identifiers_unadjudicated"


def diagnose(original_zip, qwen_zip, smol_zip):
    original = sealed_zip(original_zip, SOURCE_SHA)
    if hashlib.sha256(original["plan/plan.json"]).hexdigest() != PLAN_SHA:
        raise ValueError("frozen original plan changed")
    truth = json.loads(original["observations/labels.json"])
    expected = {r["id"]: r for r in truth if r["phase"] == "test"}
    if len(expected) != 8 or len({r["id"] for r in truth}) != 16:
        raise ValueError("wrong fixed authored census")
    output = {}
    for model, path in (("qwen-3b", qwen_zip), ("smol-1.7b", smol_zip)):
        files = sealed_zip(path, MODELS[model])
        if files["tested-commit.txt"].decode().strip() != GENERATING_SOURCE:
            raise ValueError("generation source drift")
        raw = [json.loads(line) for line in files["run/raw-answers.jsonl"].splitlines()]
        scored = json.loads(files["run/scored-answers.json"])
        if (
            len(raw) != len(scored)
            or len(raw) != len(expected) * len(ARMS)
            or {(r["question_id"], r["arm"]) for r in raw}
            != {(qid, arm) for qid in expected for arm in ARMS}
        ):
            raise ValueError("incomplete original answer census")
        counts = {arm: Counter() for arm in ARMS}
        cases = []
        for original_row, row in zip(raw, scored, strict=True):
            if any(row.get(k) != v for k, v in original_row.items()):
                raise ValueError("scorer altered pretrained output")
            qid, arm = row["question_id"], row["arm"]
            if row["kind"] != expected[qid]["kind"]:
                raise ValueError("task kind drift")
            kind = classify(row, expected[qid]["expected"])
            counts[arm][kind] += 1
            cases.append(
                dict(
                    question_id=qid,
                    task_kind=row["kind"],
                    arm=arm,
                    original_answer=row.get("answer"),
                    failure_class=kind,
                    strict_success=row.get("strict_task_success"),
                    annotated_support_covered=row.get("required_sources_covered"),
                )
            )
        output[model] = dict(
            generation_commit=GENERATING_SOURCE,
            planned=len(raw),
            by_arm={a: dict(sorted(counts[a].items())) for a in ARMS},
            cases=cases,
        )
    return dict(
        schema="hepta.memory-cell.reader-surface-failures.v1",
        source_plan_sha256=PLAN_SHA,
        historical_source_sha=GENERATING_SOURCE,
        independently_sampled=False,
        new_model_generations=0,
        label_derived_diagnostic_only=True,
        modifies_primary_task_score=False,
        semantic_citation_adjudication=False,
        production_accepted=False,
        models=output,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("original_zip", type=Path)
    p.add_argument("qwen_zip", type=Path)
    p.add_argument("smol_zip", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    result = diagnose(args.original_zip, args.qwen_zip, args.smol_zip)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                model: value["by_arm"]["hybrid"]
                for model, value in result["models"].items()
            }
        )
    )


if __name__ == "__main__":
    main()
