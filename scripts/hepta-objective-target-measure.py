#!/usr/bin/env python3
"""Record objective.compiler target-host latency and resource evidence.

Every workload fixture runs below a fresh helper process. Resource counters are
therefore scoped to that fixture's command process tree instead of being the
cumulative maximum of every previously executed child. Internal Rust phase
latencies remain separately reported; the helper does not pretend that a
process-tree RSS peak is an allocation measurement for an individual phase.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CARGO_ROOT = ROOT / "codex-rs"
PREFIX = "OBJECTIVE_MEASUREMENT="
PRODUCT_PREFIX = "OBJECTIVE_PRODUCT_MEASUREMENT="
RESOURCE_PREFIX = "OBJECTIVE_PROCESS_RESOURCE="
SCHEMA = "hepta.objective-target-host-evidence.v2"
PRODUCT_SCHEMA = "hepta.objective-product-target-measurement.v1"
RESOURCE_SCHEMA = "hepta.objective-command-resource-observation.v1"


def fail(message: str) -> None:
    raise SystemExit("FAIL_HEPTA_OBJECTIVE_TARGET_MEASUREMENT: " + message)


def command(*args: str, cwd: Path = ROOT, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.stdout


def git(*args: str) -> str:
    return command("git", *args).strip()


def latency_distribution(value: Any, field: str) -> dict[str, int]:
    if not isinstance(value, dict):
        fail(f"missing latency distribution for {field}")
    ordered = [value.get(key) for key in ("p50", "p95", "p99")]
    if not all(type(item) is int and item >= 0 for item in ordered):
        fail(f"invalid latency percentiles for {field}")
    if ordered != sorted(ordered):
        fail(f"non-monotone latency percentiles for {field}")
    return value


def _peak_rss_bytes(value: float) -> int:
    # Darwin reports bytes; Linux and BSD-compatible CI images report KiB.
    scale = 1 if platform.system() == "Darwin" else 1024
    return max(0, int(value) * scale)


def _resource_payload(usage: resource.struct_rusage, wall_ns: int) -> dict[str, Any]:
    return {
        "schema": RESOURCE_SCHEMA,
        "scope": (
            "one isolated native fixture command; OS-reported waited-child peak RSS, "
            "not simultaneous process-tree sum, build cost or per-phase allocation"
        ),
        "peakResidentSetBytes": _peak_rss_bytes(usage.ru_maxrss),
        "userCpuNanoseconds": max(0, int(usage.ru_utime * 1_000_000_000)),
        "systemCpuNanoseconds": max(0, int(usage.ru_stime * 1_000_000_000)),
        "wallNanoseconds": max(0, wall_ns),
        "minorPageFaults": max(0, int(usage.ru_minflt)),
        "majorPageFaults": max(0, int(usage.ru_majflt)),
        "voluntaryContextSwitches": max(0, int(usage.ru_nvcsw)),
        "involuntaryContextSwitches": max(0, int(usage.ru_nivcsw)),
    }


def process_resource_observation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != RESOURCE_SCHEMA:
        fail("invalid isolated process resource observation schema")
    if not isinstance(value.get("scope"), str) or not value["scope"]:
        fail("isolated process resource observation lacks scope")
    fields = (
        "peakResidentSetBytes",
        "userCpuNanoseconds",
        "systemCpuNanoseconds",
        "wallNanoseconds",
        "minorPageFaults",
        "majorPageFaults",
        "voluntaryContextSwitches",
        "involuntaryContextSwitches",
    )
    for field in fields:
        if type(value.get(field)) is not int or value[field] < 0:
            fail(f"invalid isolated process resource field: {field}")
    if value["wallNanoseconds"] == 0:
        fail("isolated process resource wall time must be positive")
    return value


def resource_helper(cwd: Path, argv: list[str]) -> int:
    if not argv:
        print("resource helper requires one command", file=sys.stderr)
        return 2
    started = time.monotonic_ns()
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            env=os.environ.copy(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        output = result.stdout
        code = result.returncode
    except OSError as error:
        output = f"{type(error).__name__}: {error}\n"
        code = 127
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    if output:
        sys.stdout.write(output)
        if not output.endswith("\n"):
            sys.stdout.write("\n")
    print(
        RESOURCE_PREFIX
        + json.dumps(
            _resource_payload(usage, time.monotonic_ns() - started),
            sort_keys=True,
        )
    )
    return code


def run_isolated_command(
    *args: str, cwd: Path, env: dict[str, str] | None = None
) -> tuple[str, dict[str, Any]]:
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--resource-helper",
            "--resource-cwd",
            str(cwd),
            "--",
            *args,
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    resource_rows = [
        line.split(RESOURCE_PREFIX, 1)[1]
        for line in result.stdout.splitlines()
        if line.startswith(RESOURCE_PREFIX)
    ]
    child_lines = [
        line for line in result.stdout.splitlines() if not line.startswith(RESOURCE_PREFIX)
    ]
    child_output = "\n".join(child_lines)
    if child_output:
        child_output += "\n"
    if len(resource_rows) != 1:
        fail(
            "expected exactly one isolated process resource row, received "
            f"{len(resource_rows)}"
        )
    try:
        observation = process_resource_observation(json.loads(resource_rows[0]))
    except ValueError as error:
        fail(f"invalid isolated process resource JSON: {error}")
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            args,
            output=child_output,
        )
    return child_output, observation


def parse_measurement(output: str, expected_path: str) -> dict[str, Any]:
    rows = [line.split(PREFIX, 1)[1] for line in output.splitlines() if PREFIX in line]
    if len(rows) != 1:
        fail(
            f"expected exactly one measurement row for {expected_path}, received {len(rows)}"
        )
    try:
        value = json.loads(rows[0])
    except ValueError as error:
        fail(f"invalid measurement JSON for {expected_path}: {error}")
    if not isinstance(value, dict):
        fail("measurement JSON must be an object")
    if type(value.get("samples")) is not int or value["samples"] <= 0:
        fail("invalid measurement sample count")
    if expected_path == "maximum_conflict_extraction" and (
        type(value.get("constraintAtoms")) is not int
        or value["constraintAtoms"] != 256
        or type(value.get("oracleCallsPerSample")) is not int
        or value["oracleCallsPerSample"] != 257
    ):
        fail("conflict measurement must cover 256 atoms and 257 oracle calls")
    if value.get("schema") != "hepta.objective-target-measurement.v1":
        fail(f"unexpected measurement schema for {expected_path}")
    if value.get("path") != expected_path:
        fail(f"unexpected measurement path: {value.get('path')!r}")
    latency_distribution(value.get("latencyNanoseconds"), expected_path)
    if expected_path == "ordinary_authenticated_admission_compile":
        phases = value.get("phaseLatencyNanoseconds")
        expected_phases = {
            "coldProfileValidation",
            "warmAuthenticatedAdmission",
            "nativeCompile",
            "protocolEncode",
            "protocolDecode",
        }
        if not isinstance(phases, dict) or set(phases) != expected_phases:
            fail("ordinary measurement phase set is incomplete")
        for name, distribution in phases.items():
            latency_distribution(distribution, f"ordinary.{name}")
        reuse = value.get("staticProfileReuseKey")
        if not isinstance(reuse, dict) or set(reuse) != {
            "profileDigest",
            "profileRevision",
            "compilerContractDigest",
        }:
            fail("ordinary measurement lacks the exact static-profile reuse key")
        if type(reuse.get("profileRevision")) is not int or reuse["profileRevision"] <= 0:
            fail("ordinary measurement has an invalid profile revision")
        for field in ("profileDigest", "compilerContractDigest"):
            if not isinstance(reuse.get(field), str) or not reuse[field]:
                fail(f"ordinary measurement has an invalid {field}")
        if value.get("dynamicAuthorizationCached") is not False:
            fail("ordinary measurement must state that dynamic authorization is not cached")
    return value


def parse_product_measurement(output: str) -> dict[str, Any]:
    rows = [
        line.split(PRODUCT_PREFIX, 1)[1]
        for line in output.splitlines()
        if PRODUCT_PREFIX in line
    ]
    if len(rows) != 1:
        fail(f"expected exactly one product measurement row, received {len(rows)}")
    try:
        value = json.loads(rows[0])
    except ValueError as error:
        fail(f"invalid product measurement JSON: {error}")
    if not isinstance(value, dict):
        fail("product measurement JSON must be an object")
    if value.get("schema") != PRODUCT_SCHEMA:
        fail("unexpected product measurement schema")
    if value.get("path") != "signed_objective_daemon_round_trip":
        fail(f"unexpected product measurement path: {value.get('path')!r}")
    samples = value.get("samples")
    if type(samples) is not int or samples <= 0:
        fail("invalid product measurement sample count")
    latency_distribution(value.get("latencyNanoseconds"), "product")
    phases = value.get("phaseLatencyNanoseconds")
    expected_phases = {
        "signedIngressCompileDurableAppendCheckpointAndAgentdHandoff",
        "compiledPublicationAndAgentdHandoff",
        "contextAttachment",
        "currentFinalUseProviderAndTerminalObservation",
    }
    if not isinstance(phases, dict) or set(phases) != expected_phases:
        fail("product measurement phase set is incomplete")
    for name, distribution in phases.items():
        latency_distribution(distribution, f"product.{name}")
    if value.get("atomicOwnerBoundaryNotSplit") is not True:
        fail("product measurement must preserve the atomic owner boundary")
    execution_samples = value.get("executionSamples")
    if type(execution_samples) is not int or execution_samples <= 0:
        fail("invalid product execution sample count")
    latency_distribution(value.get("executionLatencyNanoseconds"), "product execution")
    for field in (
        "exactReplayNanoseconds",
        "executionExactReplayNanoseconds",
        "restartReadyNanoseconds",
    ):
        if type(value.get(field)) is not int or value[field] < 0:
            fail(f"invalid product measurement field: {field}")
    for field in (
        "physicalProviderSends",
        "terminalObservations",
        "durableCheckpointSequence",
    ):
        if type(value.get(field)) is not int:
            fail(f"invalid product measurement counter: {field}")
    if value.get("physicalProviderSends") != execution_samples:
        fail("product execution did not preserve one physical send per run")
    if value.get("terminalObservations") != execution_samples:
        fail("product execution did not observe every terminal")
    if value.get("durableCheckpointSequence") != samples + execution_samples:
        fail("product checkpoint sequence does not cover every measured request")
    return value


def attach_resources(
    measurement: dict[str, Any], observation: dict[str, Any]
) -> dict[str, Any]:
    measurement["harnessWallNanoseconds"] = observation["wallNanoseconds"]
    measurement["fixtureProcessResources"] = observation
    return measurement


def file_identity(path: Path) -> dict[str, Any]:
    """Hash an actual executable; caller-supplied names never establish identity."""
    if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
        fail(f"native artifact is not a regular executable: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1_048_576), b""):
            digest.update(block)
    return {
        "path": str(path.resolve()),
        "sha256": digest.hexdigest(),
        "sizeBytes": path.stat().st_size,
    }


def select_native_artifacts(
    output: str, package: str, target_name: str, target_kind: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Use Cargo's exact artifact messages, never a target-directory glob."""
    selected: list[dict[str, Any]] = []
    artifacts: dict[str, dict[str, Any]] = {}
    crate_root = (CARGO_ROOT / package.removeprefix("codex-")).resolve()
    for line in output.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue  # Cargo's combined output also contains progress text.
        if not isinstance(row, dict) or row.get("reason") != "compiler-artifact":
            continue
        target = row.get("target", {})
        source = target.get("src_path") if isinstance(target, dict) else None
        executable = row.get("executable")
        if not source or not executable or not Path(source).resolve().is_relative_to(crate_root):
            continue
        item = file_identity(Path(executable))
        item["targetName"] = target.get("name")
        item["targetKind"] = target.get("kind")
        artifacts[item["path"]] = item
        if (
            target.get("name") == target_name
            and target_kind in target.get("kind", [])
            and row.get("profile", {}).get("test") is True
        ):
            selected.append(item)
    if len(selected) != 1:
        fail(f"expected one Cargo test executable for {package}/{target_name}, found {len(selected)}")
    return selected[0], sorted(artifacts.values(), key=lambda item: item["path"])


def verify_native_artifacts(artifacts: list[dict[str, Any]]) -> None:
    for expected in artifacts:
        current = file_identity(Path(expected["path"]))
        if any(current[key] != expected[key] for key in ("path", "sha256", "sizeBytes")):
            fail("native artifact changed between build and measurement")


def build_native_fixture(package: str, target: str | None) -> dict[str, Any]:
    """Build before resource sampling and bind every emitted package executable."""
    argv = ["cargo", "test", "--locked", "--release", "-p", package]
    argv.extend(["--test", target] if target else ["--lib"])
    argv.extend(["--no-run", "--message-format=json"])
    output = command(*argv, cwd=CARGO_ROOT)
    selected, artifacts = select_native_artifacts(
        output, package, target or package.replace("-", "_"), "test" if target else "lib"
    )
    return {
        "schema": "hepta.objective-native-fixture.v1",
        "sourceCommit": git("rev-parse", "HEAD"),
        "sourceTree": git("rev-parse", "HEAD^{tree}"),
        "buildCommand": argv,
        "cargoArtifactMessagesSha256": hashlib.sha256(output.encode()).hexdigest(),
        "executable": selected["path"],
        "artifacts": artifacts,
        "buildCostsExcludedFromFixtureResources": True,
        "nativeFfiQualificationProved": False,
    }


def select_exact_test(output: str, requested: str) -> str:
    tests = [line.removesuffix(": test") for line in output.splitlines() if line.endswith(": test")]
    matches = [name for name in tests if name == requested or name.endswith("::" + requested)]
    if len(matches) != 1:
        fail(f"expected one exact native test for {requested}, found {len(matches)}")
    return matches[0]


def run_native_fixture(
    package: str, target: str | None, test_name: str, env: dict[str, str]
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    native = build_native_fixture(package, target)
    verify_native_artifacts(native["artifacts"])
    listed = command(native["executable"], "--list", "--format", "terse", cwd=CARGO_ROOT, env=env)
    exact = select_exact_test(listed, test_name)
    verify_native_artifacts(native["artifacts"])
    argv = [native["executable"], exact, "--ignored", "--exact", "--nocapture", "--test-threads=1"]
    output, observation = run_isolated_command(*argv, cwd=CARGO_ROOT, env=env)
    verify_native_artifacts(native["artifacts"])
    native.update({
        "testName": exact,
        "testListSha256": hashlib.sha256(listed.encode()).hexdigest(),
        "executionCommand": argv,
        "executionOutputSha256": hashlib.sha256(output.encode()).hexdigest(),
        "exitCode": 0,
        "artifactsUnchangedAfterExecution": True,
    })
    return output, observation, native


def run_product_fixture(samples: int, execution_samples: int) -> dict[str, Any]:
    env = os.environ.copy()
    env["HEPTA_OBJECTIVE_PRODUCT_MEASUREMENT_SAMPLES"] = str(samples)
    env["HEPTA_OBJECTIVE_PRODUCT_EXECUTION_SAMPLES"] = str(execution_samples)
    output, observation, native = run_native_fixture(
        "codex-hepta-agentd", "objective_product_e2e",
        "measurement_signed_objective_daemon_round_trip", env,
    )
    measurement = parse_product_measurement(output)
    if (
        measurement["samples"] != samples
        or measurement["executionSamples"] != execution_samples
    ):
        fail("product fixture sample count differs from requested measurement")
    measurement["nativeFixture"] = native
    return attach_resources(measurement, observation)


def run_fixture(test_name: str, expected_path: str, samples: int) -> dict[str, Any]:
    env = os.environ.copy()
    env["HEPTA_OBJECTIVE_MEASUREMENT_SAMPLES"] = str(samples)
    output, observation, native = run_native_fixture(
        "codex-hepta-objective", None, test_name, env,
    )
    measurement = parse_measurement(output, expected_path)
    if measurement["samples"] != samples:
        fail("fixture sample count differs from requested measurement")
    measurement["nativeFixture"] = native
    return attach_resources(measurement, observation)


def sample_resource_observation() -> dict[str, Any]:
    return {
        "schema": RESOURCE_SCHEMA,
        "scope": "one isolated fixture command process tree",
        "peakResidentSetBytes": 1024,
        "userCpuNanoseconds": 10,
        "systemCpuNanoseconds": 5,
        "wallNanoseconds": 20,
        "minorPageFaults": 1,
        "majorPageFaults": 0,
        "voluntaryContextSwitches": 2,
        "involuntaryContextSwitches": 0,
    }


def self_test() -> int:
    fixture = (
        'OBJECTIVE_MEASUREMENT={"schema":"hepta.objective-target-measurement.v1",'
        '"path":"ordinary_authenticated_admission_compile","samples":3,'
        '"latencyNanoseconds":{"p50":10,"p95":20,"p99":30},'
        '"phaseLatencyNanoseconds":{'
        '"coldProfileValidation":{"p50":1,"p95":2,"p99":3},'
        '"warmAuthenticatedAdmission":{"p50":1,"p95":2,"p99":3},'
        '"nativeCompile":{"p50":1,"p95":2,"p99":3},'
        '"protocolEncode":{"p50":1,"p95":2,"p99":3},'
        '"protocolDecode":{"p50":1,"p95":2,"p99":3}},'
        '"staticProfileReuseKey":{"profileDigest":"a","profileRevision":1,'
        '"compilerContractDigest":"b"},"dynamicAuthorizationCached":false}'
    )
    parsed = parse_measurement(fixture, "ordinary_authenticated_admission_compile")
    if parsed["latencyNanoseconds"]["p99"] != 30:
        fail("self-test parse mismatch")
    product_fixture = (
        'OBJECTIVE_PRODUCT_MEASUREMENT={"schema":"hepta.objective-product-target-measurement.v1",'
        '"path":"signed_objective_daemon_round_trip","samples":3,'
        '"latencyNanoseconds":{"p50":100,"p95":200,"p99":300},'
        '"phaseLatencyNanoseconds":{'
        '"signedIngressCompileDurableAppendCheckpointAndAgentdHandoff":'
        '{"p50":100,"p95":200,"p99":300},'
        '"compiledPublicationAndAgentdHandoff":{"p50":10,"p95":20,"p99":30},'
        '"contextAttachment":{"p50":10,"p95":20,"p99":30},'
        '"currentFinalUseProviderAndTerminalObservation":'
        '{"p50":100,"p95":200,"p99":300}},'
        '"atomicOwnerBoundaryNotSplit":true,'
        '"exactReplayNanoseconds":80,"executionSamples":2,'
        '"executionLatencyNanoseconds":{"p50":150,"p95":250,"p99":350},'
        '"executionExactReplayNanoseconds":90,"physicalProviderSends":2,'
        '"terminalObservations":2,"restartReadyNanoseconds":400,'
        '"durableCheckpointSequence":5}'
    )
    product = parse_product_measurement(product_fixture)
    if product["restartReadyNanoseconds"] != 400:
        fail("product self-test parse mismatch")
    process_resource_observation(sample_resource_observation())
    print("PASS_HEPTA_OBJECTIVE_TARGET_MEASUREMENT_SELF_TEST")
    return 0


def filesystem_context(root: Path, mountinfo: str) -> dict[str, Any]:
    """Describe the actual fixture filesystem without claiming storage acceptance."""
    root = root.resolve()
    selected = None
    for line in mountinfo.splitlines():
        fields = line.split()
        try:
            separator = fields.index("-")
            if separator < 6 or len(fields) <= separator + 1:
                continue
            encoded = fields[4]
            for escape, decoded in (
                ("\\040", " "),
                ("\\011", "\t"),
                ("\\012", "\n"),
                ("\\134", "\\"),
            ):
                encoded = encoded.replace(escape, decoded)
            mount = Path(encoded)
            if not root.is_relative_to(mount):
                continue
            entry = {
                "mountPoint": str(mount),
                "filesystemType": fields[separator + 1],
                "deviceId": fields[2],
            }
            if selected is None or len(mount.parts) > len(
                Path(selected["mountPoint"]).parts
            ):
                selected = entry
        except (ValueError, IndexError):
            continue
    result: dict[str, Any] = {
        "temporaryRoot": str(root),
        "mountIdentityAvailable": selected is not None,
    }
    if selected is not None:
        result.update(selected)
        result["memoryBacked"] = selected["filesystemType"] in {"tmpfs", "ramfs"}
    result["storageQualificationProved"] = False
    return result


def current_filesystem_context() -> dict[str, Any]:
    try:
        mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
    except OSError:
        mountinfo = ""
    return filesystem_context(Path(tempfile.gettempdir()), mountinfo)


def measure(args: argparse.Namespace) -> int:
    source_sha = git("rev-parse", "HEAD")
    source_tree = git("rev-parse", "HEAD^{tree}")
    if source_sha != args.expected_sha:
        fail(
            f"source identity mismatch: expected {args.expected_sha}, observed {source_sha}"
        )
    if git("status", "--porcelain"):
        fail("working tree is not clean")

    rustc = command("rustc", "--version").strip()
    cargo = command("cargo", "--version").strip()
    ordinary = run_fixture(
        "measurement_ordinary_admission_compile_v1",
        "ordinary_authenticated_admission_compile",
        args.ordinary_samples,
    )
    conflict = run_fixture(
        "measurement_conflict_extraction_v1",
        "maximum_conflict_extraction",
        args.conflict_samples,
    )
    product = run_product_fixture(args.product_samples, args.execution_samples)

    for measurement in (ordinary, conflict, product):
        native = measurement["nativeFixture"]
        if native["sourceCommit"] != source_sha or native["sourceTree"] != source_tree:
            fail("native build source differs from measured source")

    if (
        git("rev-parse", "HEAD") != source_sha
        or git("rev-parse", "HEAD^{tree}") != source_tree
    ):
        fail("source identity changed during measurement")
    if git("status", "--porcelain"):
        fail("working tree changed during measurement")

    evidence = {
        "schema": SCHEMA,
        "sourceCommit": source_sha,
        "sourceTree": source_tree,
        "workflowRunId": os.environ.get("GITHUB_RUN_ID"),
        "workflowRunAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "workflowCommit": os.environ.get("GITHUB_WORKFLOW_SHA", os.environ.get("GITHUB_SHA")),
        "workflowRef": os.environ.get("GITHUB_WORKFLOW_REF"),
        "hostProfileId": args.host_profile_id,
        "host": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "rustc": rustc,
            "cargo": cargo,
            "fixtureFilesystem": current_filesystem_context(),
        },
        "buildProfile": "release",
        "measurements": [ordinary, conflict, product],
        "interpretation": {
            "ordinaryAndConflictAreSeparate": True,
            "phaseLatencyMeasuredInsideFixture": True,
            "buildCostsExcludedFromFixtureResources": True,
            "nativeArtifactsBoundBeforeAndAfterExecution": True,
            "nativeFfiQualificationProved": False,
            "fixtureResourcesIsolatedByFreshHelperProcess": True,
            "memoryIsNotPerInternalPhaseAllocation": True,
            "productIncludesSignedIngressSocketFsyncAndRestart": True,
            "productExecutionIncludesFinalUsePhysicalSendAndTerminal": True,
            "ciRunnerIsNotProductionEvidence": True,
            "controlledModelProviderAndContextFixture": True,
            "storageQualificationProved": False,
            "staticProfileReuseMeasuredSeparately": True,
            "dynamicAuthorizationCachingAllowed": False,
            "atomicAppendCheckpointHandoffBoundaryPreserved": True,
            "activationGranted": False,
            "releaseGranted": False,
        },
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(evidence, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, output)
    print(json.dumps(evidence, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resource-helper", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--resource-cwd", help=argparse.SUPPRESS)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--expected-sha")
    parser.add_argument("--host-profile-id")
    parser.add_argument("--ordinary-samples", type=int, default=1_000)
    parser.add_argument("--conflict-samples", type=int, default=64)
    parser.add_argument("--product-samples", type=int, default=32)
    parser.add_argument("--execution-samples", type=int, default=4)
    parser.add_argument("--output")
    parser.add_argument("resource_command", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.resource_helper:
        if not args.resource_cwd:
            parser.error("--resource-cwd is required for the resource helper")
        helper_command = args.resource_command[1:] if args.resource_command[:1] == ["--"] else args.resource_command
        return resource_helper(Path(args.resource_cwd), helper_command)
    if args.resource_command:
        parser.error("unexpected trailing command")
    if args.self_test:
        return self_test()
    if not args.expected_sha or len(args.expected_sha) != 40:
        parser.error("--expected-sha must be the exact 40-character candidate SHA")
    if not args.host_profile_id:
        parser.error("--host-profile-id is required")
    if not args.output:
        parser.error("--output is required")
    if not (1 <= args.ordinary_samples <= 100_000):
        parser.error("--ordinary-samples must be in 1..=100000")
    if not (1 <= args.conflict_samples <= 10_000):
        parser.error("--conflict-samples must be in 1..=10000")
    if not (1 <= args.product_samples <= 1_000):
        parser.error("--product-samples must be in 1..=1000")
    if not (1 <= args.execution_samples <= 64):
        parser.error("--execution-samples must be in 1..=64")
    return measure(args)


if __name__ == "__main__":
    sys.exit(main())
