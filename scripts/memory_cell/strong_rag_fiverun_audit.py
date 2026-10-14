"""Exact read-only five-run audit of original Qwen reader journals.

Every required byte is pinned in advance. This reports *repeated* authored
questions, not independent future populations, model learning or acceptance.
"""

from __future__ import annotations

from itertools import combinations
import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

SCHEMA = "hepta.memory-strong-rag.five-original-runs.v1"
PLAN_SHA = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
MODEL_ID = "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"
PINS = {
    "A": dict(
        run_id=38148514657,
        source="8250698244417eb14994518af05fa6f79e783066",
        full="7c991f0996fc24c650efb28f6266da51ed1655b78585e11b78dbc424707b7b7f",
        replay="7e390bddfb1c59e0bb82999b01747a180eb1ec1f84d9f863a536dd036ec483f1",
        members=267,
        replay_members=1,
        workflow="success",
    ),
    "B": dict(
        run_id=38146546731,
        source="eba9af092cca1c2875552ffaea2219678143a73c",
        full="b4cf1346ce4c5b1625cdc57845bcca33fcf82f84340433b602d76258c10c1138",
        replay="4c64e9c01bef56d0f311e633af53c7a246102e7083a272122286fb7ff66085a3",
        members=267,
        replay_members=1,
        workflow="success",
    ),
    "C": dict(
        run_id=38114667490,
        source="c24fad24b65984a6255a8854c6714c141911ff79",
        full="2d71f40e553e7d28cad9d8e16803f52b7a99e771b5bf54f55c89bc9468702107",
        replay="fe710be3f987e34ec3cda48be37509e20a01b48db090907c98ce33cfff198225",
        members=38,
        replay_members=8,
        workflow="failure_format_only_reader_and_replay_success",
    ),
    "D": dict(
        run_id=38161049090,
        source="e0e413d670be8982b9986a119696c6ca164ca518",
        full="d59560882e217d8772e4044ec33b8cdb10f5297f19b0a6e03e53266407c839a0",
        replay="9a4dfb20f0ab5bb6de6ed577e7787d3faa8c02f5a842198a5b1b1eafced2ea53",
        members=300,
        replay_members=1,
        workflow="success",
    ),
    "E": dict(
        run_id=38389920977,
        source="3b03ea7dee4b270bdf328251f7a404571c9d1013",
        full="de7087dbd3ee367475ef279d01dbeeeea46ee991b11399324289300df10c40bf",
        replay="442c7171cb2c522988e6e6c52b12201d1b59104702229dc256ca91b7bf6559c1",
        members=43,
        replay_members=8,
        workflow="success",
    ),
}
CAL_ARMS = ("k1", "k2", "k3", "k4", "k6")
EVAL_ARMS = (
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
SCORED_ONLY = frozenset(
    (
        "parsed_identifier",
        "strict_task_success",
        "required_sources_covered",
        "procedure_verification",
    )
)


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def strict_json(payload):
    def object_pairs(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON member")
            value[key] = item
        return value

    def number(value):
        num = float(value)
        if not math.isfinite(num):
            raise ValueError("nonfinite floating-point number")
        return num

    def constant(value):
        raise ValueError("nonfinite JSON constant")

    return json.loads(
        payload,
        object_pairs_hook=object_pairs,
        parse_float=number,
        parse_constant=constant,
    )


def _canonical(name):
    p = PurePosixPath(name)
    if (
        not name
        or name.startswith("/")
        or name != str(p)
        or "\\" in name
        or any(x in ("..", ".", "") for x in p.parts)
    ):
        raise ValueError("noncanonical ZIP path")


def archive(path, digest, members, *, kind):
    path = Path(path)
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > 16 * 1024 * 1024
        or sha(path.read_bytes()) != digest
    ):
        raise ValueError("wrong original ZIP SHA-256")
    with zipfile.ZipFile(path) as zipped:
        infos = zipped.infolist()
        if (
            not infos
            or len(infos) != members + (1 if kind == "full" or members > 1 else 0)
            or len(infos) > 400
            or sum(i.file_size for i in infos) > 12 * 1024 * 1024
        ):
            raise ValueError("wrong original ZIP file count/budget")
        names = set()
        for obj in infos:
            _canonical(obj.filename)
            if (
                obj.filename in names
                or obj.is_dir()
                or stat.S_ISLNK(obj.external_attr >> 16)
            ):
                raise ValueError("duplicate, directory or symlink archive member")
            names.add(obj.filename)
        files = {x.filename: zipped.read(x) for x in infos}
    if "SHA256SUMS" in files:
        specified = {}
        for line in files["SHA256SUMS"].decode("utf-8").splitlines():
            found = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
            if not found:
                raise ValueError("invalid original manifest")
            expected, name = found.groups()
            _canonical(name)
            if name in specified:
                raise ValueError("duplicate manifest member")
            specified[name] = expected
        if set(specified) != names - {"SHA256SUMS"} or any(
            sha(files[name]) != h for name, h in specified.items()
        ):
            raise ValueError("wrong original manifest census or member hash")
    elif kind == "full" or set(files) != {"shard-replay.json"}:
        raise ValueError("missing original archive manifest")
    if kind == "replay" and set(files) != (
        {"shard-replay.json"} if members == 1 else set(files)
    ):
        raise ValueError("unexpected replay archive contents")
    return files


def load(label, full_path, replay_path, pins=PINS):
    pin = pins[label]
    main = archive(full_path, pin["full"], pin["members"], kind="full")
    verified = archive(replay_path, pin["replay"], pin["replay_members"], kind="replay")
    if main["tested-commit.txt"].decode().strip() != pin["source"]:
        raise ValueError("emitting source commit differs")
    replay = strict_json(
        verified["shard-replay.json"]
        if pin["replay_members"] == 1
        else verified["receipt.json"]
    )
    policy = strict_json(main["calibration/frozen-policy.json"])
    if (
        replay["generating_commit"] != pin["source"]
        or replay["production_accepted"] is not False
        or policy["source_commit"] != pin["source"]
        or policy["original_test_plan_sha256"] != PLAN_SHA
        or policy["reader_identity"] != MODEL_ID
        or policy["selected_k"] != 1
        or policy["production_accepted"] is not False
    ):
        raise ValueError("frozen policy/model or separate replay identity drift")
    stages = {}
    for phase, expected_arms in (("calibration", CAL_ARMS), ("evaluation", EVAL_ARMS)):
        rawbytes = main[f"{phase}/raw-answers.jsonl"]
        if not rawbytes.endswith(b"\n"):
            raise ValueError("truncated raw journal")
        raw = [strict_json(s) for s in rawbytes.splitlines()]
        scored = strict_json(main[f"{phase}/scored-answers.json"])
        report = strict_json(main[f"{phase}/report.json"])
        run = strict_json(main[f"{phase}/run.json"])
        count = 8 * len(expected_arms)
        audit = replay[phase]
        if (
            len(raw) != count
            or len(scored) != count
            or run["source_commit"] != pin["source"]
            or report["source_commit"] != pin["source"]
            or report["raw_answers_sha256"] != sha(rawbytes)
            or audit["attempts"] != count
            or audit["all_model_calls_succeeded"] is not True
            or audit["original_raw_sha256"] != sha(rawbytes)
        ):
            raise ValueError("missing or detached original model answers")
        lookup, outcomes = {}, {}
        for original, result in zip(raw, scored, strict=True):
            key = (original["question_id"], original["arm"])
            if (
                key in lookup
                or original["arm"] not in expected_arms
                or original["status"] != "succeeded"
                or result["status"] != "succeeded"
            ):
                raise ValueError("missing, duplicate or failed model generation")
            if (
                any(x in original for x in SCORED_ONLY)
                or {k: v for k, v in result.items() if k not in SCORED_ONLY} != original
            ):
                raise ValueError("scorer rewrote an original generated answer")
            if type(result.get("strict_task_success")) is not bool:
                raise ValueError("missing registered outcome")
            receipt = original["receipt"]
            if (
                receipt["reader_identity"] != MODEL_ID
                or receipt["token_limit"] != 2048
                or not re.fullmatch(r"[0-9a-f]{64}", receipt["input_ids_digest"])
                or not re.fullmatch(r"[0-9a-f]{64}", receipt["generated_ids_digest"])
                or type(receipt["input_tokens"]) is not int
                or not 0 < receipt["input_tokens"] <= 2048
                or type(receipt["generated_tokens"]) is not int
                or not 0 <= receipt["generated_tokens"] <= 64
                or receipt["production_accepted"] is not False
            ):
                raise ValueError("model receipt/precision/budget identity changed")
            lookup[key], outcomes[key] = original, result
        if len({key[0] for key in lookup}) != 8 or set(key[1] for key in lookup) != set(
            expected_arms
        ):
            raise ValueError("incomplete question/arm grid")
        by_arm = {}
        for arm in expected_arms:
            rows = [outcomes[key] for key in outcomes if key[1] == arm]
            correctness = sum(x["strict_task_success"] for x in rows)
            tokens = sum(x["receipt"]["input_tokens"] for x in rows)
            stats = (
                report["arms"] if phase == "calibration" else report["success_by_arm"]
            )[arm]
            if (
                stats["strict_success"] != correctness
                or stats["input_tokens"] != tokens
                or audit["strict_success"][arm] != correctness
            ):
                raise ValueError("original score summary differs from raw answers")
            entry = dict(correct=correctness, input_tokens=tokens)
            if phase == "evaluation":
                cited = report["formal_citation_chain"]["by_arm"][arm]
                case_rows = [
                    x
                    for x in report["formal_citation_chain"]["cases"]
                    if x["arm"] == arm
                ]
                if len(case_rows) != 8 or any(
                    type(x["strict_task_success"]) is not bool for x in case_rows
                ):
                    raise ValueError("incomplete citation census")
                for cite in case_rows:
                    row = outcomes[(cite["question_id"], arm)]
                    if (
                        cite["answer"] != row["answer"]
                        or cite["strict_task_success"] != row["strict_task_success"]
                    ):
                        raise ValueError(
                            "citation trace detached from original generated answer"
                        )
                complete = sum(
                    x["strict_task_success"] and x["program_declared_support_cited"]
                    for x in case_rows
                )
                if (
                    cited["strict_task_success"] != correctness
                    or cited["correct_with_full_program_declared_citations"] != complete
                ):
                    raise ValueError("incorrect reported citation-chain completion")
                entry["complete_declared_citation_chains"] = complete
            by_arm[arm] = entry
        stages[phase] = dict(
            rows=lookup, scored=outcomes, metrics=by_arm, sha=sha(rawbytes)
        )
    return dict(
        label=label,
        source=pin["source"],
        run_id=pin["run_id"],
        status=pin["workflow"],
        calibration=stages["calibration"],
        evaluation=stages["evaluation"],
        model_id=MODEL_ID,
    )


def compare_five(runs):
    if set(runs) != set(PINS):
        raise ValueError("all five pinned original executions required")
    unstable, pairs = {}, {}
    for phase in ("calibration", "evaluation"):
        left = runs["A"][phase]["rows"]
        for name in ("B", "C", "D", "E"):
            if set(runs[name][phase]["rows"]) != set(left):
                raise ValueError("different original question/arm census")
        stage_unstable = []
        for key in sorted(left):
            rows = {name: runs[name][phase]["rows"][key] for name in PINS}
            outcomes = {
                name: runs[name][phase]["scored"][key]["strict_task_success"]
                for name in PINS
            }
            baseline = rows["A"]
            for name, row in rows.items():
                for part, a, b in (
                    (
                        "source candidates",
                        baseline["candidate_digest"],
                        row["candidate_digest"],
                    ),
                    ("ordered evidence", baseline["selected"], row["selected"]),
                    (
                        "reader profile",
                        baseline["receipt"]["reader_profile"],
                        row["receipt"]["reader_profile"],
                    ),
                    (
                        "prompt SHA",
                        baseline["receipt"]["input_ids_digest"],
                        row["receipt"]["input_ids_digest"],
                    ),
                    (
                        "delivered evidence",
                        baseline["receipt"]["delivered_evidence"],
                        row["receipt"]["delivered_evidence"],
                    ),
                    (
                        "input tokens",
                        baseline["receipt"]["input_tokens"],
                        row["receipt"]["input_tokens"],
                    ),
                ):
                    if a != b:
                        raise ValueError(
                            f"changed frozen original {part}: {name} {phase} {key}"
                        )
            variants = {
                (row["answer"], row["receipt"]["generated_ids_digest"])
                for row in rows.values()
            }
            if len(variants) > 1:
                stage_unstable.append(
                    dict(
                        question_id=key[0],
                        arm=key[1],
                        outputs={label: row["answer"] for label, row in rows.items()},
                        correct=outcomes,
                        task_result_flip=len(set(outcomes.values())) > 1,
                    )
                )
        unstable[phase] = stage_unstable
    for a, b in combinations(PINS, 2):
        pair = {}
        for phase in ("calibration", "evaluation"):
            xx, yy = runs[a][phase]["rows"], runs[b][phase]["rows"]
            pair[phase] = sum(
                xx[k]["answer"] != yy[k]["answer"]
                or xx[k]["receipt"]["generated_ids_digest"]
                != yy[k]["receipt"]["generated_ids_digest"]
                for k in xx
            )
        pairs[a + "_vs_" + b] = pair
    arm_stats = {
        arm: {name: runs[name]["evaluation"]["metrics"][arm] for name in PINS}
        for arm in EVAL_ARMS
    }
    decisions = {
        name: dict(
            organizer_minus_entity_time_tasks=runs[name]["evaluation"]["metrics"][
                "organized"
            ]["correct"]
            - runs[name]["evaluation"]["metrics"]["entity_time"]["correct"],
            organizer_minus_entity_time_citation_chains=runs[name]["evaluation"][
                "metrics"
            ]["organized"]["complete_declared_citation_chains"]
            - runs[name]["evaluation"]["metrics"]["entity_time"][
                "complete_declared_citation_chains"
            ],
        )
        for name in PINS
    }
    # New original E must not be relabelled as an independent question family.
    new_variations = {}
    for phase in ("calibration", "evaluation"):
        original = ("A", "B", "C", "D")
        new_variations[phase] = []
        for key in sorted(runs["E"][phase]["rows"]):
            prior = {
                (
                    runs[name][phase]["rows"][key]["answer"],
                    runs[name][phase]["rows"][key]["receipt"][
                        "generated_ids_digest"
                    ],
                )
                for name in original
            }
            current = (
                runs["E"][phase]["rows"][key]["answer"],
                runs["E"][phase]["rows"][key]["receipt"]["generated_ids_digest"],
            )
            if len(prior) == 1 and current not in prior:
                new_variations[phase].append(dict(question_id=key[0], arm=key[1]))
    return dict(
        schema=SCHEMA,
        source_pins=PINS,
        original_frozen_plan_sha256=PLAN_SHA,
        reader_inventory_digest=MODEL_ID,
        source_runs=5,
        original_generations_per_run=112,
        actual_archived_model_generations=560,
        unchanged_input_prompt_census={"calibration": 40, "evaluation": 72},
        chosen_k={name: 1 for name in PINS},
        per_arm=arm_stats,
        cross_run_unstable_inputs={
            phase: len(rows) for phase, rows in unstable.items()
        },
        unstable_inputs=unstable,
        pairwise_different_outputs=pairs,
        new_variants_only_in_fifth_run=new_variations,
        across_run_task_outcome_flips=[
            dict(
                phase=phase,
                question_id=r["question_id"],
                arm=r["arm"],
                outcomes=r["correct"],
            )
            for phase, rows in unstable.items()
            for r in rows
            if r["task_result_flip"]
        ],
        causal_differences=decisions,
        org_task_accuracy_superiority=False,
        org_complete_citation_superiority=False,
        independent_new_source_families=0,
        independent_semantic_citation_adjudication=False,
        repeated_questions_are_independent=False,
        full_production_lifecycle_cost_measured=False,
        production_accepted=False,
        disposition="NO-GO: no incremental organized-over-full-path task or complete declared-citation gain on exposed authored tasks; independent source families required",
    )


def run(paths, *, pins=PINS):
    if set(paths) != set(pins) or set(pins) != set(PINS):
        raise ValueError("all exact five registered ZIP pairs required")
    result = compare_five(
        {label: load(label, *paths[label], pins=pins) for label in PINS}
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for label in PINS:
        parser.add_argument(label.lower() + "_full", type=Path)
        parser.add_argument(label.lower() + "_replay", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pairs = {
        label: (
            getattr(args, label.lower() + "_full"),
            getattr(args, label.lower() + "_replay"),
        )
        for label in PINS
    }
    result = run(pairs)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "source_runs": result["source_runs"],
                "unstable": result["cross_run_unstable_inputs"],
                "outcome_flips": len(result["across_run_task_outcome_flips"]),
                "accepted": False,
            }
        )
    )


if __name__ == "__main__":
    main()
