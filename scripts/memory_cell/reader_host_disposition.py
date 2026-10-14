"""Read-only failure census for the 16 frozen Reader-host inference shards.

An uploaded partial Actions artifact is not a model success. Validate each
shard's local seal and host receipt, preserve absent/failed original journals,
and never open labels or turn CPU capability into task quality evidence.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re

PROFILE = "hepta.memory-cell.reader-host-disposition.v1"
TIERS = ("smol-1.7b", "qwen-3b")
ARMS = ("none", "selected_k", "hybrid_k4", "declared_support", "minus_one")
HOST_SCHEMA = "hepta.memory-strong-rag.bf16-host-gate.v1"
RUN_SCHEMA = "hepta.memory-cell.reader-bottleneck-original.v1"
SOURCE = re.compile(r"[0-9a-f]{40}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
MANIFEST = re.compile(r"([0-9a-f]{64})  (?:\./)?([a-zA-Z0-9_.-]+)\Z")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate original receipt JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("nonfinite original receipt " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def sealed(folder):
    """Check a *local* SHA256SUMS and physical file census, not an outer ZIP pin."""
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("invalid extracted shard directory")
    manifest = folder / "SHA256SUMS"
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("missing original shard SHA256SUMS")
    files = {}
    for file in folder.iterdir():
        if (
            file.is_symlink()
            or not file.is_file()
            or file.stat().st_size > 2 * 1024 * 1024
        ):
            raise ValueError("unsafe or oversized original shard member")
        files[file.name] = file.read_bytes()
    if not 2 <= len(files) <= 16:
        raise ValueError("unbounded original shard file count")
    if len(files["SHA256SUMS"]) > 4096:
        raise ValueError("oversized original shard manifest")
    hashes = {}
    for line in files["SHA256SUMS"].decode("ascii").splitlines():
        match = MANIFEST.fullmatch(line)
        if match is None:
            raise ValueError("malformed original shard manifest")
        digest, name = match.groups()
        if name in hashes or name == "SHA256SUMS":
            raise ValueError("duplicate or self-pinned manifest name")
        hashes[name] = digest
    if set(hashes) != set(files) - {"SHA256SUMS"}:
        raise ValueError("missing or extra original shard member")
    if any(sha(files[key]) != digest for key, digest in hashes.items()):
        raise ValueError("original shard SHA256SUMS mismatch")
    return files


def inspect(folder, tier, index, *, expected_commit):
    if type(index) is not int or not 0 <= index < 8 or tier not in TIERS:
        raise ValueError("unregistered reader shard")
    result = dict(
        tier=tier,
        case_index=index,
        present=folder.exists(),
        host_eligible=None,
        host_cpu_models=None,
        raw_attempt_rows=0,
        raw_success_rows=0,
        full_original_journal=False,
        outcome="missing_shard_artifact",
    )
    if not folder.exists():
        return result
    files = sealed(folder)
    if files.get("checkout-commit.txt", b"").decode("ascii").strip() != expected_commit:
        raise ValueError("original shard checkout differs from generating HEAD")
    if "host-gate.json" not in files:
        if "run.json" in files or "raw-answers.jsonl" in files:
            raise ValueError("model claim without hardware provenance")
        result["outcome"] = "host_receipt_missing"
        return result
    gate = strict_json(files["host-gate.json"])
    if (
        gate.get("schema") != HOST_SCHEMA
        or gate.get("policy") != "x86_64-original-qwen-torch2.5.1-cpu-bfloat16-eager"
        or gate.get("new_model_calls") != 0
        or gate.get("production_accepted") is not False
        or type(gate.get("host_eligible")) is not bool
    ):
        raise ValueError("unqualified original BF16 hardware gate")
    result["host_eligible"] = gate["host_eligible"]
    result["host_cpu_models"] = gate.get("cpu_models")
    if not gate["host_eligible"]:
        if (
            gate.get("all_cpus_bf16_accelerated") is not False
            or "run.json" in files
            or "raw-answers.jsonl" in files
        ):
            raise ValueError("ineligible hardware cannot claim a generated answer")
        result["outcome"] = "hardware_ineligible"
        return result
    if (
        gate.get("all_cpus_bf16_accelerated") is not True
        or gate.get("machine") != "x86_64"
        or gate.get("same_original_model_weights_required") is not True
    ):
        raise ValueError("forged positive BF16 hardware disposition")
    raw = files.get("raw-answers.jsonl")
    if raw is not None:
        if not raw.endswith(b"\n"):
            raise ValueError("unsealed original answer journal")
        rows = [strict_json(line) for line in raw.splitlines()]
        if not 1 <= len(rows) <= len(ARMS):
            raise ValueError("bounded original model attempt census required")
        if [row.get("arm") for row in rows] != list(ARMS[: len(rows)]):
            raise ValueError("changed original arm order or duplicated attempts")
        for row in rows:
            if row.get("status") not in ("failed", "succeeded"):
                raise ValueError("unknown original model attempt state")
            if row["status"] == "succeeded":
                receipt = row.get("receipt")
                if (
                    not isinstance(receipt, dict)
                    or receipt.get("trainable_parameters") != 0
                    or receipt.get("answer_postprocessed") is not False
                    or not isinstance(row.get("answer"), str)
                    or not row["answer"].strip()
                ):
                    raise ValueError("unsubstantiated original model answer")
        result["raw_attempt_rows"] = len(rows)
        result["raw_success_rows"] = sum(r["status"] == "succeeded" for r in rows)
    if "run.json" not in files:
        result["outcome"] = (
            "incomplete_original_journal" if raw is not None else "no_model_journal"
        )
        return result
    run = strict_json(files["run.json"])
    if (
        raw is None
        or run.get("schema") != RUN_SCHEMA
        or run.get("source_commit") != expected_commit
        or run.get("tier") != tier
        or run.get("case_index") != index
        or run.get("raw_sha256") != sha(raw)
        or run.get("attempts") != len(ARMS)
        or run.get("actual_successes") != result["raw_success_rows"]
        or run.get("arms") != list(ARMS)
        or run.get("learned_parameters") != 0
        or run.get("target_labels_exposed") is not False
        or run.get("production_accepted") is not False
        or result["raw_attempt_rows"] != len(ARMS)
        or any(
            r["receipt"].get("reader_identity") != run["reader_identity"]
            for r in rows
            if r["status"] == "succeeded"
        )
    ):
        raise ValueError("invalid or mixed original model run receipt")
    result["full_original_journal"] = result["raw_success_rows"] == len(ARMS)
    result["outcome"] = (
        "complete_original_journal_not_independently_scored"
        if result["full_original_journal"]
        else "complete_attempts_with_failed_generation"
    )
    return result


def census(root, *, expected_commit):
    if not SOURCE.fullmatch(expected_commit):
        raise ValueError("generating source commit must be an exact SHA")
    if root.is_symlink() or not root.is_dir():
        raise ValueError("original shard artifact directory required")
    expected = {
        f"memory-reader-bottleneck-{tier}-{index}"
        for tier in TIERS
        for index in range(8)
    }
    unexpected = {
        entry.name
        for entry in root.iterdir()
        if entry.name.startswith("memory-reader-bottleneck-")
        and entry.name not in expected
    }
    if unexpected:
        raise ValueError("unregistered original shard artifact names")
    records = [
        inspect(
            root / f"memory-reader-bottleneck-{tier}-{index}",
            tier,
            index,
            expected_commit=expected_commit,
        )
        for tier in TIERS
        for index in range(8)
    ]
    return dict(
        schema=PROFILE,
        source_commit=expected_commit,
        originally_planned_model_calls=len(TIERS) * 8 * len(ARMS),
        observed_raw_attempt_rows=sum(r["raw_attempt_rows"] for r in records),
        observed_raw_succeeded_rows=sum(r["raw_success_rows"] for r in records),
        complete_original_journal_shards=sum(
            r["full_original_journal"] for r in records
        ),
        ineligible_hardware_shards=sum(
            r["outcome"] == "hardware_ineligible" for r in records
        ),
        missing_shard_artifacts=sum(not r["present"] for r in records),
        entire_generation_census_complete=all(
            r["full_original_journal"] for r in records
        ),
        shards=records,
        original_github_artifact_outer_digests_verified=False,
        reader_capacity_improvement=None,
        task_success_rate=None,
        human_sufficient_evidence_reviewed=False,
        prospective_real_project_tasks_qualified=False,
        learned_memory_gain_proven=False,
        independent_semantic_review=False,
        production_accepted=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shards", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    report = census(args.shards, expected_commit=args.source)
    with args.report.open("x", encoding="utf-8") as output:
        json.dump(report, output, sort_keys=True, indent=2, allow_nan=False)
        output.write("\n")
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "originally_planned_model_calls",
                    "observed_raw_attempt_rows",
                    "observed_raw_succeeded_rows",
                    "complete_original_journal_shards",
                    "ineligible_hardware_shards",
                    "missing_shard_artifacts",
                )
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
