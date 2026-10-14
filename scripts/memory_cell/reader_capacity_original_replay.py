"""Independently replay sealed historical 8x6x2 frozen Reader capacity results.

Research-only. The two models have different tokenizers and are not a weights-only
intervention. Never turn old inference/author labels into new model/semantic gains.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import zipfile

SCHEMA = "hepta.memorycell.historical-reader-capacity-original-replay.v1"
SOURCE = "d773742bc8c1fbf210293db55c0ab16505440a217d3f66ddc17f7d723fbedb99"
PLAN = "5927a01e11a0bf7199fa0b77f0d4215ed6823da7c32e3cf0496b43042a35b529"
WORKER = "5adfa11f201ef35480718828f30c9e5581c98e979210e3ee5a64363e3576b3d1"
ENV = "8c6b6d4050832af6cbb21f87927147fa446ed4fafd495ee46dc62563f89cc6f2"
GENERATION = "59f9eadd5cc919359079e04442f7343838a60057"
MODELS = {
    "qwen-3b": (
        "ad6901d916b9fb263f86ee21b24d3c97236391936eda884fde50e52af16741a9",
        "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225",
        "Qwen/Qwen2.5-3B-Instruct",
        "82f42baa094a9600e39ccd80d34058aeeb3abbc1",
    ),
    "smol-1.7b": (
        "149bf665ab2916e675f69d5e62cbe02dd07cf532afa98daa17804a86508a215a",
        "78ad24ab45f9620ada47df17a7de446f24ab4082fb993dd143ee30fce422acec",
        "HuggingFaceTB/SmolLM2-1.7B-Instruct",
        "31b70e2e869a7173562077fd711b654946d38674",
    ),
}
ARMS = (
    "empty",
    "hybrid",
    "entity_time",
    "organized",
    "program_support",
    "without_prerequisite",
)
SCORER = frozenset(
    (
        "parsed_identifier",
        "strict_task_success",
        "required_sources_covered",
        "procedure_verification",
    )
)
IDENTIFIER = re.compile(
    r"\s*((?:site|mode)_[0-9a-f]{8})(?:\s*\[E[1-9][0-9]*\])*\s*\.?\s*"
)
MANIFEST = re.compile(r"([0-9a-f]{64})  (?:\./)?([^\n]+)\Z")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(data):
    def unique(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ValueError("duplicate original JSON key")
            out[k] = v
        return out

    def invalid(value):
        raise ValueError("nonfinite original JSON " + value)

    return json.loads(data, object_pairs_hook=unique, parse_constant=invalid)


def opened(path, expected, *, count):
    path = Path(path)
    if (
        path.is_symlink()
        or not path.is_file()
        or not 0 < path.stat().st_size < 16 * 1024 * 1024
    ):
        raise ValueError("bounded original artifact required")
    if sha(path.read_bytes()) != expected:
        raise ValueError("external original ZIP SHA256 changed")
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if (
            len(members) != count + 1
            or sum(x.file_size for x in members) > 32 * 1024 * 1024
        ):
            raise ValueError("original archive member census incomplete")
        files = {}
        for info in members:
            name = PurePosixPath(info.filename)
            if (
                name.is_absolute()
                or ".." in name.parts
                or "\\" in info.filename
                or name.as_posix() != info.filename
                or info.is_dir()
                or stat.S_ISLNK(info.external_attr >> 16)
                or info.filename in files
            ):
                raise ValueError("invalid original ZIP member")
            files[info.filename] = archive.read(info)
    if "SHA256SUMS" not in files:
        raise ValueError("original archive has no inner SHA256SUMS")
    hashes = {}
    for line in files["SHA256SUMS"].decode("ascii").splitlines():
        match = MANIFEST.fullmatch(line)
        if not match:
            raise ValueError("invalid original manifest line")
        digest, name = match.groups()
        if name == "SHA256SUMS" or name in hashes or name not in files:
            raise ValueError("duplicate/unknown original manifest member")
        hashes[name] = digest
    if set(hashes) != set(files) - {"SHA256SUMS"} or any(
        sha(files[k]) != v for k, v in hashes.items()
    ):
        raise ValueError("original inner member SHA256 mismatch")
    return files


def strict_identifier(answer):
    found = IDENTIFIER.fullmatch(answer)
    return found[1] if found else None


def run_worker(worker_path, recipe, supplied):
    request = dict(operation="execute", recipe=recipe, supplied=supplied)
    data = json.dumps(request, sort_keys=True)
    if len(data.encode()) > 16384:
        raise ValueError("bounded program request required")
    result = subprocess.run(
        [sys.executable, "-I", "-S", str(worker_path)],
        input=data,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if len(result.stdout.encode()) + len(result.stderr.encode()) > 16384:
        raise ValueError("bounded program response required")
    return result


def replay(original_zip, qwen_zip, smol_zip):
    source = opened(original_zip, SOURCE, count=41)
    if (
        sha(source["plan/plan.json"]) != PLAN
        or sha(source["source/event_probe.py"]) != WORKER
        or sha(source["environment.txt"]) != ENV
    ):
        raise ValueError("changed frozen plan, environment or program verifier")
    plan = strict_json(source["plan/plan.json"])
    if (
        plan.get("schema") != "hepta.event-organization.plan.v1"
        or tuple(plan.get("arms", ())) != ARMS
        or len(plan.get("cases", [])) != 8
        or plan.get("token_limit") != 2048
        or plan.get("independent_human_review") is not False
        or plan.get("production_accepted") is not False
        or sha(source["observations/labels.json"]) != plan["labels_sha"]
        or sha(source["plan/source-view.json"]) != plan["source_view_sha"]
        or source["tested-commit.txt"].decode().strip() != GENERATION
    ):
        raise ValueError("source, task, authorization or label cut drift")
    cases = {item["query"]["identity"]: item for item in plan["cases"]}
    labels = {
        item["id"]: item
        for item in strict_json(source["observations/labels.json"])
        if item["phase"] == "test"
    }
    docs = {
        item["identity"]: item for item in strict_json(source["plan/source-view.json"])
    }
    if len(cases) != len(labels) or set(cases) != set(labels) or len(docs) != 108:
        raise ValueError("incomplete authentic authored development census")
    results, summary, all_raw, profiles = {}, {}, {}, {}
    with tempfile.TemporaryDirectory() as temp:
        probe = Path(temp) / "event_probe.py"
        probe.write_bytes(source["source/event_probe.py"])
        for model_name, file_path in (("qwen-3b", qwen_zip), ("smol-1.7b", smol_zip)):
            archive_sha, inventory, repository, revision = MODELS[model_name]
            model = opened(file_path, archive_sha, count=20)
            execution = strict_json(model["run/execution.json"])
            report = strict_json(model["run/report.json"])
            if (
                model["tested-commit.txt"].decode().strip() != GENERATION
                or sha(model["environment.txt"]) != ENV
                or execution["plan_sha"] != PLAN
                or execution["plan"] != plan
                or execution["model"]["tier"] != model_name
                or execution["model"]["inventory_digest"] != inventory
                or execution["model"]["repository"] != repository
                or execution["model"]["revision"] != revision
                or report.get("parametric_optimizer_executed") is not False
                or report.get("production_accepted") is not False
                or report.get("independent_human_review") is not False
                or report.get("significance_established") is not False
            ):
                raise ValueError("wrong original Reader, plan or research authority")
            raw_bytes = model["run/raw-answers.jsonl"]
            if not raw_bytes.endswith(b"\n"):
                raise ValueError("partial source model answer journal")
            raw = [strict_json(line) for line in raw_bytes.splitlines()]
            scored = strict_json(model["run/scored-answers.json"])
            if len(raw) != len(scored) or len(raw) != 8 * len(ARMS):
                raise ValueError("original model attempt census incomplete")
            groups, track, single_profile = {}, Counter(), set()
            for original, row in zip(raw, scored, strict=True):
                if {k: v for k, v in row.items() if k not in SCORER} != original:
                    raise ValueError("original model answer edited in scored overlay")
                qid, arm = row["question_id"], row["arm"]
                if qid not in cases or arm not in ARMS or (qid, arm) in groups:
                    raise ValueError("missing/duplicate original paired attempt")
                case, truth = cases[qid], labels[qid]
                ids = case["controls"][arm]["selected"]
                if (
                    row["kind"] != truth["kind"]
                    or row["kind"] != case["kind"]
                    or row["selected"] != ids
                    or row["candidate_digest"] != case["candidate_digest"]
                    or row["status"] != "succeeded"
                    or type(row["strict_task_success"]) is not bool
                    or type(row["required_sources_covered"]) is not bool
                    or set(truth["support"]).issubset(row["selected"])
                    is not row["required_sources_covered"]
                ):
                    raise ValueError(
                        "source set, task identity, journal status or coverage differs"
                    )
                receipt = row["receipt"]
                if (
                    receipt["reader_identity"] != inventory
                    or receipt.get("trainable_parameters") != 0
                    or receipt.get("answer_postprocessed") is not False
                    or receipt.get("semantic_citation_precision") is not None
                    or receipt.get("production_accepted") is not False
                    or receipt["token_limit"] != 2048
                    or type(receipt["input_tokens"]) is not int
                    or not 0 < receipt["input_tokens"] <= 2048
                    or type(receipt["generated_tokens"]) is not int
                    or not 0 <= receipt["generated_tokens"] <= 64
                    or not isinstance(receipt["reader_profile"], str)
                ):
                    raise ValueError(
                        "Reader model, budget, training or decoding profile drift"
                    )
                provided = receipt["delivered_evidence"]
                if [x["original_id"] for x in provided] != ids:
                    raise ValueError("original delivered evidence order changed")
                for i, item in enumerate(provided, 1):
                    doc = docs[item["original_id"]]
                    if (
                        item["label"] != f"E{i}"
                        or item["excerpt"] != doc["content"]
                        or doc["scope"] != case["query"]["scope"]
                        or item["observed_at"] != doc["observed_at"]
                    ):
                        raise ValueError(
                            "Reader did not receive exact original event evidence"
                        )
                parsed = strict_identifier(row["answer"])
                if parsed != row["parsed_identifier"]:
                    raise ValueError("grader grammar differs from real generation")
                success = parsed == truth["expected"]
                if row["kind"] == "procedure":
                    verified = run_worker(
                        probe, truth["procedure"], parsed or "invalid_response"
                    )
                    stored = row.get("procedure_verification")
                    if not isinstance(stored, dict) or (
                        stored["exit_code"],
                        stored["stdout"],
                        stored["stderr"],
                    ) != (verified.returncode, verified.stdout, verified.stderr):
                        raise ValueError(
                            "original program task worker reexecution differs"
                        )
                    success = verified.returncode == 0
                    track["rerun_bounded_program"] += 1
                elif row.get("procedure_verification") is not None:
                    raise ValueError("nonprogram task has forbidden worker receipt")
                if success is not row["strict_task_success"]:
                    raise ValueError(
                        "original task success disagrees with independent scoring"
                    )
                groups[(qid, arm)] = row
                track[arm] += int(success)
                single_profile.add(receipt["reader_profile"])
            if (
                set(groups) != {(qid, arm) for qid in cases for arm in ARMS}
                or len(single_profile) != 1
            ):
                raise ValueError("Reader profile or complete paired census drift")
            for arm in ARMS:
                rows = [groups[(qid, arm)] for qid in sorted(cases)]
                expected = report["arms"][arm]
                if (
                    expected["planned"] != 8
                    or expected["strict_task_successes"] != track[arm]
                    or expected["input_tokens"]
                    != sum(r["receipt"]["input_tokens"] for r in rows)
                    or expected["generated_tokens"]
                    != sum(r["receipt"]["generated_tokens"] for r in rows)
                    or not math.isclose(
                        expected["measured_read_seconds"],
                        sum(r["receipt"]["seconds"] for r in rows),
                        rel_tol=1e-9,
                        abs_tol=1e-6,
                    )
                ):
                    raise ValueError("original published summary not reproducible")
            all_raw[model_name] = groups
            profiles[model_name] = next(iter(single_profile))
            summary[model_name] = {
                arm: dict(
                    successful=track[arm],
                    denominator=8,
                    input_tokens=report["arms"][arm]["input_tokens"],
                    output_tokens=report["arms"][arm]["generated_tokens"],
                    reader_seconds=report["arms"][arm]["measured_read_seconds"],
                )
                for arm in ARMS
            }
            results[model_name] = dict(
                original_generations=len(raw),
                independent_bounded_program_replays=track["rerun_bounded_program"],
                reader_profile=next(iter(single_profile)),
                raw_answers_sha256=sha(raw_bytes),
            )
    if profiles["qwen-3b"] == profiles["smol-1.7b"]:
        raise ValueError("models/tokenizers unexpectedly share a Reader profile")
    paired = {}
    for arm in ARMS:
        wins = losses = ties = 0
        for qid in sorted(cases):
            high = all_raw["qwen-3b"][(qid, arm)]["strict_task_success"]
            low = all_raw["smol-1.7b"][(qid, arm)]["strict_task_success"]
            wins += bool(high and not low)
            losses += bool(low and not high)
            ties += bool(high == low)
            if (
                all_raw["qwen-3b"][(qid, arm)]["selected"]
                != all_raw["smol-1.7b"][(qid, arm)]["selected"]
            ):
                raise ValueError("cross-Reader original evidence drift")
        paired[arm] = dict(qwen_wins=wins, smol_wins=losses, ties=ties, n=8)
    return dict(
        schema=SCHEMA,
        original_generating_commit=GENERATION,
        original_artifact_outer_sha256={
            "source": SOURCE,
            "qwen-3b": MODELS["qwen-3b"][0],
            "smol-1.7b": MODELS["smol-1.7b"][0],
        },
        original_plan_sha256=PLAN,
        shared_original_source_and_evidence=True,
        model_and_tokenizer_changed=True,
        causal_weights_only_isolation=False,
        independent_semantic_evidence_review=False,
        original_authored_development_task_count=8,
        actual_historical_model_generations=96,
        new_model_generations=0,
        models=results,
        per_arm=summary,
        paired=paired,
        weak_reader_organized_context_success=summary["smol-1.7b"]["organized"][
            "successful"
        ],
        stronger_reader_organized_context_success=summary["qwen-3b"]["organized"][
            "successful"
        ],
        reader_capacity_is_memory_learning_gain=False,
        parametric_memory_gain_established=False,
        full_cloud_cost_usd=None,
        future_windows_completed=0,
        new_independent_source_families=0,
        production_accepted=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("qwen", type=Path)
    parser.add_argument("smol", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    data = replay(args.original, args.qwen, args.smol)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "original_generations": data["actual_historical_model_generations"],
                "new_generations": 0,
                "paired_organized": data["paired"]["organized"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
