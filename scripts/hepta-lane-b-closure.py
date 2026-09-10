#!/usr/bin/env python3
"""Verify Lane B documentation, native-source mapping and CI evidence boundaries.

This verifier closes repository-internal documentation and mapping blockers only.
It never converts source presence, a test design, CI success or a generated receipt
into product-runtime, provider, external-effect, deployment or release authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs/lane-b/LANE_B_CLOSURE.json"
STATUS = ROOT / "docs/lane-b/STATUS.md"

MODULES = (
    "runtime.supervisor",
    "runtime.fleet",
    "runtime.agentd",
    "runtime.codex",
    "inference.control",
    "inference.worker",
    "automation.taskflow",
    "channel.matrix",
    "browser.servo",
    "ui.control",
    "ui.native",
)

LIFECYCLE_STATES = (
    "specified",
    "source_mapped",
    "compiled",
    "unit_tested",
    "integration_tested",
    "production_called",
    "deployment_qualified",
    "independently_accepted",
)

FALSE_CLAIMS = (
    "productRuntimeQualified",
    "providerExecutionProved",
    "externalEffectProved",
    "deploymentQualified",
    "independentAcceptance",
    "promotionAuthorized",
    "releaseAuthorized",
)

REPOSITORY_BLOCKERS = (
    "LB-P0-001-STATE-SOURCE",
    "LB-P0-002-RECEIPT-WORKFLOW",
    "LB-P0-003-NATIVE-MAPPING",
    "LB-P0-004-DEFAULT-BRANCH-CI",
    "LB-P0-005-EXACT-CANDIDATE-EVIDENCE",
    "LB-P1-001-CURRENT-TARGET-BRIDGE",
    "LB-P2-001-MACHINE-VERIFICATION",
)

EXTERNAL_GATES = tuple(f"RDY-EXT-{index:03d}" for index in range(1, 10))


class Invalid(ValueError):
    """Invalid closed-world document or stale source observation."""


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise Invalid(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(Invalid(value)),
    )


def need(condition: bool, message: str) -> None:
    if not condition:
        raise Invalid(message)


def inside(relative: str) -> Path:
    need(isinstance(relative, str) and relative, "empty repository path")
    candidate = Path(relative)
    need(not candidate.is_absolute() and ".." not in candidate.parts, "unsafe path")
    resolved = (ROOT / candidate).resolve()
    need(resolved.is_relative_to(ROOT.resolve()), "path escape")
    return resolved


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def status_text(registry: dict[str, Any]) -> str:
    observations = registry["nativeSourceFiles"]
    closed = sum(row["state"] == "closed_by_candidate" for row in registry["repositoryBlockers"])
    lines = [
        "# Lane B closure status",
        "",
        "This status separates repository-internal closure from external product and capability evidence.",
        "",
        f"- Registered Lane B modules: **{len(registry['modules'])}/{len(MODULES)}**",
        f"- Stable technical guides with current/target/bridge sections: **{len(registry['modules'])}/{len(MODULES)}**",
        f"- Native source mapping coverage: **{len(registry['modules'])}/{len(MODULES)} modules** across **{observations} source files**",
        f"- Repository-internal blockers closed by this candidate: **{closed}/{len(REPOSITORY_BLOCKERS)}**",
        "- Product runtime or provider execution qualification: **not claimed**",
        "- Deployment and independent acceptance: **not claimed**",
        f"- External capability gates: **{len(EXTERNAL_GATES)} remain externally evidenced and non-self-certifiable**",
        "",
        "## Closure rule",
        "",
        "A source symbol, local test, CI run or generated document may close only the repository-internal blocker it actually proves. External model, device, operator, future-time, deployment, promotion and release evidence remains a separate gate.",
        "",
        "## Module states",
        "",
        "| Module | Current lifecycle state | Product caller proved | Deployment qualified |",
        "|---|---|---:|---:|",
    ]
    for row in registry["modules"]:
        claims = row["claims"]
        lines.append(
            f"| `{row['module']}` | `{row['lifecycleState']}` | no | {'yes' if claims['deploymentQualified'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## External gates",
            "",
            *[f"- `{gate}` — external evidence required" for gate in EXTERNAL_GATES],
            "",
        ]
    )
    return "\n".join(lines)


def verify_registry(registry: dict[str, Any]) -> None:
    need(registry.get("schema") == "hepta.lane-b-closure.v1", "registry schema")
    need(registry.get("schemaVersion") == 1, "registry schema version")
    need(registry.get("laneId") == "LANE-B-RUNTIME", "lane identity")
    need(registry.get("moduleCount") == len(MODULES), "module count")
    need(registry.get("lifecycleStates") == list(LIFECYCLE_STATES), "lifecycle ordering")
    boundary = registry.get("claimBoundary")
    need(isinstance(boundary, dict), "claim boundary")
    need(boundary.get("repositoryInternalGapsClosed") is True, "internal closure flag")
    for key in FALSE_CLAIMS:
        need(boundary.get(key) is False, f"positive boundary claim: {key}")
    need(boundary.get("allGapsClosed") is False, "false global closure")

    rows = registry.get("modules")
    need(isinstance(rows, list), "module rows")
    need([row.get("module") for row in rows] == list(MODULES), "module order/coverage")
    observed_paths: set[tuple[str, str]] = set()
    for row in rows:
        module = row["module"]
        need(row.get("lifecycleState") in LIFECYCLE_STATES, f"{module}: lifecycle")
        need(LIFECYCLE_STATES.index(row["lifecycleState"]) >= 1, f"{module}: unmapped source")
        guide = inside(row.get("guide", ""))
        design = inside(row.get("design", ""))
        need(guide.is_file() and design.is_file(), f"{module}: documents")
        text = guide.read_text(encoding="utf-8")
        need(
            "## 18. Lane B current capability, native mapping and remaining gates" in text,
            f"{module}: generated closure section",
        )
        need(
            ".github/workflows/hepta-gap-closure.yml" not in text,
            f"{module}: stale receipt workflow",
        )
        for key in ("currentCapability", "targetCapability"):
            need(isinstance(row.get(key), str) and len(row[key]) >= 40, f"{module}: {key}")
        bridges = row.get("remainingBridges")
        need(isinstance(bridges, list) and bridges, f"{module}: remaining bridges")
        mappings = row.get("operationMappings")
        need(isinstance(mappings, list) and mappings, f"{module}: operation mappings")
        operations: set[str] = set()
        for mapping in mappings:
            operation = mapping.get("operation")
            path = mapping.get("path")
            symbols = mapping.get("symbols")
            need(isinstance(operation, str) and operation, f"{module}: operation")
            need(operation not in operations, f"{module}: duplicate operation")
            operations.add(operation)
            source = inside(path)
            need(source.is_file(), f"{module}: mapping path")
            source_text = source.read_text(encoding="utf-8")
            need(isinstance(symbols, list) and symbols, f"{module}: symbols")
            for symbol in symbols:
                need(
                    isinstance(symbol, str)
                    and re.search(r"\b" + re.escape(symbol) + r"\b", source_text) is not None,
                    f"{module}: stale symbol {symbol}",
                )
            observed_paths.add((module, path))
        claims = row.get("claims")
        need(isinstance(claims, dict) and list(claims) == list(FALSE_CLAIMS), f"{module}: claim keys")
        need(not any(claims.values()), f"{module}: positive product claim")

    blockers = registry.get("repositoryBlockers")
    need(isinstance(blockers, list), "repository blockers")
    need([row.get("id") for row in blockers] == list(REPOSITORY_BLOCKERS), "blocker coverage")
    for row in blockers:
        need(row.get("state") == "closed_by_candidate", f"{row.get('id')}: state")
        evidence = row.get("evidence")
        need(isinstance(evidence, list) and evidence, f"{row.get('id')}: evidence")
        for path in evidence:
            need(inside(path).exists(), f"{row.get('id')}: missing evidence")

    external = registry.get("externalGates")
    need([row.get("id") for row in external] == list(EXTERNAL_GATES), "external gate coverage")
    for row in external:
        need(row.get("state") == "external_evidence_required", f"{row.get('id')}: state")
        need(row.get("repositoryMaySelfCertify") is False, f"{row.get('id')}: self certification")

    native = load(ROOT / "qualification/module-execution-dossiers/NATIVE_BINDINGS.json")
    observations = [row for row in native["observations"] if row.get("module") in MODULES]
    need({row["module"] for row in observations} == set(MODULES), "Lane B native coverage")
    need(len(observations) == registry["nativeSourceFiles"], "native source-file count")
    native_pairs = {(row["module"], row["path"]) for row in observations}
    need(observed_paths <= native_pairs, "registry/native observation mismatch")
    for row in observations:
        source = inside(row["path"])
        data = source.read_bytes()
        need(blob_sha(data) == row["blobSha"], f"native blob drift: {row['path']}")
        decoded = data.decode("utf-8")
        for symbol in row["exports"]:
            need(re.search(r"\b" + re.escape(symbol) + r"\b", decoded) is not None, f"native symbol drift: {symbol}")


def verify_workflows_and_packages() -> None:
    current = load(ROOT / "docs/CURRENT.json")
    default_branch = current["repository"]["defaultBranch"]
    for workflow in (".github/workflows/blocking-ci.yml", ".github/workflows/postmerge-ci.yml"):
        text = inside(workflow).read_text(encoding="utf-8")
        need(default_branch in text, f"{workflow}: default branch trigger")
    blocking = inside(".github/workflows/blocking-ci.yml").read_text(encoding="utf-8")
    need("hepta-lane-b:" in blocking and "- hepta-lane-b" in blocking, "blocking Lane B gate")

    workflow = inside(".github/workflows/hepta-lane-b-closure.yml").read_text(encoding="utf-8")
    for token in (
        "contents: read",
        "persist-credentials: false",
        "scripts/hepta-lane-b-closure.py",
        "codex-hepta-supervisor",
        "codex-hepta-fleet",
        "codex-hepta-agentd",
        "codex-hepta-codex-adapter",
        "codex-hepta-infer-core",
        "codex-hepta-inferd",
        "codex-hepta-infer-worker-host",
        "codex-hepta-automation",
        "codex-hepta-matrix-sdk",
        "codex-hepta-matrixd",
        "apps/hepta-browser/test/*.js",
        "apps/hepta-control-ui/test/*.js",
        "apps/hepta-native/test/*.js",
    ):
        need(token in workflow, f"Lane B workflow token: {token}")

    for workflow in (
        ".github/workflows/hepta-implementation-readiness.yml",
        ".github/workflows/hepta-development-docs.yml",
        ".github/workflows/hepta-consolidated-source.yml",
    ):
        text = inside(workflow).read_text(encoding="utf-8")
        need("scripts/hepta-lane-b-closure.py" in text, f"{workflow}: closure verifier")

    for package in ("apps/hepta-browser", "apps/hepta-control-ui", "apps/hepta-native"):
        manifest = load(inside(package + "/package.json"))
        scripts = manifest.get("scripts", {})
        need(scripts.get("check") == "node --check src/*.js", f"{package}: check script")
        need(scripts.get("test") == "node --test", f"{package}: test script")
        need(scripts.get("ci") == "npm run check && npm test", f"{package}: ci script")

    packages = load(ROOT / "docs/delivery/WORK_PACKAGES.json")["packages"]
    matrix = next(row for row in packages if row["id"] == "MATRIX-1-CHANNEL-BOUNDARY")
    need("codex-rs/hepta-matrixd/**" in matrix["allowedWritePaths"], "Matrix daemon path ownership")


def verify() -> int:
    registry = load(REGISTRY)
    verify_registry(registry)
    verify_workflows_and_packages()
    expected = status_text(registry)
    need(STATUS.read_text(encoding="utf-8") == expected, "stale Lane B status")
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_LANE_B_CLOSURE",
                "modules": len(MODULES),
                "repositoryInternalGapsClosed": True,
                "productRuntimeQualified": False,
                "externalCapabilityGatesClosed": False,
                "allGapsClosed": False,
            },
            sort_keys=True,
        )
    )
    return 0


def self_test() -> int:
    need(len(MODULES) == 11, "module fixture")
    need(len(LIFECYCLE_STATES) == 8, "lifecycle fixture")
    need(len(REPOSITORY_BLOCKERS) == 7, "blocker fixture")
    need(len(EXTERNAL_GATES) == 9, "external gate fixture")
    try:
        json.loads('{"a":1,"a":2}', object_pairs_hook=pairs)
        raise AssertionError("duplicate key accepted")
    except Invalid:
        pass
    print(json.dumps({"status": "PASS_HEPTA_LANE_B_CLOSURE_SELF_TEST"}, sort_keys=True))
    return 0


def generate_status(check: bool) -> int:
    registry = load(REGISTRY)
    rendered = status_text(registry)
    if check:
        need(STATUS.is_file() and STATUS.read_text(encoding="utf-8") == rendered, "stale Lane B status")
    else:
        STATUS.parent.mkdir(parents=True, exist_ok=True)
        STATUS.write_text(rendered, encoding="utf-8")
    print(json.dumps({"status": "PASS_HEPTA_LANE_B_STATUS", "check": check}, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("self-test", "verify", "generate-status"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "self-test":
            return self_test()
        if args.command == "verify":
            return verify()
        return generate_status(args.check)
    except (Invalid, OSError, KeyError, TypeError, ValueError, StopIteration) as exc:
        print(f"FAIL_HEPTA_LANE_B_CLOSURE: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
