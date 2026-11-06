"""Replay externally pinned historical Qwen shards, without any model generation.

Never rehabilitate the original failed Actions workflow as a successful run:
only the 32 sealed generation shards are eligible for a NEW, independently
verified aggregation. All archive ZIP identities must be pinned in source.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

RUN_ID = 38423223376
SOURCE = "bc76ac57ba972bf105c71ddd997cd215cec5df2e"
WORKFLOW = "MemoryCell disjoint 40+72 actual Qwen frozen-reader evidence"
SPECIAL = ("rag-sharded-original", "rag-sharded-calibration-joined")
EVALUATION = tuple(
    f"memory-evaluation-{case}-{part}" for case in range(8) for part in range(2)
)
REQUIRED = frozenset((*SPECIAL, *EVALUATION))
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON property")
        result[key] = value
    return result


def invalid(value):
    raise ValueError(f"nonfinite JSON number: {value}")


def read_json(path):
    path = Path(path)
    if (
        path.is_symlink()
        or not path.is_file()
        or not 0 < path.stat().st_size <= 4 * 1024 * 1024
    ):
        raise ValueError("bounded regular JSON input required")
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=unique,
        parse_constant=invalid,
    )


def validate_pins(pins):
    if (
        not isinstance(pins, dict)
        or set(pins) != {"run_id", "source_commit", "artifacts"}
        or pins["run_id"] != RUN_ID
        or pins["source_commit"] != SOURCE
        or type(pins["run_id"]) is not int
        or not isinstance(pins["artifacts"], dict)
        or set(pins["artifacts"]) != REQUIRED
    ):
        raise ValueError("incomplete or altered externally registered population")
    ids = set()
    for name, pin in pins["artifacts"].items():
        if (
            type(pin) is not dict
            or set(pin) != {"id", "sha256", "size"}
            or type(pin["id"]) is not int
            or pin["id"] <= 0
            or pin["id"] in ids
            or type(pin["size"]) is not int
            or not 0 < pin["size"] <= 2 * 1024 * 1024
            or not isinstance(pin["sha256"], str)
            or HEX64.fullmatch(pin["sha256"]) is None
            or "/" in name
        ):
            raise ValueError("nonunique, unsafe or unpinned original artifact")
        ids.add(pin["id"])
    return pins


def qualify(pins, run, jobs, metadata):
    """The generator run FAILED; only successfully executed sealed jobs qualify."""
    validate_pins(pins)
    if (
        not isinstance(run, dict)
        or run.get("id") != RUN_ID
        or run.get("head_sha") != SOURCE
        or run.get("name") != WORKFLOW
        or run.get("run_attempt") != 16
        or run.get("status") != "completed"
        or run.get("conclusion") != "failure"
    ):
        raise ValueError("original failing workflow/run/source identity moved")
    job_rows = jobs.get("jobs")
    artifact_rows = metadata.get("artifacts")
    if (
        not isinstance(job_rows, list)
        or not isinstance(artifact_rows, list)
        or type(jobs.get("total_count")) is not int
        or type(metadata.get("total_count")) is not int
        or len(job_rows) != jobs["total_count"]
        or len(artifact_rows) != metadata["total_count"]
        or not 1 <= len(job_rows) <= 100
        or not 18 <= len(artifact_rows) <= 100
    ):
        raise ValueError("incomplete generating-job or artifact metadata census")
    required_jobs = (
        {"preflight", "prepare", "calibration-collect"}
        | {f"calibration-shard ({i}, {part})" for i in range(8) for part in range(2)}
        | {f"evaluation-shard ({i}, {part})" for i in range(8) for part in range(2)}
    )
    by_job = {}
    for row in job_rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            raise ValueError("invalid original job metadata")
        if row["name"] in by_job:
            raise ValueError("duplicate original job name")
        by_job[row["name"]] = row
    if (
        not required_jobs.issubset(by_job)
        or any(by_job[name].get("conclusion") != "success" for name in required_jobs)
        or by_job.get("evaluation-collect", {}).get("conclusion") != "failure"
        or by_job.get("independent-replay", {}).get("conclusion") != "skipped"
    ):
        raise ValueError("unqualified generation or failed collector not preserved")
    by_name, all_ids = {}, set()
    for row in artifact_rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("name"), str)
            or type(row.get("id")) is not int
            or row["id"] in all_ids
            or row["name"] in by_name
        ):
            raise ValueError("ambiguous artifact metadata")
        by_name[row["name"]] = row
        all_ids.add(row["id"])
    for name in REQUIRED:
        pin = pins["artifacts"][name]
        item = by_name.get(name)
        if (
            item is None
            or item.get("id") != pin["id"]
            or item.get("digest") != "sha256:" + pin["sha256"]
            or item.get("size_in_bytes") != pin["size"]
            or item.get("expired") is not False
            or not isinstance(item.get("workflow_run"), dict)
            or item["workflow_run"].get("head_sha") != SOURCE
        ):
            raise ValueError("expired, forged or missing pinned original artifact")
    return {
        "schema": "hepta.memory-cell.disjoint-archived-closure-admission.v1",
        "generating_run_id": RUN_ID,
        "generating_source_commit": SOURCE,
        "generating_workflow_conclusion": "failure",
        "successful_original_calibration_jobs": 16,
        "successful_original_evaluation_jobs": 16,
        "sealed_archives_to_reopen": len(REQUIRED),
        "original_evaluation_collector": "failed",
        "recovery_method": "read_only_new_source_replay",
        "new_model_calls": 0,
        "human_semantic_review": False,
        "future_independent_source_families": 0,
        "parametric_training_qualified": False,
        "production_accepted": False,
    }


def extract_one(pins, name, zip_path, destination):
    validate_pins(pins)
    if name not in REQUIRED:
        raise ValueError("unregistered archived shard")
    zip_path, destination = Path(zip_path), Path(destination)
    registered = pins["artifacts"][name]
    if (
        zip_path.is_symlink()
        or not zip_path.is_file()
        or zip_path.stat().st_size != registered["size"]
        or hashlib.sha256(zip_path.read_bytes()).hexdigest() != registered["sha256"]
    ):
        raise ValueError("external Actions ZIP identity or size differs")
    with zipfile.ZipFile(zip_path) as archive:
        entries = archive.infolist()
        if not 1 <= len(entries) <= 256:
            raise ValueError("archive member census bound")
        if sum(entry.file_size for entry in entries) > 32 * 1024 * 1024:
            raise ValueError("decompression size bound")
        decoded, normalized = {}, set()
        for item in entries:
            path = PurePosixPath(item.filename)
            value = str(path)
            if (
                not value
                or value in (".", "..")
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in item.filename
                or item.is_dir()
                or stat.S_ISLNK(item.external_attr >> 16)
                or value in normalized
            ):
                raise ValueError("unsafe, duplicate or nonregular archive member")
            normalized.add(value)
            decoded[value] = archive.read(item)
    destination.mkdir(parents=True, exist_ok=False)
    for name, raw in decoded.items():
        location = destination.joinpath(*PurePosixPath(name).parts)
        location.parent.mkdir(parents=True, exist_ok=True)
        with location.open("xb") as target:
            target.write(raw)
    return len(decoded)


def unpack(pins, zip_directory, root):
    validate_pins(pins)
    if root.exists():
        raise ValueError("replay destination must be new")
    root.mkdir(parents=True)
    result = {}
    for name in sorted(REQUIRED):
        destination = (
            root / "original"
            if name == SPECIAL[0]
            else root / "joined"
            if name == SPECIAL[1]
            else root / "evaluation" / name
        )
        result[name] = extract_one(
            pins, name, zip_directory / (name + ".zip"), destination
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    for arg in ("pins", "run", "jobs", "artifacts", "report", "downloads"):
        plan.add_argument(arg, type=Path)
    restore = sub.add_parser("unpack")
    for arg in ("pins", "zips", "output"):
        restore.add_argument(arg, type=Path)
    single = sub.add_parser("unpack-one")
    for arg in ("pins", "name", "zip", "output"):
        single.add_argument(arg, type=Path if arg != "name" else str)
    args = parser.parse_args()
    pins = validate_pins(read_json(args.pins))
    if args.command == "plan":
        report = qualify(
            pins, read_json(args.run), read_json(args.jobs), read_json(args.artifacts)
        )
        with args.report.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
        with args.downloads.open("x", encoding="utf-8") as handle:
            for name in sorted(REQUIRED):
                handle.write(f"{name}\t{pins['artifacts'][name]['id']}\n")
        print(json.dumps(report, sort_keys=True))
    elif args.command == "unpack":
        print(json.dumps(unpack(pins, args.zips, args.output), sort_keys=True))
    else:
        print(extract_one(pins, args.name, args.zip, args.output))


if __name__ == "__main__":
    main()
