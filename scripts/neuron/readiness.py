#!/usr/bin/env python3
"""Deterministic neuron.runtime projections and same-candidate qualification evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

import readiness_evidence as provenance


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SPEC = ROOT / "docs/modules/neuron.runtime/MODULE_SPEC.json"
PROVENANCE_SCHEMA = "hepta.neuron.runtime.qualification-provenance.v2"
MANIFEST_SCHEMA = "hepta.neuron.runtime.readiness-manifest.v2"


class ReadinessError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_json(path: Path) -> dict[str, Any]:
    try:
        return provenance.read_json(path)
    except (OSError, ValueError, RecursionError) as error:
        raise ReadinessError(f"cannot read {path}: {error}") from error


def write_text(path: Path, content: str, check: bool) -> None:
    if not content.endswith("\n"):
        content += "\n"
    if check:
        try:
            current = path.read_text()
        except OSError as error:
            raise ReadinessError(f"generated projection is missing: {path}") from error
        if current != content:
            raise ReadinessError(
                f"generated projection is stale: {path.relative_to(ROOT)}; "
                "run scripts/neuron/readiness.py render"
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def tree_hash(paths: Iterable[Path]) -> str:
    records: list[dict[str, str]] = []
    for path in sorted(
        (item.resolve() for item in paths), key=lambda item: relative(item)
    ):
        if not path.is_file():
            raise ReadinessError(f"bound source is missing: {relative(path)}")
        records.append({"path": relative(path), "sha256": file_sha256(path)})
    return sha256_bytes(canonical_bytes(records))


def run_git(*args: str) -> str:
    try:
        return provenance.git(ROOT, *args)
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReadinessError(f"git {' '.join(args)} failed: {error}") from error


def gate_by_id(spec: dict[str, Any], gate_id: str) -> dict[str, Any]:
    for gate in spec["qualification"]["requiredGates"]:
        if gate["id"] == gate_id:
            return gate
    raise ReadinessError(f"unknown qualification gate: {gate_id}")


def gate_test_set_hash(spec: dict[str, Any], gate: dict[str, Any]) -> str:
    command_sets = spec["qualification"]["commandSets"]
    selected = {name: command_sets[name] for name in gate["commandSets"]}
    value = {
        "module": spec["module"],
        "testSetVersion": spec["qualification"]["testSetVersion"],
        "gate": gate,
        "commands": selected,
        "requirements": spec["requirements"],
    }
    return sha256_bytes(canonical_bytes(value))


def render_implementation_map(spec: dict[str, Any], source: str) -> str:
    projection = {
        "schema": "hepta.module-implementation-map.v4",
        "schemaVersion": 4,
        "generatedFrom": source,
        "module": spec["module"],
        "owner": spec["owner"],
        "deputy": spec["deputy"],
        "sourceRoots": spec["sourceRoots"],
        "operations": [
            {
                "operation": item["id"],
                "nativeSymbol": item["symbol"],
                "sourcePath": item["source"],
                "state": item["state"],
                "authority": item["authority"],
                "tests": item["tests"],
            }
            for item in spec["operations"]
        ],
        "claimBoundary": spec["claimBoundary"],
        "qualification": {
            "workflow": spec["qualification"]["workflow"],
            "requiredGates": [
                item["id"] for item in spec["qualification"]["requiredGates"]
            ],
            "productionActivation": False,
        },
    }
    return json.dumps(projection, indent=2) + "\n"


def render_requirement_matrix(spec: dict[str, Any], source: str) -> str:
    value = {
        "schema": "hepta.neuron.runtime.requirement-test-matrix.v1",
        "generatedFrom": source,
        "module": spec["module"],
        "requirements": spec["requirements"],
    }
    return json.dumps(value, indent=2) + "\n"


def render_activation(spec: dict[str, Any], source: str) -> str:
    value = {
        "schema": "hepta.neuron.runtime.production-activation.v1",
        "generatedFrom": source,
        "module": spec["module"],
        "productionActivation": False,
        "release": False,
        "reason": (
            "Source implementation is not deployment authorization. Activation remains "
            "false until every same-candidate qualification gate, product execution, "
            "independent acceptance, canary, promotion and release authorization pass."
        ),
        "requiredQualificationGates": [
            gate["id"] for gate in spec["qualification"]["requiredGates"]
        ],
        "externalGates": [
            "authenticated target-host product execution",
            "calibration, OOD, retention and deletion non-resurrection acceptance",
            "independent semantic and operator acceptance",
            "canary, promotion and release authorization",
        ],
    }
    return json.dumps(value, indent=2) + "\n"


def render_docs_index(spec: dict[str, Any], source: str) -> str:
    lines = [
        "# neuron.runtime documentation index",
        "",
        f"Generated from `{source}`. Do not edit this projection directly.",
        "",
    ]
    index_parent = (ROOT / spec["paths"]["docsIndex"]).parent
    for item in spec["documents"]:
        target = Path(os.path.relpath(ROOT / item["path"], index_parent)).as_posix()
        lines.append(f"- [`{item['path']}`]({target}) — {item['role']}")
    lines += [
        "",
        "## Generated control surfaces",
        "",
        f"- `{spec['paths']['implementationMap']}`",
        f"- `{spec['paths']['readinessDashboard']}`",
        f"- `{spec['paths']['requirementTestMatrix']}`",
        f"- `{spec['paths']['productionActivation']}`",
        "",
    ]
    return "\n".join(lines)


def render_dashboard(spec: dict[str, Any], source: str) -> str:
    lines = [
        "# neuron.runtime readiness dashboard",
        "",
        f"Generated from `{source}`. Runtime evidence is emitted by "
        f"`{spec['qualification']['workflow']}`.",
        "",
        "**Production activation: false.** Passing source qualification is necessary "
        "but does not authorize product activation or release.",
        "",
        "| Gate | Runner | Platform | Toolchain | Candidate |",
        "|---|---|---|---|---|",
    ]
    for gate in spec["qualification"]["requiredGates"]:
        lines.append(
            f"| `{gate['id']}` | `{gate['runner']}` | `{gate['platform']}` | "
            f"`{gate['toolchain']}` | `{gate['lane']}` |"
        )
    lines += [
        "",
        "Every gate emits a provenance record binding the exact source and tested tree "
        "to the workflow run, target triple, runner fingerprint, test-set hash, "
        "`Cargo.lock`, documentation and generated implementation map.",
        "",
        "The aggregate `READINESS_MANIFEST.json` is an immutable workflow artifact. "
        "It rejects mixed SHAs, mixed integration bases, stale generated projections, "
        "missing target evidence and failed gates. Provenance v2 checks exact Git "
        "objects, actual compiler/target, one workflow run/attempt and every required "
        "stage. Metadata consistency is not remote attestation: the workflow must "
        "also require all matrix jobs, download and aggregation to succeed.",
        "",
        "## Performance policy",
        "",
        "Concurrency levels: "
        + ", ".join(
            str(value) for value in spec["performanceQualification"]["concurrency"]
        )
        + ".",
        "",
        "No lock-topology refactor is authorized without retained p95/p99 evidence of "
        "head-of-line blocking.",
        "",
    ]
    return "\n".join(lines)


def render_runbook_errors(spec: dict[str, Any], source: str) -> str:
    lines = [
        "# neuron.runtime generated error actions",
        "",
        f"Generated from `{source}`. Stable codes remain low-cardinality; retained "
        "evidence must carry the internal stage and correlation identity.",
        "",
        "| Stable code | Required operator action |",
        "|---|---|",
    ]
    for item in spec["errorCodes"]:
        lines.append(f"| `{item['code']}` | {item['action']} |")
    lines.append("")
    return "\n".join(lines)


def render(spec_path: Path, check: bool) -> None:
    spec = load_json(spec_path)
    tree_hash(ROOT / item["path"] for item in spec["documents"])
    source = relative(spec_path)
    outputs = {
        spec["paths"]["implementationMap"]: render_implementation_map(spec, source),
        spec["paths"]["readinessDashboard"]: render_dashboard(spec, source),
        spec["paths"]["requirementTestMatrix"]: render_requirement_matrix(spec, source),
        spec["paths"]["productionActivation"]: render_activation(spec, source),
        spec["paths"]["docsIndex"]: render_docs_index(spec, source),
        "docs/modules/neuron.runtime/ERROR_ACTIONS.generated.md": render_runbook_errors(
            spec, source
        ),
    }
    for name, content in outputs.items():
        write_text(ROOT / name, content, check)


def required_stages(gate: dict[str, Any]) -> list[str]:
    return (
        ["candidate", "tools", "validate"]
        + (["compiler"] if gate["toolchain"] == "msrv" else [])
        + (["frozen"] if "linuxFrozen" in gate["commandSets"] else [])
    )


def candidate_bindings(spec, spec_path, tested_sha):
    def digest(path):
        # Read exact Git blobs, not another lane's checkout or an edited file.
        return sha256_bytes(provenance.git_blob(ROOT, tested_sha, path))

    docs = [
        {"path": item["path"], "sha256": digest(item["path"])}
        for item in sorted(spec["documents"], key=lambda item: item["path"])
    ]
    return {
        "specSha256": digest(relative(spec_path)),
        "cargoLockSha256": digest("codex-rs/Cargo.lock"),
        "documentationSha256": sha256_bytes(canonical_bytes(docs)),
        "implementationMapSha256": digest(spec["paths"]["implementationMap"]),
        "workflowSha256": digest(spec["qualification"]["workflow"]),
        "validatorSha256": digest("scripts/neuron/readiness.py"),
        "provenanceValidatorSha256": digest("scripts/neuron/readiness_evidence.py"),
    }


def capture(args: argparse.Namespace) -> None:
    spec_path = args.spec.resolve()
    spec = load_json(spec_path)
    gate = gate_by_id(spec, args.gate)
    if args.lane != gate["lane"]:
        raise ReadinessError(
            f"gate {args.gate} requires lane {gate['lane']}, got {args.lane}"
        )
    if args.toolchain != gate["toolchain"]:
        raise ReadinessError(
            f"gate {args.gate} requires toolchain {gate['toolchain']}, got {args.toolchain}"
        )

    tested_sha = args.tested_sha or run_git("rev-parse", "HEAD")
    tree_sha = args.tree_sha or run_git("rev-parse", "HEAD^{tree}")
    objects = provenance.candidate(ROOT, args.source_sha, args.base_sha)
    if (tested_sha, tree_sha) != objects[args.lane]:
        raise ReadinessError("captured identity differs from the exact candidate lane")
    provenance.clean_checkout(ROOT, tested_sha, tree_sha)
    render(spec_path, check=True)
    observed_rust = provenance.actual_rust(ROOT)
    target = args.target_triple or observed_rust["host"]
    expected_target = provenance.PLATFORMS[gate["platform"]][2]
    if (
        target != observed_rust["host"]
        or target != expected_target
        or observed_rust["release"] != spec["toolchains"][args.toolchain]
    ):
        raise ReadinessError("actual compiler/target differs from the requested gate")
    stages = json.loads(args.stage_outcomes)
    if not isinstance(stages, dict) or set(stages) != set(required_stages(gate)):
        raise ReadinessError(
            "required workflow stage outcomes are missing or unexpected"
        )
    if any(
        value not in ("success", "failure", "cancelled", "skipped")
        for value in stages.values()
    ):
        raise ReadinessError("invalid workflow stage outcome")
    runner = {
        "name": args.runner_name or os.environ.get("RUNNER_NAME", "unknown"),
        "os": args.runner_os or os.environ.get("RUNNER_OS", platform.system()),
        "arch": args.runner_arch or os.environ.get("RUNNER_ARCH", platform.machine()),
        "image": args.runner_image
        or os.environ.get("ImageOS")
        or os.environ.get("ImageVersion")
        or "unknown",
        "environment": os.environ.get("RUNNER_ENVIRONMENT", "unknown"),
        "kernel": platform.platform(),
        "python": platform.python_version(),
        "targetTriple": target,
    }
    runner["fingerprintSha256"] = sha256_bytes(canonical_bytes(runner))

    result = args.result.lower()
    if result not in {"success", "failure", "cancelled", "skipped"}:
        raise ReadinessError(f"unsupported result: {args.result}")
    if result == "success" and any(value != "success" for value in stages.values()):
        raise ReadinessError(
            "successful provenance requires every workflow stage to succeed"
        )
    evidence = {
        "schema": PROVENANCE_SCHEMA,
        "observedRust": observed_rust,
        "stageOutcomes": stages,
        "module": spec["module"],
        "gate": args.gate,
        "result": result,
        "sourceSha": args.source_sha,
        "testedSha": tested_sha,
        "testedTree": tree_sha,
        "baseSha": args.base_sha,
        "lane": args.lane,
        "platform": gate["platform"],
        "toolchain": {
            "class": args.toolchain,
            "version": spec["toolchains"][args.toolchain],
        },
        "workflow": {
            "name": args.workflow,
            "runId": str(args.run_id),
            "runAttempt": str(args.run_attempt),
            "job": args.job,
            "repository": args.repository,
        },
        "runner": runner,
        "bindings": {
            **candidate_bindings(spec, spec_path, tested_sha),
            "testSetSha256": gate_test_set_hash(spec, gate),
        },
        "claimBoundary": {
            "qualificationGatePassed": result == "success",
            "productionActivation": False,
            "release": False,
        },
    }
    context = {
        "sourceSha": args.source_sha,
        "baseSha": args.base_sha,
        "name": args.workflow,
        "repository": args.repository,
        "runId": str(args.run_id),
        "runAttempt": str(args.run_attempt),
    }
    problems = provenance.check_record(spec, evidence, objects, context)
    if problems:
        raise ReadinessError("; ".join(problems))
    provenance.clean_checkout(ROOT, tested_sha, tree_sha)
    if args.output.resolve().is_relative_to(ROOT.resolve()):
        raise ReadinessError("evidence output must be outside the checked source")
    provenance.publish(args.output, evidence)


def validate_evidence(spec, spec_path, evidence, objects, context) -> list[str]:
    if evidence.get("schema") != PROVENANCE_SCHEMA:
        return ["invalid provenance schema; historical v1 is not current qualification"]
    errors = provenance.check_record(spec, evidence, objects, context)
    try:
        gate = gate_by_id(spec, str(evidence.get("gate")))
    except ReadinessError as error:
        return errors + [str(error)]
    expected = candidate_bindings(spec, spec_path, objects[gate["lane"]][0])
    expected["testSetSha256"] = gate_test_set_hash(spec, gate)
    if evidence.get("bindings") != expected:
        errors.append("source bindings differ from exact tested candidate")
    if evidence.get("stageOutcomes") != {
        stage: "success" for stage in required_stages(gate)
    }:
        errors.append("required workflow stages did not all succeed")
    if evidence.get("result") != "success":
        errors.append(f"gate result is {evidence.get('result')}")
    return errors


def record_object(records, gate, key):
    value = records.get(gate, {}).get(key)
    return value if isinstance(value, dict) else {}


def aggregate(args: argparse.Namespace) -> None:
    spec_path = args.spec.resolve()
    spec = load_json(spec_path)
    provenance.clean_checkout(
        ROOT, args.source_sha, run_git("rev-parse", args.source_sha + "^{tree}")
    )
    render(spec_path, check=True)
    objects = provenance.candidate(ROOT, args.source_sha, args.base_sha)
    context = {
        "sourceSha": args.source_sha,
        "baseSha": args.base_sha,
        "name": args.workflow,
        "repository": args.repository,
        "runId": str(args.run_id),
        "runAttempt": str(args.run_attempt),
    }
    evidence_files = sorted(args.evidence_dir.rglob("*.provenance.json"))
    if len(evidence_files) > 64:
        raise ReadinessError("evidence record limit exceeded")
    records: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    if args.qualification_outcome != "success":
        errors.append(f"qualification matrix is {args.qualification_outcome}")
    if args.download_outcome != "success":
        errors.append(f"artifact download is {args.download_outcome}")
    for path in evidence_files:
        try:
            record = load_json(path)
        except ReadinessError as error:
            errors.append(str(error))
            continue
        gate = str(record.get("gate", ""))
        if gate in records:
            errors.append(f"duplicate evidence for gate {gate}")
            continue
        records[gate] = record
        errors.extend(validate_evidence(spec, spec_path, record, objects, context))

    expected = [gate["id"] for gate in spec["qualification"]["requiredGates"]]
    missing = [gate for gate in expected if gate not in records]
    errors.extend(f"missing evidence for gate {gate}" for gate in missing)

    source_shas = {
        record["sourceSha"]
        for record in records.values()
        if isinstance(record.get("sourceSha"), str)
    }
    base_shas = {
        record["baseSha"]
        for record in records.values()
        if isinstance(record.get("baseSha"), str)
    }
    if len(source_shas) > 1:
        errors.append("mixed source SHAs in readiness evidence")
    if len(base_shas) > 1:
        errors.append("mixed integration base SHAs in readiness evidence")
    if args.source_sha and source_shas and source_shas != {args.source_sha}:
        errors.append("evidence source SHA does not match requested candidate")
    if args.base_sha and base_shas and base_shas != {args.base_sha}:
        errors.append("evidence base SHA does not match requested integration base")

    ready = not errors and len(records) == len(expected)
    generated_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "module": spec["module"],
        "generatedAt": generated_at,
        "sourceSha": next(iter(source_shas)) if len(source_shas) == 1 else None,
        "baseSha": next(iter(base_shas)) if len(base_shas) == 1 else None,
        "qualificationReady": ready,
        "workflowContext": context,
        "workflowOutcomes": {
            "qualification": args.qualification_outcome,
            "download": args.download_outcome,
        },
        "evidenceAuthentication": "trusted-workflow-job-results-required",
        "hostedExecutionIndependentlyVerified": False,
        "inputEvidence": [
            {
                "path": str(path.relative_to(args.evidence_dir)),
                "sha256": file_sha256(path),
            }
            for path in evidence_files
        ],
        "productionActivation": False,
        "release": False,
        "gates": [
            {
                "id": gate,
                "result": records.get(gate, {}).get("result", "missing"),
                "workflowRunId": record_object(records, gate, "workflow").get("runId"),
                "targetTriple": record_object(records, gate, "runner").get(
                    "targetTriple"
                ),
                "runnerFingerprintSha256": record_object(records, gate, "runner").get(
                    "fingerprintSha256"
                ),
                "testSetSha256": record_object(records, gate, "bindings").get(
                    "testSetSha256"
                ),
            }
            for gate in expected
        ],
        "blockers": sorted(set(errors)),
        "claimBoundary": {
            "sourceQualification": ready,
            "productExecutionProved": False,
            "independentAcceptance": False,
            "productionActivation": False,
            "release": False,
        },
    }
    provenance.clean_checkout(ROOT, args.source_sha, objects["source-head"][1])
    if args.output.resolve().is_relative_to(ROOT.resolve()):
        raise ReadinessError("evidence output must be outside the checked source")
    provenance.publish(args.output, manifest)
    if not ready and not args.allow_incomplete:
        raise ReadinessError("; ".join(manifest["blockers"]))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command", required=True)

    render_parser = sub.add_parser("render")
    render_parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    render_parser.add_argument("--check", action="store_true")

    capture_parser = sub.add_parser("capture")
    capture_parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    capture_parser.add_argument("--gate", required=True)
    capture_parser.add_argument("--source-sha", required=True)
    capture_parser.add_argument("--base-sha", required=True)
    capture_parser.add_argument("--tested-sha")
    capture_parser.add_argument("--tree-sha")
    capture_parser.add_argument("--lane", required=True)
    capture_parser.add_argument(
        "--toolchain", choices=("stable", "msrv"), required=True
    )
    capture_parser.add_argument("--target-triple")
    capture_parser.add_argument("--workflow", required=True)
    capture_parser.add_argument("--run-id", required=True)
    capture_parser.add_argument("--run-attempt", required=True)
    capture_parser.add_argument("--job", required=True)
    capture_parser.add_argument("--repository", required=True)
    capture_parser.add_argument("--runner-name")
    capture_parser.add_argument("--runner-os")
    capture_parser.add_argument("--runner-arch")
    capture_parser.add_argument("--runner-image")
    capture_parser.add_argument("--stage-outcomes", required=True)
    capture_parser.add_argument("--result", required=True)
    capture_parser.add_argument("--output", type=Path, required=True)

    aggregate_parser = sub.add_parser("aggregate")
    aggregate_parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    aggregate_parser.add_argument("--evidence-dir", type=Path, required=True)
    aggregate_parser.add_argument("--source-sha", required=True)
    aggregate_parser.add_argument("--base-sha", required=True)
    for flag in ("workflow", "run-id", "run-attempt", "repository"):
        aggregate_parser.add_argument("--" + flag, required=True)
    for flag in ("qualification-outcome", "download-outcome"):
        aggregate_parser.add_argument(
            "--" + flag,
            choices=("success", "failure", "cancelled", "skipped"),
            required=True,
        )
    aggregate_parser.add_argument("--output", type=Path, required=True)
    aggregate_parser.add_argument("--allow-incomplete", action="store_true")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "render":
            render(args.spec, args.check)
        elif args.command == "capture":
            capture(args)
        elif args.command == "aggregate":
            aggregate(args)
        else:
            raise AssertionError(args.command)
    except (
        ReadinessError,
        ValueError,
        OSError,
        KeyError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"neuron readiness: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
