#!/usr/bin/env python3
"""Closed-world verifier for the Hepta distributed CNS and organ reference."""

from __future__ import annotations
import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ARCH_PATH = "docs/cns/CNS_ARCHITECTURE.json"
PROTOCOL_PATH = "docs/cns/ORGAN_PROTOCOLS.json"
GAPS_PATH = "docs/cns/GAPS.json"
STATUS_PATH = "docs/cns/STATUS.md"
TECHNICAL_PATH = "docs/cns/TECHNICAL.md"
REFERENCE_DIR = "qualification/cns-organ-reference"
AUTHORITY_KEYS = [
    "runtimeAuthority",
    "productionCaller",
    "productionWriter",
    "modelInvocation",
    "providerDispatch",
    "toolExecution",
    "networkConnect",
    "externalFilesystemMutation",
    "secretOperation",
    "matrixSend",
    "externalEffect",
    "fleetMutation",
    "canonicalSelection",
    "merge",
    "operatorAcceptance",
    "promotion",
    "release",
]
ORGAN_KEYS = [
    "id",
    "anatomicalRole",
    "organClass",
    "function",
    "moduleBindings",
    "dependencies",
    "fallbackOrgans",
    "essential",
    "localHotPath",
    "effectBoundary",
    "implementationState",
    "activationState",
]
REQUIRED_ORGANS = [
    "constitutional.kernel",
    "human.override",
    "brainstem.supervisor",
    "energy.metabolism",
    "autonomic.homeostasis",
    "spinal.reflex-safety",
    "peripheral.time-calibration",
    "peripheral.sensor-bus",
    "body.schema",
    "cns.memory-hnmf",
    "cns.value-homeostasis",
    "cns.world-model",
    "cns.attention-workspace",
    "cns.action-gating",
    "cns.executive",
    "cns.metacognition",
    "skill.library",
    "motor.plan",
    "motor.control",
    "actuator.gateway",
    "simulation.twin",
    "sleep.consolidation",
    "immune.anomaly",
    "social.cognition",
]
REQUIRED_PROTOCOLS = [
    "OrganManifestV1",
    "BodyGraphSnapshotV1",
    "OrganProposalV1",
    "OrganQualificationReceiptV1",
    "OrganLeaseV1",
    "OrganHealthSnapshotV1",
    "HomeostasisSnapshotV1",
    "SensorObservationV1",
    "BodyStateEstimateV1",
    "WorldModelPredictionV1",
    "ActuationIntentV1",
    "ReflexVetoV1",
    "PhysicalOutcomeReceiptV1",
    "ConsolidationArtifactV1",
    "HumanOverrideV1",
]
HARD = {
    "authority",
    "truth",
    "privacy",
    "deletion",
    "writer_ownership",
    "objective_core",
}
LIFECYCLE = [
    "proposed",
    "built",
    "simulated",
    "qualified",
    "dormant",
    "canary",
    "active",
    "draining",
    "quarantined",
    "retired",
]

# These are reference-only packages that may be named by an organ while
# remaining outside the production module registry.  Keep this exception
# explicit in the architecture registry; an unregistered module binding must
# never be silently accepted by the closed-world verifier.
QUALIFICATION_REFERENCE_KEYS = ["id", "root", "scope"]


class DuplicateKey(ValueError):
    pass


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in items:
        if key in out:
            raise DuplicateKey(key)
        out[key] = value
    return out


def die(message: str) -> None:
    raise SystemExit("FAIL_HEPTA_CNS: " + message)


def need(condition: bool, message: str) -> None:
    if not condition:
        die(message)


def load(rel: str) -> dict[str, Any]:
    try:
        return json.loads(
            (ROOT / rel).read_text(encoding="utf-8"), object_pairs_hook=pairs
        )
    except Exception as exc:
        die(f"{rel}: {exc}")


def false_authority(value: Any, label: str) -> None:
    need(
        isinstance(value, dict) and list(value) == AUTHORITY_KEYS,
        label + " authority closure/order",
    )
    need(not any(bool(x) for x in value.values()), label + " positive authority")


def acyclic(nodes: list[str], edges: list[tuple[str, str]]) -> list[str]:
    ns = set(nodes)
    need(len(ns) == len(nodes), "duplicate graph node")
    indeg = {n: 0 for n in ns}
    out = defaultdict(list)
    for a, b in edges:
        need(a in ns and b in ns and a != b, "invalid graph edge")
        indeg[b] += 1
        out[a].append(b)
    q = deque(sorted(n for n in ns if indeg[n] == 0))
    order = []
    while q:
        n = q.popleft()
        order.append(n)
        for x in sorted(out[n]):
            indeg[x] -= 1
            if indeg[x] == 0:
                q.append(x)
    need(len(order) == len(ns), "body graph cycle")
    return order


def validate_module_bindings(
    organs: list[dict[str, Any]],
    module_ids: list[str] | set[str],
    qualification_references: list[dict[str, Any]],
) -> tuple[set[str], set[str]]:
    """Validate the bidirectional organ-to-module projection.

    Every production module must be bound by at least one organ, and every
    binding must resolve either to one of those registered modules or to an
    explicitly declared qualification reference.  Qualification references
    are intentionally kept separate from the forty production modules so a
    reference crate cannot acquire production identity by appearing in an
    organ binding.
    """
    registered = set(module_ids)
    need(len(registered) == len(module_ids), "duplicate registered module IDs")
    need(len(registered) == 40, "forty-module production registry")
    refs: dict[str, dict[str, Any]] = {}
    for row in qualification_references:
        need(
            isinstance(row, dict) and list(row) == QUALIFICATION_REFERENCE_KEYS,
            "qualification reference key closure/order",
        )
        identity = row["id"]
        need(
            isinstance(identity, str)
            and identity
            and identity not in registered
            and identity not in refs,
            "qualification reference identity",
        )
        need(
            isinstance(row["root"], str)
            and row["root"]
            and isinstance(row["scope"], str)
            and row["scope"] == "qualification_only_not_production_module",
            identity + " qualification reference posture",
        )
        refs[identity] = row

    bound = {module for organ in organs for module in organ["moduleBindings"]}
    allowed = registered | set(refs)
    need(not (bound - allowed), "unknown organ module binding")
    need(not (registered - bound), "unbound registered module")
    need(not (set(refs) - bound), "unbound qualification reference")
    # The two sides must be exact: no production module is represented only as
    # a qualification reference, and no qualification reference is promoted to
    # a production module by accident.
    need((bound & registered) == registered, "production module projection")
    need((bound - registered) == set(refs), "qualification module projection")
    return registered, set(refs)


def status_text(
    arch: dict[str, Any], protocols: dict[str, Any], gaps: dict[str, Any]
) -> str:
    external = gaps["externalCapabilityGates"]
    unit_vectors = sum(
        isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        for path in (ROOT / REFERENCE_DIR).glob("test_*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
    )
    return "\n".join(
        [
            "# Hepta CNS and Organ Reference Status",
            "",
            "**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.1.0-cns-organ  ",
            "**Repository specification/reference gaps:** `closed`  ",
            "**Production embodiment:** `not activated`  ",
            "**Longitudinal efficacy:** `not claimed`  ",
            "**Functional biomimicry:** `not claimed`",
            "",
            "## Closed reference surface",
            "",
            f"- Functional organs: **{len(arch['organs'])}**",
            f"- Typed cross-organ protocols: **{len(protocols['protocols'])}**",
            f"- Repository gaps with deterministic evidence: **{len(gaps['gaps'])}**",
            f"- External capability gates: **{len(external)}**",
            "- HNMF reference packages: **3**",
            f"- CNS deterministic unit vectors: **{unit_vectors}**",
            "- Positive authority flags: **0**",
            "",
            "Repository closure covers anatomy, lifecycle, dependency/fallback, local hot paths, homeostasis, sensor staleness, body generation, action gating, reflex veto, terminal-effect observation, next-snapshot topology, role separation, consolidation/unlearning and machine validation.",
            "",
            "Real sensors, actuators, target-host timing, physical safety, future-time learning, empirical biomimicry, operator acceptance and production rollout remain evidence gates that cannot be satisfied by repository prose or fixtures.",
            "",
        ]
    )


def verify() -> int:
    arch = load(ARCH_PATH)
    protocols = load(PROTOCOL_PATH)
    gaps = load(GAPS_PATH)
    need(
        arch.get("schema") == "hepta.cns-organ-architecture.v1"
        and arch.get("schemaVersion") == 1,
        "architecture schema",
    )
    need(
        arch.get("planVersion") == "8.1.0-cns-organ"
        and arch.get("parentPlanVersion") == "8.0.0",
        "architecture plan",
    )
    need(
        protocols.get("schema") == "hepta.cns-organ-protocol-registry.v1"
        and protocols.get("schemaVersion") == 1,
        "protocol schema",
    )
    need(
        gaps.get("schema") == "hepta.cns-organ-gap-ledger.v1"
        and gaps.get("schemaVersion") == 1,
        "gap schema",
    )
    for label, value in [
        ("architecture", arch),
        ("protocols", protocols),
        ("gaps", gaps),
    ]:
        false_authority(value.get("authorityFlags"), label)
    organs = arch["organs"]
    ids = [x["id"] for x in organs]
    need(
        ids == REQUIRED_ORGANS and arch["requiredOrganRoles"] == REQUIRED_ORGANS,
        "organ closed world/order",
    )
    need(len(set(ids)) == 24, "organ IDs")
    need(arch["organLifecycle"] == LIFECYCLE, "lifecycle")
    need(
        arch["structuralMutationGrammar"]
        == ["add", "split", "merge", "rewire", "retire"],
        "mutation grammar",
    )
    defaults = arch.get("organDefaults", {})
    need(defaults.get("centralSynchronousRpcAllowed") is False, "central RPC default")
    need(set(defaults.get("hardBoundaries", [])) == HARD, "hard boundary defaults")
    need(
        set(defaults.get("mutableSurface", []))
        == {
            "resource_allocation",
            "routing_weight",
            "soft_threshold",
            "activation_state",
        },
        "mutable surface defaults",
    )
    by_id = {x["id"]: x for x in organs}
    edges = []
    for row in organs:
        need(list(row) == ORGAN_KEYS, row["id"] + " key closure/order")
        need(
            row["moduleBindings"] and row["function"] and row["anatomicalRole"],
            row["id"] + " identity",
        )
        need(
            set(row["dependencies"]) <= set(ids)
            and set(row["fallbackOrgans"]) <= set(ids),
            row["id"] + " graph references",
        )
        need(
            row["id"] not in row["dependencies"]
            and row["id"] not in row["fallbackOrgans"],
            row["id"] + " self edge",
        )
        if row["essential"] and not row["fallbackOrgans"]:
            need(
                row["organClass"] in {"constitutional_kernel", "human_override"},
                row["id"] + " essential fallback",
            )
        if row["effectBoundary"]:
            need(
                row["id"] == "actuator.gateway",
                row["id"] + " unexpected effect boundary",
            )
        edges += [(dep, row["id"]) for dep in row["dependencies"]]
    order = acyclic(ids, edges)
    acyclic(
        ids,
        [(row["id"], fallback) for row in organs for fallback in row["fallbackOrgans"]],
    )
    ancestors = {}
    for organ_id in order:
        dependencies = set(by_id[organ_id]["dependencies"])
        for dependency in by_id[organ_id]["dependencies"]:
            dependencies.update(ancestors[dependency])
        ancestors[organ_id] = dependencies
    for row in organs:
        for fallback in row["fallbackOrgans"]:
            need(
                row["id"] not in ancestors[fallback],
                row["id"] + " fallback depends on failed organ",
            )
    modules = load("docs/modules/MODULES.json")["modules"]
    module_ids = [x["id"] for x in modules]
    mids = set(module_ids)
    validate_module_bindings(
        organs,
        module_ids,
        arch.get("qualificationReferences", []),
    )
    prows = protocols["protocols"]
    pids = [x["id"] for x in prows]
    need(pids == REQUIRED_PROTOCOLS and len(set(pids)) == 15, "protocol closed world")
    for row in prows:
        need(
            list(row) == ["id", "owner", "requiredFields"], row["id"] + " protocol keys"
        )
        need(
            (row["owner"] in by_id or row["owner"] in mids) and row["requiredFields"],
            row["id"] + " owner/fields",
        )
        need(
            len(row["requiredFields"]) == len(set(row["requiredFields"])),
            row["id"] + " duplicate field",
        )
    need(
        protocols["rules"]["queueAckMayEqualTerminalSuccess"] is False,
        "queue acknowledgement rule",
    )
    need(
        protocols["rules"]["modelOutputMayMintAuthority"] is False,
        "model authority rule",
    )
    need(
        gaps["allRepositoryGapsClosed"] is True
        and gaps["productionCapabilityClaimed"] is False,
        "gap truth posture",
    )
    grows = gaps["gaps"]
    need(
        len(grows) == 22
        and [x["id"] for x in grows] == [f"CNS-GAP-{i:03d}" for i in range(1, 23)],
        "gap closure",
    )
    for row in grows:
        need(
            row["state"] == "closed_reference" and row["evidence"],
            row["id"] + " state/evidence",
        )
        for path in row["evidence"]:
            need((ROOT / path).exists(), row["id"] + " missing evidence " + path)
    ext = gaps["externalCapabilityGates"]
    need(len(ext) == 8, "external gate count")
    need(
        all(
            x["repositoryMaySelfCertify"] is False
            and x["state"].startswith("requires_")
            for x in ext
        ),
        "external gate truth",
    )
    tech = (ROOT / TECHNICAL_PATH).read_text(encoding="utf-8")
    need(
        len(tech.encode()) >= 12000 and all(f"## {i}." in tech for i in range(1, 18)),
        "technical document depth",
    )
    for token in [
        "queue acknowledgement",
        "next-snapshot",
        "Human override",
        "HNMF",
        "local controllers",
    ]:
        need(token.lower() in tech.lower(), "technical token " + token)
    for path in [
        "docs/hnmf/GAPS.json",
        "docs/hnmf/HNMF.json",
        "docs/hnmf/MIGRATION.md",
        "docs/hnmf/TECHNICAL.md",
        "qualification/hnmf-reference/Cargo.toml",
        "qualification/hnmf-contract-reference/Cargo.toml",
        "qualification/hnmf-adversarial-reference/Cargo.toml",
        "scripts/hepta-hnmf.py",
        "docs/learning/PAPER_EVIDENCE_BINDINGS.json",
        "scripts/hepta-paper-evidence.py",
    ]:
        need((ROOT / path).is_file(), "missing integrated evidence " + path)
    unit = subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            str(ROOT / REFERENCE_DIR),
            "-p",
            "test_*.py",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    need(
        unit.returncode == 0,
        "CNS reference tests " + (unit.stderr or unit.stdout).strip(),
    )
    need(
        (ROOT / STATUS_PATH).read_text(encoding="utf-8")
        == status_text(arch, protocols, gaps),
        "CNS status stale",
    )
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_CNS_ORGAN_CLOSED_WORLD",
                "organs": 24,
                "protocols": 15,
                "repositoryGaps": 22,
                "externalCapabilityGates": 8,
                "topologicalOrderDigest": hashlib.sha256(
                    "\n".join(order).encode()
                ).hexdigest(),
                "authorityGranted": False,
            },
            sort_keys=True,
        )
    )
    return 0


def generate_status(check: bool) -> int:
    text = status_text(load(ARCH_PATH), load(PROTOCOL_PATH), load(GAPS_PATH))
    path = ROOT / STATUS_PATH
    if check:
        need(
            path.is_file() and path.read_text(encoding="utf-8") == text,
            "CNS status stale",
        )
    else:
        path.write_text(text, encoding="utf-8")
    print("PASS_HEPTA_CNS_STATUS" if check else "WROTE docs/cns/STATUS.md")
    return 0


def self_test() -> int:
    need(
        acyclic(["a", "b", "c"], [("a", "b"), ("b", "c")]) == ["a", "b", "c"],
        "acyclic fixture",
    )
    try:
        acyclic(["a", "b"], [("a", "b"), ("b", "a")])
        die("cycle accepted")
    except SystemExit as exc:
        if "body graph cycle" not in str(exc):
            raise
    try:
        json.loads('{"a":1,"a":2}', object_pairs_hook=pairs)
        die("duplicate accepted")
    except DuplicateKey:
        pass
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_CNS_SELF_TEST",
                "cases": ["acyclic", "cycle", "duplicate_key"],
                "authorityGranted": False,
            },
            sort_keys=True,
        )
    )
    return 0


def git(*args: str) -> str:
    p = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if p.returncode:
        die("git " + " ".join(args) + ": " + p.stderr.strip())
    return p.stdout.strip()


def receipt(kind: str, expected_sha: str, output: str) -> int:
    need(kind in {"source-head", "merge-candidate"}, "receipt kind")
    actual = git("rev-parse", "HEAD")
    need(actual == expected_sha, "receipt expected SHA")
    tree = git("rev-parse", "HEAD^{tree}")
    parents = git("rev-list", "--parents", "-n", "1", "HEAD").split()[1:]
    payload = {
        "schema": "hepta.cns-execution-receipt.v1",
        "kind": kind,
        "commit": actual,
        "tree": tree,
        "parents": parents,
        "architectureSha256": hashlib.sha256(
            (ROOT / ARCH_PATH).read_bytes()
        ).hexdigest(),
        "protocolSha256": hashlib.sha256(
            (ROOT / PROTOCOL_PATH).read_bytes()
        ).hexdigest(),
        "gapSha256": hashlib.sha256((ROOT / GAPS_PATH).read_bytes()).hexdigest(),
        "authorityGranted": False,
    }
    target = ROOT / output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


def receipt_verify(kind: str, expected_sha: str, input_path: str) -> int:
    p = load(input_path)
    actual = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    parents = git("rev-list", "--parents", "-n", "1", "HEAD").split()[1:]
    need(
        p.get("schema") == "hepta.cns-execution-receipt.v1" and p.get("kind") == kind,
        "receipt schema/kind",
    )
    need(
        actual == expected_sha == p.get("commit")
        and tree == p.get("tree")
        and parents == p.get("parents"),
        "receipt identity",
    )
    need(p.get("authorityGranted") is False, "receipt authority")
    for field, path in [
        ("architectureSha256", ARCH_PATH),
        ("protocolSha256", PROTOCOL_PATH),
        ("gapSha256", GAPS_PATH),
    ]:
        need(
            p.get(field) == hashlib.sha256((ROOT / path).read_bytes()).hexdigest(),
            "receipt source digest " + field,
        )
    if kind == "merge-candidate":
        need(
            len(parents) == 2 and len(set(parents)) == 2,
            "receipt synthetic merge parents",
        )
    print("PASS_HEPTA_CNS_RECEIPT")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("verify")
    sub.add_parser("self-test")
    g = sub.add_parser("generate-status")
    g.add_argument("--check", action="store_true")
    r = sub.add_parser("receipt")
    r.add_argument("--kind", required=True)
    r.add_argument("--expected-sha", required=True)
    r.add_argument("--output", required=True)
    rv = sub.add_parser("receipt-verify")
    rv.add_argument("--kind", required=True)
    rv.add_argument("--expected-sha", required=True)
    rv.add_argument("--input", required=True)
    a = p.parse_args()
    if a.command == "verify":
        return verify()
    if a.command == "self-test":
        return self_test()
    if a.command == "generate-status":
        return generate_status(a.check)
    if a.command == "receipt":
        return receipt(a.kind, a.expected_sha, a.output)
    return receipt_verify(a.kind, a.expected_sha, a.input)


if __name__ == "__main__":
    raise SystemExit(main())
