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


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SPEC = ROOT / "docs/modules/neuron.runtime/MODULE_SPEC.json"
PROVENANCE_SCHEMA = "hepta.neuron.runtime.qualification-provenance.v1"
MANIFEST_SCHEMA = "hepta.neuron.runtime.readiness-manifest.v1"


class ReadinessError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ReadinessError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise ReadinessError(f"{path} must contain a JSON object")
    return value


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
    for path in sorted((item.resolve() for item in paths), key=lambda item: relative(item)):
        if not path.is_file():
            raise ReadinessError(f"bound source is missing: {relative(path)}")
        records.append({"path": relative(path), "sha256": file_sha256(path)})
    return sha256_bytes(canonical_bytes(records))


def run_git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
        ).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReadinessError(f"git {' '.join(args)} failed: {error}") from error


def rust_host() -> str:
    try:
        output = subprocess.check_output(
            ["rustc", "-Vv"], cwd=ROOT / "codex-rs", text=True
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReadinessError(f"rustc -Vv failed: {error}") from error
    for line in output.splitlines():
        if line.startswith("host: "):
            return line.removeprefix("host: ").strip()
    raise ReadinessError("rustc -Vv did not report a host target")


def spec_hash(spec_path: Path) -> str:
    return file_sha256(spec_path)


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
    for item in spec["documents"]:
        lines.append(
            f"- [`{item['path']}`](../../{item['path'].removeprefix('docs/')}) — {item['role']}"
        )
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
        "missing target evidence and failed gates.",
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
    target = args.target_triple or rust_host()
    docs = [ROOT / item["path"] for item in spec["documents"]]
    implementation_map = ROOT / spec["paths"]["implementationMap"]
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
    evidence = {
        "schema": PROVENANCE_SCHEMA,
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
            "specSha256": spec_hash(spec_path),
            "testSetSha256": gate_test_set_hash(spec, gate),
            "cargoLockSha256": file_sha256(ROOT / "codex-rs/Cargo.lock"),
            "documentationSha256": tree_hash(docs),
            "implementationMapSha256": file_sha256(implementation_map),
        },
        "claimBoundary": {
            "qualificationGatePassed": result == "success",
            "productionActivation": False,
            "release": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_bytes(evidence))


def validate_evidence(
    spec: dict[str, Any], spec_path: Path, evidence: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    if evidence.get("schema") != PROVENANCE_SCHEMA:
        errors.append("invalid provenance schema")
        return errors
    gate_id = evidence.get("gate")
    try:
        gate = gate_by_id(spec, str(gate_id))
    except ReadinessError as error:
        errors.append(str(error))
        return errors
    for key in ("lane", "platform"):
        if evidence.get(key) != gate[key]:
            errors.append(f"{gate_id}: {key} does not match module spec")
    toolchain = evidence.get("toolchain", {})
    if toolchain.get("class") != gate["toolchain"]:
        errors.append(f"{gate_id}: toolchain class does not match module spec")
    if toolchain.get("version") != spec["toolchains"][gate["toolchain"]]:
        errors.append(f"{gate_id}: toolchain version does not match module spec")
    bindings = evidence.get("bindings", {})
    expected = {
        "specSha256": spec_hash(spec_path),
        "testSetSha256": gate_test_set_hash(spec, gate),
        "cargoLockSha256": file_sha256(ROOT / "codex-rs/Cargo.lock"),
        "documentationSha256": tree_hash(
            ROOT / item["path"] for item in spec["documents"]
        ),
        "implementationMapSha256": file_sha256(
            ROOT / spec["paths"]["implementationMap"]
        ),
    }
    for name, value in expected.items():
        if bindings.get(name) != value:
            errors.append(f"{gate_id}: {name} does not match candidate source")
    if evidence.get("result") != "success":
        errors.append(f"{gate_id}: result is {evidence.get('result')}")
    if evidence.get("claimBoundary", {}).get("productionActivation") is not False:
        errors.append(f"{gate_id}: provenance attempted to activate production")
    return errors


def aggregate(args: argparse.Namespace) -> None:
    spec_path = args.spec.resolve()
    spec = load_json(spec_path)
    evidence_files = sorted(args.evidence_dir.rglob("*.provenance.json"))
    records: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for path in evidence_files:
        record = load_json(path)
        gate = str(record.get("gate", ""))
        if gate in records:
            errors.append(f"duplicate evidence for gate {gate}")
            continue
        records[gate] = record
        errors.extend(validate_evidence(spec, spec_path, record))

    expected = [gate["id"] for gate in spec["qualification"]["requiredGates"]]
    missing = [gate for gate in expected if gate not in records]
    errors.extend(f"missing evidence for gate {gate}" for gate in missing)

    source_shas = {record.get("sourceSha") for record in records.values()}
    base_shas = {record.get("baseSha") for record in records.values()}
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
        "productionActivation": False,
        "release": False,
        "gates": [
            {
                "id": gate,
                "result": records.get(gate, {}).get("result", "missing"),
                "workflowRunId": records.get(gate, {})
                .get("workflow", {})
                .get("runId"),
                "targetTriple": records.get(gate, {})
                .get("runner", {})
                .get("targetTriple"),
                "runnerFingerprintSha256": records.get(gate, {})
                .get("runner", {})
                .get("fingerprintSha256"),
                "testSetSha256": records.get(gate, {})
                .get("bindings", {})
                .get("testSetSha256"),
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
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_bytes(manifest))
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
    capture_parser.add_argument("--toolchain", choices=("stable", "msrv"), required=True)
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
    capture_parser.add_argument("--result", required=True)
    capture_parser.add_argument("--output", type=Path, required=True)

    aggregate_parser = sub.add_parser("aggregate")
    aggregate_parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    aggregate_parser.add_argument("--evidence-dir", type=Path, required=True)
    aggregate_parser.add_argument("--source-sha")
    aggregate_parser.add_argument("--base-sha")
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
    except ReadinessError as error:
        print(f"neuron readiness: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
