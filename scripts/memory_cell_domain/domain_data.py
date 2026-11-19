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


def repair_patch_digest(commit):
    files = commit["files"]
    if not files or not all("filename" in file and "patch" in file for file in files):
        return None
    return sha(canonical(sorted((file["filename"], file["patch"]) for file in files)))


def source_groups(cases):
    """Conservative connected components of declared and observed ancestry.

    A renamed cause cannot make repeated commits, repair patches or original
    failure bytes independent. Generic success logs are deliberately excluded.
    """
    parents = list(range(len(cases)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    seen = {}
    for index, case in enumerate(cases):
        identities = [("declared_cause", case["root_cause"])]
        identities += [
            ("commit", case.get("project"), case[field])
            for field in ("failed_commit", "fixed_commit")
            if case.get(field)
        ]
        identities += [
            (field, case[field])
            for field in (
                "commit_evidence_sha256",
                "failure_log_sha256",
                "repair_patch_sha256",
            )
            if case.get(field)
        ]
        for identity in identities:
            if identity in seen:
                parents[root(index)] = root(seen[identity])
            else:
                seen[identity] = index
    groups = {}
    for index, case in enumerate(cases):
        groups.setdefault(root(index), []).append(case)
    return list(groups.values())


def source_group_ids(cases):
    """Return aligned canonical component IDs for training and evaluation."""
    identities = {}
    for component in source_groups(cases):
        group = sha(canonical(sorted(case["id"] for case in component)))
        identities.update({case["id"]: group for case in component})
    return [identities[case["id"]] for case in cases]


def partition_cases(cases, train_until, validation_until):
    """Purge groups crossing time boundaries; never split one repair family."""
    first, second = timestamp(train_until), timestamp(validation_until)
    if first > second:
        raise ValueError("ordered time cutoffs required")
    groups = source_groups(cases)
    partitions = {name: [] for name in ("train", "validation", "future", "purged")}
    for values in groups:
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
        first_observed = failed.get("created_at")
        observed = first_observed or failed["updated_at"]
        resolved = passed["updated_at"]
        attempts = [run.get("run_attempt") for run in (failed, passed)]
        if any(
            value is not None and (type(value) is not int or value < 1)
            for value in attempts
        ):
            raise ValueError("positive run attempts or explicit unknown required")
        if timestamp(observed) > timestamp(failed["updated_at"]):
            raise ValueError("failure creation follows its last update")
        if timestamp(observed) > timestamp(resolved):
            raise ValueError("verification predates failure")
        record = {
            k: entry[k]
            for k in ("id", "root_cause", "repair_id", "repair_text", "previously_seen")
        }
        record.update(
            project=project,
            observed_at=observed,
            first_observed_at=first_observed,
            observation_time_basis="run_created_at"
            if first_observed
            else "unknown_first_seen",
            failed_updated_at=failed["updated_at"],
            failed_run_attempt=attempts[0],
            success_run_attempt=attempts[1],
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
            repair_patch_sha256=repair_patch_digest(commit),
            prospective_at_registration=first_observed is not None
            and attempts[0] is not None
            and timestamp(first_observed) > registered
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
        schema="hepta.domain.dataset.v2",
        cases=records,
        partitions=partitions,
        manifest_sha256=sha(original),
        registered_at=manifest["registered_at"],
        source_bytes=sum(map(len, sources.values())),
        source_inventory={key: len(raw) for key, raw in sources.items()},
        scope="hepta-ci-domain-development",
        independent_groups=len(source_groups(records)),
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
    if data["schema"] != "hepta.domain.dataset.v2":
        raise ValueError(
            "unsupported dataset: rebuild legacy partitions from original sources"
        )
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
    # A valid byte pin does not make legacy or manually reassigned partitions
    # independent. Recompute over the entire census before selecting train rows.
    original = json.loads(manifest)
    entries = {entry["id"]: entry for entry in original["cases"]}
    case_ids = [case["id"] for case in data["cases"]]
    if len(set(case_ids)) != len(case_ids) or set(case_ids) != set(entries):
        raise ValueError("dataset differs from complete original incident census")
    expected = partition_cases(
        data["cases"], original["train_until"], original["validation_until"]
    )
    if data["partitions"] != expected or data["independent_groups"] != len(
        source_groups(data["cases"])
    ):
        raise ValueError("dataset source components or temporal partitions changed")
    raw_runs = json.loads(
        (Path(path).parent / "evidence" / original["runs"]["sha256"]).read_bytes()
    )
    runs = raw_runs["workflow_runs"] if isinstance(raw_runs, dict) else raw_runs
    by_id = {run["id"]: run for run in runs}
    prospective = []
    for case in data["cases"]:
        entry = entries[case["id"]]
        failed = by_id[entry["failed_run_id"]]
        passed = by_id[entry["success_run_id"]]
        commit = json.loads(
            (Path(path).parent / "evidence" / entry["fix"]["sha256"]).read_bytes()
        )
        ancestry = dict(
            failed_run_id=failed["id"],
            success_run_id=passed["id"],
            failed_commit=failed["head_sha"],
            fixed_commit=commit["sha"],
            project=failed["repository"]["full_name"],
            failure_log_sha256=entry["failure_log"]["sha256"],
            success_log_sha256=entry["success_log"]["sha256"],
            commit_evidence_sha256=entry["fix"]["sha256"],
            repair_patch_sha256=repair_patch_digest(commit),
            resolved_at=passed["updated_at"],
        )
        ancestry.update(
            {key: entry[key] for key in ("root_cause", "symptom", "previously_seen")}
        )
        if any(case[key] != value for key, value in ancestry.items()):
            raise ValueError("dataset ancestry differs from original incident sources")
        first_seen = failed.get("created_at")
        observed = first_seen or failed["updated_at"]
        prospective_case = bool(
            first_seen is not None
            and failed.get("run_attempt") is not None
            and timestamp(first_seen) > timestamp(original["registered_at"])
            and not case["previously_seen"]
        )
        if (
            case["first_observed_at"],
            case["observed_at"],
            case["failed_run_attempt"],
            case["prospective_at_registration"],
        ) != (first_seen, observed, failed.get("run_attempt"), prospective_case):
            raise ValueError("dataset first observation differs from original run")
        if case["id"] in expected["future"] and prospective_case:
            prospective.append(case["id"])
    if data["prospective_cases"] != prospective:
        raise ValueError("dataset prospective census changed")
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
