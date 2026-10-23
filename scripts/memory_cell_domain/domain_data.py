"""Produce bounded memory observations from pinned, actually completed CI runs.

Repair labels are annotations, not causal proofs. A successful run verifies only
the recorded workflow. Historical incidents never become prospective evidence.
"""

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re


TRAIN_TEMPLATES = [
    "For failure {entity}, return the recorded {relation} code.",
    "Which {relation} code was recorded for failure {entity}?",
    "Recall the {relation} code for this failure: {entity}",
    "Failure: {entity}. Give its stored {relation} code.",
]
SELECT_TEMPLATE = "Find the recorded {relation} code associated with failure {entity}."
FINAL_TEMPLATE = (
    "According to incident memory, what {relation} code resolves failure {entity}?"
)


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def write_json(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value))


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return result


def pinned_file(directory, reference):
    if set(reference) != {"path", "sha256"}:
        raise ValueError("closed path/hash reference required")
    requested = directory / reference["path"]
    path = requested.resolve()
    if (
        not path.is_relative_to(directory.resolve())
        or requested.is_symlink()
        or not path.is_file()
    ):
        raise ValueError("source must stay inside the input directory")
    with path.open("rb") as stream:
        raw = stream.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024 or sha(raw) != reference["sha256"]:
        raise ValueError("source size or hash mismatch")
    return raw


def partition_cases(cases, train_until, validation_until):
    """Purge groups crossing time boundaries; never split one repair family."""
    first, second = timestamp(train_until), timestamp(validation_until)
    if first > second:
        raise ValueError("ordered time cutoffs required")
    groups = {}
    for case in cases:
        # Root-cause groups are global, so another project cannot leak the same
        # repair family into a later split under a different project spelling.
        groups.setdefault(case["root_cause"], []).append(case)
    partitions = {name: [] for name in ("train", "validation", "future", "purged")}
    for values in groups.values():
        earliest = min(timestamp(x["observed_at"]) for x in values)
        latest = max(timestamp(x["resolved_at"]) for x in values)
        split = (
            "train"
            if latest <= first
            else "validation"
            if earliest > first and latest <= second
            else "future"
            if earliest > second
            else "purged"
        )
        partitions[split].extend(x["id"] for x in values)
    return partitions


def produce(manifest_path, output):
    manifest_path, output = Path(manifest_path), Path(output)
    original = manifest_path.read_bytes()
    manifest = json.loads(original)
    if manifest.get("schema") != "hepta.domain.ci-manifest.v1":
        raise ValueError("registered CI manifest required")
    registered = timestamp(manifest["registered_at"])
    root, sources, records = manifest_path.parent, {}, []

    def retain(ref):
        raw = pinned_file(root, ref)
        sources[sha(raw)] = raw
        return raw

    runs = json.loads(retain(manifest["runs"]))
    runs = runs["workflow_runs"] if isinstance(runs, dict) else runs
    by_id = {run["id"]: run for run in runs}
    if len(by_id) != len(runs) or not 2 <= len(manifest["cases"]) <= 64:
        raise ValueError("distinct runs and two to sixty-four incident groups required")
    for entry in manifest["cases"]:
        failed, passed = (by_id[entry[k]] for k in ("failed_run_id", "success_run_id"))
        commit = json.loads(retain(entry["fix"]))
        bad_log, good_log = retain(entry["failure_log"]), retain(entry["success_log"])
        project = failed["repository"]["full_name"]
        if (
            failed["status"] != "completed"
            or failed["conclusion"] != "failure"
            or passed["status"] != "completed"
            or passed["conclusion"] != "success"
            or failed["head_sha"] not in {p["sha"] for p in commit["parents"]}
            or passed["head_sha"] != commit["sha"]
            or failed["path"] != passed["path"]
            or passed["repository"]["full_name"] != project
            or not commit.get("files")
            or not bad_log
            or not good_log
        ):
            raise ValueError(
                "direct parent fix and completed same-workflow success required"
            )
        symptom = entry["symptom"]
        if (
            not isinstance(symptom, str)
            or not 1 <= len(symptom.encode()) <= 240
            or symptom.encode() not in bad_log
            or "\x00" in symptom
            or re.fullmatch(r"[a-z][a-z0-9_]{0,31}", entry["repair_id"]) is None
            or type(entry["previously_seen"]) is not bool
            or not isinstance(entry["root_cause"], str)
            or not entry["root_cause"]
        ):
            raise ValueError(
                "bounded original symptom, repair label and history required"
            )
        observed, resolved = failed["updated_at"], passed["updated_at"]
        if timestamp(observed) > timestamp(resolved):
            raise ValueError("verification predates failure")
        record = {
            k: entry[k]
            for k in ("id", "root_cause", "repair_id", "repair_text", "previously_seen")
        }
        record.update(
            project=project,
            observed_at=observed,
            resolved_at=resolved,
            symptom=symptom,
            failed_commit=failed["head_sha"],
            fixed_commit=commit["sha"],
            failed_run_id=failed["id"],
            success_run_id=passed["id"],
            workflow=failed["path"],
            failure_log_sha256=sha(bad_log),
            success_log_sha256=sha(good_log),
            commit_evidence_sha256=entry["fix"]["sha256"],
            prospective_at_registration=timestamp(observed) > registered
            and not entry["previously_seen"],
        )
        record["source_digest"] = sha(canonical(record))
        records.append(record)
    if (
        len({r["id"] for r in records}) != len(records)
        or len({r["symptom"] for r in records}) != len(records)
        or len({r["failed_run_id"] for r in records}) != len(records)
        or len({r["success_run_id"] for r in records}) != len(records)
    ):
        raise ValueError("duplicate incident, failure/success run or symptom")
    records.sort(key=lambda x: (timestamp(x["resolved_at"]), x["id"]))
    partitions = partition_cases(
        records, manifest["train_until"], manifest["validation_until"]
    )
    train_projects = {r["project"] for r in records if r["id"] in partitions["train"]}
    future = [r for r in records if r["id"] in partitions["future"]]
    result = dict(
        schema="hepta.domain.dataset.v1",
        cases=records,
        partitions=partitions,
        manifest_sha256=sha(original),
        registered_at=manifest["registered_at"],
        source_bytes=sum(map(len, sources.values())),
        source_inventory={key: len(raw) for key, raw in sources.items()},
        scope="hepta-ci-domain-development",
        independent_groups=len({r["root_cause"] for r in records}),
        future_unseen_projects=[
            r["id"] for r in future if r["project"] not in train_projects
        ],
        prospective_cases=[r["id"] for r in future if r["prospective_at_registration"]],
        status="finite_development",
        generalization_established=False,
        label_authority="source-annotated repair; workflow success is not causal attribution",
    )
    output.mkdir(parents=True, exist_ok=False)
    (output / "evidence").mkdir()
    for key, raw in sources.items():
        (output / "evidence" / key).write_bytes(raw)
    (output / "input-manifest.json").write_bytes(original)
    write_json(output / "dataset.json", result)
    return {
        "dataset": str(output / "dataset.json"),
        "sha256": sha(canonical(result)),
        "cases": len(records),
        "partitions": partitions,
        "status": result["status"],
    }


def load_dataset(path, expected_sha256):
    raw = Path(path).read_bytes()
    if sha(raw) != expected_sha256:
        raise ValueError("dataset pin changed")
    data = json.loads(raw)
    if data["schema"] != "hepta.domain.dataset.v1":
        raise ValueError("unsupported dataset")
    manifest = (Path(path).parent / "input-manifest.json").read_bytes()
    if sha(manifest) != data["manifest_sha256"]:
        raise ValueError("original source manifest changed")
    for key, size in data["source_inventory"].items():
        if re.fullmatch(r"[0-9a-f]{64}", key) is None:
            raise ValueError("bounded source digest required")
        source = (Path(path).parent / "evidence" / key).read_bytes()
        if len(source) != size or sha(source) != key:
            raise ValueError("original source unavailable or changed")
    for case in data["cases"]:
        source = {key: value for key, value in case.items() if key != "source_digest"}
        if sha(canonical(source)) != case["source_digest"] or any(
            case[field] not in data["source_inventory"]
            for field in (
                "failure_log_sha256",
                "success_log_sha256",
                "commit_evidence_sha256",
            )
        ):
            raise ValueError("case source binding changed")
    return data


def probes(cases, templates, *, unknown=False):
    return [
        dict(
            case_id=c["id"],
            question=t.format(
                entity=c["symptom"],
                relation="unrecorded checksum" if unknown else "repair",
            ),
            answer="unknown" if unknown else c["repair_id"],
            root=None if unknown else c["source_digest"],
            synthetic_unknown=unknown,
        )
        for c in cases
        for t in templates
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(produce(args.manifest, args.output), indent=2))
