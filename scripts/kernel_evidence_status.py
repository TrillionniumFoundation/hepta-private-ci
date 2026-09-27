#!/usr/bin/env python3
"""Build candidate-bound evidence status; execution is not deployment acceptance.

A positive lane needs successful checks, exact command/log records and a durable
artifact digest. An aggregate additionally verifies both lane receipts, their
run/attempt identity, and downloaded record hashes. Generated prose is a view of
one immutable status artifact, never a commit that invalidates its own source SHA.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from typing import Any

HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_OUTCOMES = {"success", "failure", "cancelled", "skipped"}
EVENTS = {"pull_request", "push", "workflow_dispatch"}
COMMANDS = {
    "evidence_tests": ("evidence-tests.json", ["bash", "-lc", "cd codex-rs && cargo test --locked -p codex-hepta-evidence"], 1),
    "agentd_product_test": ("agentd-product-test.json", ["bash", "-lc", "cd codex-rs && cargo test --locked -p codex-hepta-agentd --test kernel_evidence_product"], 1),
    "production_policy_tests": ("production-policy-tests.json", ["bash", "-lc", "cd codex-rs && cargo test --locked -p codex-hepta-agentd --test kernel_evidence_production_policy"], 1),
    "status_tests": ("status-tests.json", ["python3", "-m", "unittest", "discover", "-s", "scripts/tests", "-p", "test_kernel_evidence*.py", "-v"], 1),
    "lane_a_truth": ("lane-a-truth.json", ["python3", "scripts/verify_lane_a_foundation.py", "verify"], 0),
    "docs": ("docs.json", ["python3", "scripts/hepta-docs.py", "verify"], 0),
    "implementation_maps": ("implementation-maps.json", ["python3", "scripts/hepta-implementation-maps.py", "verify"], 0),
}
REQUIRED_LANE_CHECKS = ("candidate_identity", "setup_ci", "rust_toolchain", *COMMANDS)
LIFECYCLE_FLAGS = ("independentAcceptance", "externalFrontierActive", "backupRestoreDrilled", "canaryAccepted", "releaseApproved")
BOOL_FIELDS = ("exactSourceQualified", "mergeCandidateRequired", "mergeCandidateQualified", "allRequiredQualificationLanesPassed", *LIFECYCLE_FLAGS)
DOC_PATHS = (
    "docs/modules/kernel.evidence/TECHNICAL.md",
    "docs/lane-a-foundation/kernel.evidence/CURRENT_IMPLEMENTATION.md",
    "qualification/kernel-evidence/TRACEABILITY.md",
    "qualification/module-execution-dossiers/detail/kernel.evidence.md",
    "qualification/kernel-evidence/RELEASE_DASHBOARD.md",
)
BEGIN = "<!-- kernel.evidence:canonical-status:begin -->"
END = "<!-- kernel.evidence:canonical-status:end -->"


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hex(value: Any, size: int, label: str) -> str:
    pattern = HEX_40 if size == 40 else HEX_64
    if not isinstance(value, str) or not pattern.fullmatch(value) or set(value) == {"0"}:
        raise ValueError(f"{label} must be a nonzero lowercase {size}-character digest")
    return value


def _positive_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", value) or int(value) > 2**64 - 1:
        raise ValueError(f"{label} must be a positive decimal u64 string")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _load(path: pathlib.Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError(f"missing, linked or oversized JSON: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError("a JSON object is required")
    return value


def _write_json(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".evidence-status-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _parse_checks(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        name, separator, outcome = value.partition("=")
        if not separator or not name or name in result:
            raise ValueError(f"invalid or duplicate --check: {value!r}")
        outcome = outcome or "skipped"
        if outcome not in ALLOWED_OUTCOMES:
            raise ValueError(f"invalid outcome: {outcome!r}")
        result[name] = outcome
    return result


def _validate_git_identity(commit: str, tree: str, parents: list[str]) -> None:
    _hex(commit, 40, "commit")
    _hex(tree, 40, "tree")
    if not isinstance(parents, list):
        raise ValueError("parents must be an array")
    for parent in parents:
        _hex(parent, 40, "parent")


def _records(directory: pathlib.Path, output: pathlib.Path) -> list[dict[str, Any]]:
    result = []
    if not directory.is_dir():
        return result
    for path in sorted(directory.iterdir()):
        if path.resolve() == output.resolve():
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"record is not a regular file: {path.name}")
        if path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError(f"record exceeds 64 MiB: {path.name}")
        result.append({"name": path.name, "bytes": path.stat().st_size, "sha256": _sha256(path)})
    return result


def _safe_record(directory: pathlib.Path, name: Any) -> pathlib.Path:
    if not isinstance(name, str) or not name or pathlib.Path(name).name != name or name in {".", ".."} or "\\" in name:
        raise ValueError("record name must be a basename")
    path = directory / name
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(directory.resolve()):
        raise ValueError(f"record is absent or outside the record directory: {name}")
    return path


def validate_execution_records(directory: pathlib.Path, status: dict[str, Any]) -> None:
    candidate = _load(_safe_record(directory, "candidate.json"))
    kind = "kernel_evidence_exact_source" if status["lane"] == "source-head" else "kernel_evidence_synthetic_merge"
    if type(candidate.get("schemaVersion")) is not int or candidate != {"schemaVersion": 1, "kind": kind, "commit": status["asOfCommit"], "tree": status["asOfTree"], "parents": status["parents"]}:
        raise ValueError("candidate identity record does not match the lane")
    for label, (filename, command, minimum_tests) in COMMANDS.items():
        record = _load(_safe_record(directory, filename))
        if type(record.get("schema_version")) is not int or record.get("schema_version") != 1 or record.get("status") != "passed" or record.get("command") != command:
            raise ValueError(f"{label}: incorrect command, schema or terminal outcome")
        for field in ("exit_code", "command_exit_code", "returncode", "observed_failed_tests"):
            if type(record.get(field)) is not int or record[field] != 0:
                raise ValueError(f"{label}: {field} must be integer zero")
        for field in ("timed_out", "output_limit_exceeded"):
            if record.get(field) is not False:
                raise ValueError(f"{label}: {field} is not false")
        passed = record.get("observed_passed_tests")
        if type(passed) is not int or passed < minimum_tests:
            raise ValueError(f"{label}: no sufficient observed passing tests")
        for field, expected in (("run_id", status["workflowRunId"]), ("run_attempt", status["workflowRunAttempt"]), ("source_sha", status["sourceCommit"]), ("tested_sha", status["asOfCommit"]), ("lane", status["lane"]), ("base_sha", status["baseCommit"] or "")):
            if record.get(field) != expected:
                raise ValueError(f"{label}: {field} does not match the lane")
        for boundary in ("before", "after"):
            identity = record.get(boundary, {})
            if not isinstance(identity, dict) or any(identity.get(key) != status[target] for key, target in (("commit", "asOfCommit"), ("tree", "asOfTree"), ("parents", "parents"))) or identity.get("dirty") is not False:
                raise ValueError(f"{label}: source mutation or identity drift at {boundary}")
        log = _safe_record(directory, record.get("log_file"))
        if type(record.get("log_bytes")) is not int or log.stat().st_size != record["log_bytes"]:
            raise ValueError(f"{label}: log byte count mismatch")
        if _sha256(log) != _hex(record.get("log_sha256"), 64, "log digest"):
            raise ValueError(f"{label}: log digest mismatch")


def _run_identity(args: argparse.Namespace) -> dict[str, Any]:
    if args.event_name not in EVENTS or not args.workflow_ref or "\n" in args.workflow_ref:
        raise ValueError("unsupported event or empty workflow identity")
    return {"workflowRunId": _positive_id(args.workflow_run_id, "run id"), "workflowRunAttempt": _positive_id(args.workflow_run_attempt, "run attempt"), "workflowRef": args.workflow_ref, "eventName": args.event_name}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _output(path: str | None, qualified: bool, **values: str) -> None:
    if path:
        with pathlib.Path(path).open("a", encoding="utf-8") as stream:
            stream.write(f"qualified={str(qualified).lower()}\n")
            for key, value in values.items():
                if "\n" in value or "\r" in value:
                    raise ValueError("multiline GitHub output is forbidden")
                stream.write(f"{key}={value}\n")


def build_lane(args: argparse.Namespace) -> int:
    checks = _parse_checks(args.check)
    parents = json.loads(args.parents_json)
    _validate_git_identity(args.commit, args.tree, parents)
    source = _hex(args.source_commit or args.commit, 40, "source commit")
    expected_kind = {"source-head": "exact-source", "base-merge": "synthetic-merge"}.get(args.lane)
    if expected_kind is None or expected_kind != args.candidate_kind:
        raise ValueError("candidate kind and lane do not match")
    base = args.base_commit or None
    if args.lane == "source-head" and source != args.commit:
        raise ValueError("exact-source lane changed the candidate commit")
    if args.lane == "base-merge":
        _hex(base, 40, "base commit")
        if parents != [base, source]:
            raise ValueError("synthetic merge must have the exact base/source parents")
    status = {"schemaVersion": 1, "module": "kernel.evidence", "statusKind": "qualification-lane", "lane": args.lane, "candidateKind": args.candidate_kind, "asOfCommit": args.commit, "asOfTree": args.tree, "parents": parents, "sourceCommit": source, "baseCommit": base, **_run_identity(args), "generatedAt": _now(), "checks": {name: {"outcome": checks.get(name, "skipped")} for name in REQUIRED_LANE_CHECKS}}
    errors = []
    if set(checks) != set(REQUIRED_LANE_CHECKS) or any(value != "success" for value in checks.values()):
        errors.append("required checks are missing, extra or not successful")
    digest = args.artifact_digest or None
    try:
        _hex(digest, 64, "durable artifact digest")
    except ValueError as error:
        errors.append(str(error))
        digest = None
    status["artifact"] = {"name": args.artifact_name, "sha256": digest, "durableAcknowledgement": digest is not None}
    directory, output = pathlib.Path(args.records_dir), pathlib.Path(args.output)
    try:
        validate_execution_records(directory, status)
        status["records"] = _records(directory, output)
    except (OSError, ValueError, KeyError, TypeError) as error:
        errors.append(str(error))
        status["records"] = []
    status["validationErrors"] = errors
    status["qualified"] = not errors
    _write_json(output, status)
    _output(args.github_output, status["qualified"], commit=args.commit, tree=args.tree)
    return 0


def _bool_text(value: str) -> bool:
    if value == "true":
        return True
    if value in {"false", "", "null"}:
        return False
    raise ValueError(f"expected true or false, got {value!r}")


def validate_lane_receipt(path: pathlib.Path, args: argparse.Namespace, lane: str, digest: str | None) -> dict[str, Any]:
    value = _load(path)
    if type(value.get("schemaVersion")) is not int or value["schemaVersion"] != 1 or value.get("module") != "kernel.evidence" or value.get("statusKind") != "qualification-lane" or value.get("lane") != lane or value.get("qualified") is not True or value.get("validationErrors") != []:
        raise ValueError(f"{lane}: not a qualified terminal lane receipt")
    for field, expected in _run_identity(args).items():
        if value.get(field) != expected:
            raise ValueError(f"{lane}: mismatched {field}")
    _validate_git_identity(value.get("asOfCommit"), value.get("asOfTree"), value.get("parents"))
    if value.get("sourceCommit") != args.source_commit:
        raise ValueError(f"{lane}: mismatched source commit")
    if lane == "source-head":
        if value["asOfCommit"] != args.source_commit or value["asOfTree"] != args.source_tree or value.get("candidateKind") != "exact-source":
            raise ValueError("exact-source candidate identity mismatch")
    else:
        if value.get("candidateKind") != "synthetic-merge" or value.get("baseCommit") != args.base_commit or value["parents"] != [args.base_commit, args.source_commit]:
            raise ValueError("merge candidate parent identity mismatch")
        result = subprocess.run(["git", "merge-tree", "--write-tree", args.base_commit, args.source_commit], capture_output=True, text=True, timeout=60, check=True)
        if not result.stdout.splitlines() or result.stdout.splitlines()[0] != value["asOfTree"]:
            raise ValueError("deterministic merge tree mismatch")
    checks = value.get("checks", {})
    if set(checks) != set(REQUIRED_LANE_CHECKS) or any(checks[key] != {"outcome": "success"} for key in REQUIRED_LANE_CHECKS):
        raise ValueError("lane check coverage or outcomes mismatch")
    artifact = value.get("artifact", {})
    if artifact.get("sha256") != _hex(digest, 64, "expected artifact digest") or artifact.get("durableAcknowledgement") is not True:
        raise ValueError("lane artifact digest or durable acknowledgement mismatch")
    name = artifact.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,256}", name) or name in {".", ".."}:
        raise ValueError("unsafe artifact name")
    directory = pathlib.Path(args.records_root) / name
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("downloaded records artifact is absent or linked")
    manifest = value.get("records")
    if not isinstance(manifest, list) or any(not isinstance(item, dict) or set(item) != {"name", "bytes", "sha256"} or type(item["bytes"]) is not int for item in manifest):
        raise ValueError("invalid record manifest field types")
    if manifest != _records(directory, pathlib.Path(args.output)):
        raise ValueError("downloaded record manifest/digests do not match the receipt")
    validate_execution_records(directory, value)
    return value


def build_aggregate(args: argparse.Namespace) -> int:
    _validate_git_identity(args.source_commit, args.source_tree, [])
    identity = _run_identity(args)
    merge_required = args.event_name == "pull_request"
    if merge_required:
        _hex(args.base_commit, 40, "base commit")
    errors = []
    passed = {"source-head": False, "base-merge": False}
    digests: dict[str, str | None] = {"source-head": None, "base-merge": None}
    receipt_hashes = {}
    for lane, requested, receipt_path, digest in (("source-head", args.source_qualified, args.source_status, args.source_artifact_digest), ("base-merge", args.merge_qualified, args.merge_status, args.merge_artifact_digest)):
        if lane == "base-merge" and not merge_required:
            continue
        try:
            if not _bool_text(requested):
                raise ValueError(f"{lane}: job or lane did not succeed")
            if not receipt_path or not args.records_root:
                raise ValueError(f"{lane}: authenticated downloaded receipts are required")
            validate_lane_receipt(pathlib.Path(receipt_path), args, lane, digest)
            passed[lane] = True
            digests[lane] = digest
            receipt_hashes[lane] = _sha256(pathlib.Path(receipt_path))
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            errors.append(str(error))
    status = {"schemaVersion": 1, "module": "kernel.evidence", "statusKind": "canonical-qualification-status", "asOfCommit": args.source_commit, "asOfTree": args.source_tree, **identity, "generatedAt": _now(), "exactSourceQualified": passed["source-head"], "mergeCandidateRequired": merge_required, "mergeCandidateQualified": passed["base-merge"], "allRequiredQualificationLanesPassed": passed["source-head"] and (passed["base-merge"] or not merge_required), **{flag: False for flag in LIFECYCLE_FLAGS}, "artifacts": {"exactSourceSha256": digests["source-head"], "mergeCandidateSha256": digests["base-merge"]}, "laneReceiptSha256": receipt_hashes, "validationErrors": errors}
    validate_canonical(status)
    _write_json(pathlib.Path(args.output), status)
    _output(args.github_output, status["allRequiredQualificationLanesPassed"])
    return 0


def validate_canonical(value: dict[str, Any]) -> None:
    if type(value.get("schemaVersion")) is not int or value["schemaVersion"] != 1 or value.get("module") != "kernel.evidence" or value.get("statusKind") != "canonical-qualification-status":
        raise ValueError("unsupported canonical status identity")
    _validate_git_identity(value.get("asOfCommit"), value.get("asOfTree"), [])
    _positive_id(value.get("workflowRunId"), "run id")
    _positive_id(value.get("workflowRunAttempt"), "run attempt")
    if value.get("eventName") not in EVENTS or not isinstance(value.get("workflowRef"), str) or not value["workflowRef"]:
        raise ValueError("invalid canonical workflow identity")
    for field in BOOL_FIELDS:
        if type(value.get(field)) is not bool:
            raise ValueError(f"{field} must be a JSON boolean")
    if any(value[field] for field in LIFECYCLE_FLAGS):
        raise ValueError("CI qualification cannot self-issue deployment or independent acceptance")
    if value["mergeCandidateRequired"] != (value["eventName"] == "pull_request") or (not value["mergeCandidateRequired"] and value["mergeCandidateQualified"]):
        raise ValueError("merge applicability mismatch")
    expected = value["exactSourceQualified"] and (value["mergeCandidateQualified"] or not value["mergeCandidateRequired"])
    if value["allRequiredQualificationLanesPassed"] != expected:
        raise ValueError("aggregate qualification contradicts its lanes")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {"exactSourceSha256", "mergeCandidateSha256"}:
        raise ValueError("canonical artifact fields mismatch")
    for flag, digest in (("exactSourceQualified", "exactSourceSha256"), ("mergeCandidateQualified", "mergeCandidateSha256")):
        if value[flag] or artifacts[digest] is not None:
            _hex(artifacts[digest], 64, digest)
    proofs = value.get("laneReceiptSha256")
    expected_lanes = {lane for lane, flag in (("source-head", "exactSourceQualified"), ("base-merge", "mergeCandidateQualified")) if value[flag]}
    if not isinstance(proofs, dict) or set(proofs) != expected_lanes:
        raise ValueError("canonical lane receipt digest coverage mismatch")
    for proof in proofs.values():
        _hex(proof, 64, "lane receipt digest")
    errors = value.get("validationErrors")
    if not isinstance(errors, list) or not all(isinstance(item, str) for item in errors) or (expected and errors):
        raise ValueError("invalid validation error state")
    stamp = value.get("generatedAt")
    if not isinstance(stamp, str) or not stamp.endswith("Z"):
        raise ValueError("generatedAt must be an explicit UTC timestamp")
    dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def verify(args: argparse.Namespace) -> int:
    validate_canonical(_load(pathlib.Path(args.path)))
    return 0


def render(args: argparse.Namespace) -> int:
    path = pathlib.Path(args.path)
    value = _load(path)
    validate_canonical(value)
    source, output = pathlib.Path(args.source_root).resolve(), pathlib.Path(args.output_dir).resolve()
    if output == source or output.is_relative_to(source):
        raise ValueError("generated status views must be outside the qualified source checkout")
    lines = [BEGIN, "## Candidate qualification status", "", f"Source commit: `{value['asOfCommit']}`  ", f"Source tree: `{value['asOfTree']}`  ", f"Workflow run / attempt: `{value['workflowRunId']}` / `{value['workflowRunAttempt']}`  ", f"Canonical JSON SHA-256: `{_sha256(path)}`", "", "| Gate | State |", "|---|---|"]
    lines += [f"| `{key}` | `{str(value[key]).lower()}` |" for key in BOOL_FIELDS]
    lines += ["", "These values apply only to the commit/tree above. CI does not attest external deployment, disaster recovery, independent acceptance, canary or release approval.", END]
    block = "\n".join(lines)
    generated = {}
    for relative in DOC_PATHS:
        original = source / relative
        if original.is_symlink() or not original.resolve().is_relative_to(source):
            raise ValueError("source document must not be a symlink")
        if original.is_file():
            text = original.read_text(encoding="utf-8")
        elif relative.endswith("RELEASE_DASHBOARD.md"):
            text = "# kernel.evidence release dashboard\n"
        else:
            raise ValueError(f"required source document is absent: {relative}")
        if text.count(BEGIN) != text.count(END) or text.count(BEGIN) > 1:
            raise ValueError(f"ambiguous status markers: {relative}")
        if BEGIN in text:
            first, last = text.index(BEGIN), text.index(END)
            if last < first:
                raise ValueError("status markers are reversed")
            text = text[:first] + block + text[last + len(END):]
        else:
            text = text.rstrip() + "\n\n" + block + "\n"
        generated[relative] = text
    for relative, text in generated.items():
        destination = output / relative
        if destination.is_symlink() or not destination.resolve().is_relative_to(output):
            raise ValueError("generated document destination escapes its output directory")
        if args.check:
            if not destination.is_file() or destination.read_text(encoding="utf-8") != text:
                raise ValueError(f"generated documentation drift: {relative}")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    lane = commands.add_parser("lane")
    for name in ("candidate-kind", "lane", "commit", "tree", "parents-json", "artifact-name", "records-dir", "output"):
        lane.add_argument("--" + name, required=True)
    for name in ("source-commit", "base-commit", "github-output"):
        lane.add_argument("--" + name)
    lane.add_argument("--artifact-digest", default="")
    lane.add_argument("--check", action="append", default=[])
    lane.set_defaults(handler=build_lane)
    aggregate = commands.add_parser("aggregate")
    for name in ("source-commit", "source-tree", "source-qualified", "merge-qualified", "output"):
        aggregate.add_argument("--" + name, required=True)
    for name in ("source-status", "merge-status", "records-root", "base-commit", "github-output"):
        aggregate.add_argument("--" + name)
    for name in ("source-artifact-digest", "merge-artifact-digest"):
        aggregate.add_argument("--" + name, default="")
    aggregate.set_defaults(handler=build_aggregate)
    for command in (lane, aggregate):
        for name in ("workflow-run-id", "workflow-run-attempt", "workflow-ref", "event-name"):
            command.add_argument("--" + name, required=True)
    check = commands.add_parser("verify")
    check.add_argument("path")
    check.set_defaults(handler=verify)
    docs = commands.add_parser("render")
    docs.add_argument("path")
    docs.add_argument("--source-root", required=True)
    docs.add_argument("--output-dir", required=True)
    docs.add_argument("--check", action="store_true")
    docs.set_defaults(handler=render)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return args.handler(args)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"kernel.evidence status error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
