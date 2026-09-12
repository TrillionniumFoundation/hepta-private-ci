#!/usr/bin/env python3
"""Closed-world verifier for the canonical Hepta V8 development system."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hepta_workflow_commands import verify_synthetic_merge

ROOT = Path(__file__).resolve().parents[1]
PLAN_ID = "HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN"
VERSION = "8.0.0"
REPO = "TrillionniumFoundation/hepta-private-ci"
REPO_ID = 1320694176
DEFAULT_BRANCH = "main"
MODULE_VERIFIER = "scripts/hepta-module-docs.py"
ALGORITHM_VERIFIER = "scripts/hepta-algorithm-docs.py"
READINESS_VERIFIER = "scripts/hepta-readiness.py"
CNS_VERIFIER = "scripts/hepta-cns.py"
HNMF_VERIFIER = "scripts/hepta-hnmf.py"
READINESS_INDEX = "docs/readiness/READINESS.json"
READINESS_PROTOCOLS = "docs/readiness/PROTOCOLS.json"
READINESS_GAPS = "docs/readiness/GAPS.json"
CNS_ARCHITECTURE = "docs/cns/CNS_ARCHITECTURE.json"
CNS_GAPS = "docs/cns/GAPS.json"
HNMF_REGISTRY = "docs/hnmf/HNMF.json"
HNMF_GAPS = "docs/hnmf/GAPS.json"
OPENBAO_MATRIX = "qualification/openbao-compatibility/COMPATIBILITY_MATRIX.json"
WORKFLOW_REFERENCE_SCRIPTS = (
    "scripts/hepta-gap-closure.py",
    "scripts/hepta_source_registry_closure.py",
)
WORKFLOW_REFERENCE_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])(?P<path>\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml)(?![A-Za-z0-9_.-])"
)
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
FILES = {
    "current": "docs/CURRENT.json",
    "system": "docs/governance/DOCUMENT_SYSTEM.json",
    "architecture": "docs/architecture/ARCHITECTURE.json",
    "modules": "docs/modules/MODULES.json",
    "contracts": "docs/contracts/CONTRACTS.json",
    "protocols": "docs/contracts/PROTOCOL_SCHEMAS.json",
    "data": "docs/data/DATA_AUTHORITY.json",
    "work": "docs/delivery/WORK_PACKAGES.json",
    "development": "docs/delivery/DEVELOPMENT_DAG.json",
    "activation": "docs/delivery/ACTIVATION_DAG.json",
    "evidence_dag": "docs/delivery/EVIDENCE_DAG.json",
    "paths": "docs/delivery/PATH_OWNERSHIP.json",
    "objectives": "docs/control-plane/OBJECTIVES.json",
    "ndu": "docs/control-plane/NDU.json",
    "optimization": "docs/control-plane/OPTIMIZATION.json",
    "prompt": "docs/intelligence/PROMPT_INTERVENTIONS.json",
    "learning": "docs/learning/LEARNING_SYSTEM.json",
    "experiments": "docs/learning/EXPERIMENTS.json",
    "artifacts": "docs/learning/ARTIFACTS.json",
    "claims": "docs/evidence/CLAIMS.json",
    "qualification": "docs/evidence/QUALIFICATION.json",
    "evidence": "docs/evidence/INDEX.json",
    "threats": "docs/security/THREAT_MODEL.json",
    "module_docs": "docs/modules/MODULE_DOCS.json",
    "source_bindings": "docs/modules/SOURCE_BINDINGS.json",
    "algorithm_specs": "docs/learning/ALGORITHM_SPECS.json",
    "paper_traceability": "docs/learning/PAPER_TRACEABILITY.json",
}
SCHEMAS = {
    "current": "hepta.selected-development-source.v3",
    "system": "hepta.document-system.v6",
    "architecture": "hepta.architecture-model.v5",
    "modules": "hepta.module-registry.v7",
    "contracts": "hepta.contract-registry.v2",
    "protocols": "hepta.protocol-schema-registry.v3",
    "data": "hepta.data-authority-registry.v2",
    "work": "hepta.work-package-registry.v4",
    "development": "hepta.development-dag.v3",
    "activation": "hepta.activation-dag.v3",
    "evidence_dag": "hepta.evidence-dag.v3",
    "paths": "hepta.path-ownership.v3",
    "objectives": "hepta.global-objective-registry.v2",
    "ndu": "hepta.ndu-registry.v2",
    "optimization": "hepta.optimization-registry.v1",
    "prompt": "hepta.prompt-intervention-registry.v2",
    "learning": "hepta.learning-system.v2",
    "experiments": "hepta.experiment-registry.v1",
    "artifacts": "hepta.learning-artifact-registry.v1",
    "claims": "hepta.claim-registry.v1",
    "qualification": "hepta.qualification-registry.v2",
    "evidence": "hepta.evidence-index.v5",
    "threats": "hepta.threat-model.v2",
    "module_docs": "hepta.module-document-index.v2",
    "source_bindings": "hepta.module-source-binding.v2",
    "algorithm_specs": "hepta.algorithm-spec-registry.v1",
    "paper_traceability": "hepta.paper-traceability.v2",
}
RECEIPT_SCHEMA = "hepta.development-docs-execution-receipt.v6"
LEASE_KEYS = [
    "leaseId",
    "packageA",
    "packageB",
    "normalizedExactPaths",
    "pathSetSha256",
    "purpose",
    "status",
    "reviewBinding",
    "lifecycle",
    "authorityGranted",
    "authorityDelta",
]
LEASE_REVIEW_KEYS = [
    "identitySource",
    "repositorySource",
    "pullRequestSource",
    "baseSource",
    "headSource",
    "reviewCommitSource",
    "reviewerIdSource",
    "authorIdSource",
    "requiredState",
    "reviewCommitMustEqualHead",
    "reviewerMustDifferFromAuthor",
    "invalidateOnHeadChange",
    "reusable",
    "maximumAttestationAgeSeconds",
]
LEASE_LIFECYCLE = {
    "activation": "trusted_external_attestation_after_exact_changed_path_match",
    "changeSetBinding": "exact_normalized_lease_path_set",
    "expiresOn": "head_change_review_dismissal_or_ttl",
    "retention": "manifest_only_no_authority",
}


class DuplicateKey(ValueError):
    pass


def die(msg):
    raise SystemExit("FAIL_HEPTA_DEVELOPMENT_DOCS_V8: " + msg)


def need(ok, msg):
    if not ok:
        die(msg)


def verify_exact_workflow_references() -> None:
    """Reject stale exact workflow paths in canonical docs and source registries.

    Historical consolidation ledgers intentionally retain deleted paths and are
    excluded. Test fixtures also use synthetic workflow names; production
    verifier scripts listed above are scanned explicitly so their identity
    bindings cannot silently drift.
    """

    roots = [ROOT / "docs", ROOT / "qualification"]
    files: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in {".md", ".json"}:
                if "qualification/main-consolidation" in path.as_posix():
                    continue
                files.append(path)
    files.extend(ROOT / rel for rel in WORKFLOW_REFERENCE_SCRIPTS)

    missing: list[str] = []
    for path in sorted(set(files)):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in WORKFLOW_REFERENCE_RE.finditer(text):
            workflow = match.group("path")
            if not (ROOT / workflow).is_file():
                line = text.count("\n", 0, match.start()) + 1
                missing.append(f"{path.relative_to(ROOT)}:{line}: {workflow}")
    need(
        not missing,
        "stale exact workflow references:\n" + "\n".join(sorted(set(missing))),
    )


def pairs(items):
    out = {}
    for k, v in items:
        if k in out:
            raise DuplicateKey(k)
        out[k] = v
    return out


def load(rel):
    try:
        return json.loads(
            (ROOT / rel).read_text(encoding="utf-8"), object_pairs_hook=pairs
        )
    except Exception as exc:
        die(f"{rel}: {exc}")


def load_path(path):
    target = Path(path)
    if not target.is_absolute():
        target = ROOT / target
    try:
        return json.loads(target.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except Exception as exc:
        die(f"{target}: {exc}")


def git(*args, check=True):
    p = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and p.returncode:
        die("git " + " ".join(args) + ": " + p.stderr.strip())
    return p.stdout.strip()


def tracked():
    try:
        return sorted(x for x in git("ls-files", "-z").split("\0") if x)
    except SystemExit:
        return sorted(
            str(p.relative_to(ROOT)).replace("\\", "/")
            for p in ROOT.rglob("*")
            if p.is_file()
        )


def parse_utc(value, label):
    need(isinstance(value, str) and value.strip(), label + " missing")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        die(label + " invalid: " + str(exc))
    need(dt.tzinfo is not None, label + " timezone")
    return dt.astimezone(timezone.utc)


def normalized_utc(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_observation(value, policy, now=None):
    observed = parse_utc(value, "observation timestamp")
    checked = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    skew = int(policy["maximumClockSkewSeconds"])
    ttl = int(policy["dynamicReceiptTtlSeconds"])
    need(skew >= 0 and 0 < ttl <= 604800, "dynamic observation bounds")
    delta = (observed - checked).total_seconds()
    if policy["futureTimestampAllowed"] is False:
        need(delta <= skew, "future observation exceeds clock skew")
    age = (checked - observed).total_seconds()
    need(age <= ttl, "stale observation exceeds TTL")
    return {
        "status": "PASS_HEPTA_DYNAMIC_TIME_EVIDENCE",
        "observedAt": normalized_utc(observed),
        "checkedAt": normalized_utc(checked),
        "ageSeconds": max(0, int(age)),
        "futureSkewSeconds": max(0, int(delta)),
        "maximumClockSkewSeconds": skew,
        "ttlSeconds": ttl,
        "futureTimestampAllowed": policy["futureTimestampAllowed"],
    }


def event_context():
    event = {}
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if event_path and Path(event_path).is_file():
        try:
            event = json.loads(
                Path(event_path).read_text(encoding="utf-8"), object_pairs_hook=pairs
            )
        except Exception as exc:
            die("GitHub event: " + str(exc))
    pr = event.get("pull_request") or {}
    return {
        "event": event,
        "pr": pr,
        "number": pr.get("number") or event.get("number"),
        "base": (pr.get("base") or {}).get("sha"),
        "source": (pr.get("head") or {}).get("sha"),
        "eventMerge": pr.get("merge_commit_sha"),
    }


def shape_paths(v, p="$"):
    out = {p}
    if isinstance(v, dict):
        for k, c in v.items():
            out |= shape_paths(c, f"{p}.{k}")
    elif isinstance(v, list):
        out.add(p + "[]")
        for c in v:
            out |= shape_paths(c, p + "[]")
    else:
        out.add(p + ":" + type(v).__name__)
    return out


def shape_sha(v):
    return hashlib.sha256("\n".join(sorted(shape_paths(v))).encode()).hexdigest()


def prefix(x):
    for s in ("/**", "/*"):
        if x.endswith(s):
            return x[: -len(s)].rstrip("/")
    return x.rstrip("/")


def overlaps(a, b):
    left = prefix(a)
    right = prefix(b)
    if left == right or left.startswith(right + "/") or right.startswith(left + "/"):
        return True
    left_glob = "*" in a
    right_glob = "*" in b
    if left_glob and not right_glob:
        return glob_path_matches(a, b)
    if right_glob and not left_glob:
        return glob_path_matches(b, a)
    if left_glob and right_glob:
        return a.rpartition("/")[0] == b.rpartition("/")[0]
    return False


def glob_path_matches(pattern, exact):
    pattern_parts = pattern.split("/")
    exact_parts = exact.split("/")
    return len(pattern_parts) == len(exact_parts) and all(
        fnmatch.fnmatchcase(value, part)
        for part, value in zip(pattern_parts, exact_parts, strict=True)
    )


def canonical_exact_path(value, label):
    need(isinstance(value, str) and value, label + " missing")
    need(value == value.strip(), label + " surrounding whitespace")
    need(
        not value.startswith(("/", "~"))
        and not value.endswith("/")
        and "\\" not in value
        and "//" not in value
        and not any(char in value for char in "*?[]{}!%"),
        label + " must be a canonical exact POSIX path",
    )
    parts = value.split("/")
    need(
        all(part not in {"", ".", ".."} for part in parts),
        label + " path alias or escape",
    )
    need(parts[0] != ".git", label + " protected Git path")
    need(
        all(
            all(ord(char) >= 32 and ord(char) != 127 for char in part) for part in parts
        ),
        label + " control character",
    )
    normalized = "/".join(parts)
    need(normalized == value, label + " normalization mismatch")
    return normalized


def is_exact_path(value):
    return not value.endswith(("/**", "/*")) and not any(
        char in value for char in "*?[]{}!%"
    )


def validate_allowed_path_pattern(value, label):
    need(isinstance(value, str) and value, label + " missing")
    if value.endswith(("/**", "/*")):
        canonical_exact_path(prefix(value), label + " prefix")
        return
    wildcard_count = value.count("*")
    if wildcard_count:
        need(
            wildcard_count == 1
            and not any(char in value for char in "?[]{}!%")
            and "*" in value.rpartition("/")[2],
            label + " unsupported wildcard grammar",
        )
        canonical_exact_path(value.replace("*", "WILDCARD"), label + " pattern")
        return
    canonical_exact_path(value, label)


def leasable_overlap_path(left, right, label):
    if not overlaps(left, right):
        return None
    left_exact = is_exact_path(left)
    right_exact = is_exact_path(right)
    if left_exact:
        left = canonical_exact_path(left, label + " left")
    if right_exact:
        right = canonical_exact_path(right, label + " right")
    if left_exact and right_exact:
        need(left == right, label + " prefix widening cannot be leased")
        return left
    if left_exact:
        need(
            glob_path_matches(right, left)
            if "*" in right and not right.endswith(("/**", "/*"))
            else left == prefix(right) or left.startswith(prefix(right) + "/"),
            label + " wildcard expansion mismatch",
        )
        return left
    if right_exact:
        need(
            glob_path_matches(left, right)
            if "*" in left and not left.endswith(("/**", "/*"))
            else right == prefix(left) or right.startswith(prefix(left) + "/"),
            label + " wildcard expansion mismatch",
        )
        return right
    die(label + " wildcard-to-wildcard overlap cannot be leased")


def lease_path_set_sha(paths):
    return hashlib.sha256(("\n".join(paths) + "\n").encode()).hexdigest()


def validate_path_leases(path_registry, packages, dev, act, changed_paths=None):
    need(
        path_registry.get("schema") == "hepta.path-ownership.v3"
        and path_registry.get("schemaVersion") == 3,
        "path lease schema version",
    )
    need(
        path_registry.get("rules")
        == {
            "onePrimaryOwnerPerPath": True,
            "foreignNamespaceRequiresCoOwner": True,
            "overlapRequiresDagOrderingOrLease": True,
            "unboundedRepositoryScopeAllowed": False,
        },
        "path ownership rules",
    )
    package_ids = {package["id"] for package in packages}
    for package in packages:
        for path in package["allowedWritePaths"]:
            validate_allowed_path_pattern(path, package["id"] + " allowed path")
    required = {}
    for index, package_a in enumerate(packages):
        for package_b in packages[index + 1 :]:
            pair = tuple(sorted((package_a["id"], package_b["id"])))
            ordered = (
                package_b["id"] in dev[package_a["id"]]
                or package_a["id"] in dev[package_b["id"]]
                or package_b["id"] in act[package_a["id"]]
                or package_a["id"] in act[package_b["id"]]
            )
            if ordered:
                continue
            overlap_paths = set()
            for left in package_a["allowedWritePaths"]:
                for right in package_b["allowedWritePaths"]:
                    overlap_path = leasable_overlap_path(
                        left,
                        right,
                        "path overlap " + pair[0] + "/" + pair[1],
                    )
                    if overlap_path is not None:
                        overlap_paths.add(overlap_path)
            if overlap_paths:
                required[pair] = tuple(sorted(overlap_paths))

    leases = path_registry.get("activeLeases")
    need(isinstance(leases, list), "active leases")
    declared = {}
    lease_ids = set()
    lease_paths = set()
    for lease in leases:
        need(isinstance(lease, dict), "lease object")
        need(list(lease) == LEASE_KEYS, "lease key closure/order")
        lease_id = lease.get("leaseId")
        need(
            isinstance(lease_id, str)
            and re.fullmatch(r"LEASE-[A-Z0-9]+(?:-[A-Z0-9]+)*-[0-9]{3}", lease_id)
            and lease_id not in lease_ids,
            "lease ID",
        )
        lease_ids.add(lease_id)
        package_a = lease.get("packageA")
        package_b = lease.get("packageB")
        need(
            package_a in package_ids
            and package_b in package_ids
            and package_a < package_b,
            lease_id + " canonical package pair",
        )
        pair = (package_a, package_b)
        need(pair not in declared, lease_id + " duplicate package pair")
        paths = lease.get("normalizedExactPaths")
        need(isinstance(paths, list) and paths, lease_id + " exact paths")
        normalized = [canonical_exact_path(path, lease_id + " path") for path in paths]
        need(
            normalized == sorted(set(normalized)),
            lease_id + " path order/uniqueness",
        )
        for path in normalized:
            need(path not in lease_paths, lease_id + " path leased more than once")
            lease_paths.add(path)
        need(
            lease.get("pathSetSha256") == lease_path_set_sha(normalized),
            lease_id + " path-set digest",
        )
        need(
            isinstance(lease.get("purpose"), str)
            and re.fullmatch(r"[a-z][a-z0-9_]{0,127}", lease["purpose"]),
            lease_id + " purpose",
        )
        need(
            lease.get("status") == "requires_external_attestation",
            lease_id + " external attestation posture",
        )
        review = lease.get("reviewBinding")
        need(
            isinstance(review, dict) and list(review) == LEASE_REVIEW_KEYS,
            lease_id + " review binding key closure/order",
        )
        need(
            {
                key: review.get(key)
                for key in LEASE_REVIEW_KEYS
                if key != "maximumAttestationAgeSeconds"
            }
            == {
                "identitySource": "github_pull_request_review",
                "repositorySource": "github.event.repository.id",
                "pullRequestSource": "github.event.pull_request.number",
                "baseSource": "github.event.pull_request.base.sha",
                "headSource": "github.event.pull_request.head.sha",
                "reviewCommitSource": "github.event.review.commit_id",
                "reviewerIdSource": "github.event.review.user.id",
                "authorIdSource": "github.event.pull_request.user.id",
                "requiredState": "approved",
                "reviewCommitMustEqualHead": True,
                "reviewerMustDifferFromAuthor": True,
                "invalidateOnHeadChange": True,
                "reusable": False,
            }
            and type(review.get("maximumAttestationAgeSeconds")) is int
            and 0 < review["maximumAttestationAgeSeconds"] <= 604800,
            lease_id + " exact-head external review policy",
        )
        need(
            lease.get("lifecycle") == LEASE_LIFECYCLE,
            lease_id + " lifecycle",
        )
        need(
            lease.get("authorityGranted") is False
            and lease.get("authorityDelta") == "none",
            lease_id + " authority posture",
        )
        declared[pair] = tuple(normalized)

    need(set(declared) == set(required), "missing or unused path lease")
    for pair, paths in required.items():
        need(declared[pair] == paths, "lease path mismatch " + "/".join(pair))

    if changed_paths is not None:
        changed = {canonical_exact_path(path, "changed path") for path in changed_paths}
        for pair, paths in declared.items():
            path_set = set(paths)
            prefix_aliases = {
                path
                for path in changed
                if any(overlaps(path, leased) and path != leased for leased in path_set)
            }
            need(not prefix_aliases, "changed path prefix aliases a lease")
            touched = changed & path_set
            if touched:
                need(
                    touched == path_set,
                    "changed leased path set must equal manifest " + "/".join(pair),
                )
                die("external path lease attestation required " + "/".join(pair))
    return {
        "declaredLeaseCount": len(declared),
        "leasedPathCount": len(lease_paths),
        "touchedLeaseCount": 0,
        "externallyAttestedLeaseCount": 0,
    }


def pull_request_changed_paths():
    context = event_context()
    base = context["base"]
    source = context["source"]
    if base is None and source is None:
        return None
    need(
        isinstance(base, str)
        and isinstance(source, str)
        and re.fullmatch(r"[0-9a-f]{40}", base)
        and re.fullmatch(r"[0-9a-f]{40}", source),
        "pull-request base/source identity",
    )
    repository = context["event"].get("repository") or {}
    need(
        repository.get("id") == REPO_ID
        and repository.get("full_name") == REPO
        and type(context["number"]) is int
        and context["number"] > 0,
        "pull-request repository/number identity",
    )
    git("cat-file", "-e", base + "^{commit}")
    git("cat-file", "-e", source + "^{commit}")
    actual = git("rev-parse", "HEAD")
    if actual != source:
        parents = git("rev-list", "--parents", "-n", "1", "HEAD").split()[1:]
        need(
            len(parents) == 2 and parents == [base, source],
            "checkout is neither source head nor exact synthetic merge",
        )
    process = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "diff",
            "--name-only",
            "--no-renames",
            "-z",
            base + "..." + source,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    need(process.returncode == 0, "pull-request changed-path diff")
    try:
        raw = process.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        die("pull-request changed path is not UTF-8: " + str(exc))
    return {
        canonical_exact_path(path, "pull-request changed path")
        for path in raw.split("\0")
        if path
    }


def acyclic(nodes, edges, label):
    ns = set(nodes)
    need(len(ns) == len(nodes), label + " duplicate node")
    ind = {n: 0 for n in ns}
    out = defaultdict(list)
    seen = set()
    for e in edges:
        a, b = e.get("from"), e.get("to")
        need(
            a in ns and b in ns and a != b and (a, b) not in seen,
            f"{label} edge {a}->{b}",
        )
        seen.add((a, b))
        ind[b] += 1
        out[a].append(b)
    q = deque(sorted(n for n in ns if ind[n] == 0))
    count = 0
    while q:
        n = q.popleft()
        count += 1
        for x in sorted(out[n]):
            ind[x] -= 1
            if ind[x] == 0:
                q.append(x)
    need(count == len(ns), label + " cycle")


def reach(nodes, edges):
    out = defaultdict(list)
    for e in edges:
        out[e["from"]].append(e["to"])
    ans = {n: set() for n in nodes}
    for n in nodes:
        stack = list(out[n])
        while stack:
            x = stack.pop()
            if x in ans[n]:
                continue
            ans[n].add(x)
            stack.extend(out[x])
    return ans


def subordinate_state():
    readiness = load(READINESS_INDEX)
    readiness_protocols = load(READINESS_PROTOCOLS)
    readiness_gaps = load(READINESS_GAPS)
    cns = load(CNS_ARCHITECTURE)
    cns_gaps = load(CNS_GAPS)
    hnmf = load(HNMF_REGISTRY)
    hnmf_gaps = load(HNMF_GAPS)
    return {
        "readiness": readiness,
        "readiness_protocols": readiness_protocols,
        "readiness_gaps": readiness_gaps,
        "cns": cns,
        "cns_gaps": cns_gaps,
        "hnmf": hnmf,
        "hnmf_gaps": hnmf_gaps,
    }


def status_text(d):
    states = Counter(x["state"] for x in d["work"]["packages"])
    cur = d["current"]
    sub = subordinate_state()
    openbao = load(OPENBAO_MATRIX)
    openbao_target = openbao["target"]
    openbao_capabilities = openbao["capabilities"]
    openbao_blockers = [
        row["id"]
        for row in openbao_capabilities
        if row.get("blocking") is True and row.get("status") != "closed"
    ]
    openbao_closed = sum(row.get("status") == "closed" for row in openbao_capabilities)
    lines = [
        "# Hepta Selected Development Source Status",
        "",
        "> Generated by `python3 scripts/hepta-docs.py generate-status`. Do not edit by hand.",
        "",
        f"**Plan:** `{PLAN_ID}` v{VERSION}",
        f"**Repository:** `{cur['repository']['fullName']}`",
        f"**Exact cleanup base:** `{cur['repository']['exactBaseHead']}` / `{cur['repository']['exactBaseTree']}`",
        "**Live source and target:** `external exact-candidate receipt required`",
        f"**Current package:** `{cur['currentWorkPackage']}`",
        "",
        "Dynamic Git, branch, pull-request, CI, review, operator, selection, promotion and release facts are external exact-candidate receipts and are not cached in this file.",
        "",
        "## Registry closure",
        "",
        f"- Modules: **{len(d['modules']['modules'])}**",
        f"- Contracts: **{len(d['contracts']['contracts'])}**",
        f"- Critical protocols: **{len(d['protocols']['protocols'])}**",
        f"- Durable data domains: **{len(d['data']['domains'])}**",
        f"- Work packages: **{len(d['work']['packages'])}**",
        f"- Module technical guides: **{len(d['module_docs']['modules'])}**",
        f"- Source bindings: **{len(d['source_bindings']['bindings'])}**",
        f"- Adaptive algorithm specifications: **{len(d['algorithm_specs']['documents'])}**",
        f"- Paper source locks: **{len(d['paper_traceability']['papers'])}**",
        f"- Pre-coding readiness specifications: **{len(sub['readiness']['documents'])}**",
        f"- Readiness protocols: **{len(sub['readiness_protocols']['protocols'])}**",
        f"- Closed readiness documentation gaps: **{len(sub['readiness_gaps']['gaps'])}**",
        f"- CNS functional organs: **{len(sub['cns']['organs'])}**",
        f"- CNS repository reference gaps: **{len(sub['cns_gaps']['gaps'])}**",
        f"- HNMF reference gaps: **{len(sub['hnmf_gaps']['gaps'])}**",
        "",
        "## Work-package states",
        "",
        "| State | Count |",
        "|---|---:|",
    ]
    for k, v in sorted(states.items()):
        lines.append(f"| `{k}` | {v} |")
    lines += ["", "## Baseline claims", "", "| Claim | Current level |", "|---|---|"]
    for k, v in cur["baselineClaims"].items():
        lines.append(f"| `{k}` | `{v}` |")
    lines += [
        "",
        "## Authority posture",
        "",
        "Every canonical and subordinate authority flag is present and false. Documentation readiness, source presence, a generated file, a queued workflow or a fixture is not runtime activation, efficacy, selection, merge, operator acceptance, promotion or release.",
        "",
        "## OpenBao replacement gate",
        "",
        f"- Target: **{openbao_target['product']} {openbao_target['version']}** (`{openbao_target['profile']}`)",
        f"- Compatibility capabilities: **{len(openbao_capabilities)}**",
        f"- Closed capabilities: **{openbao_closed}**",
        f"- Blocking capabilities: **{len(openbao_blockers)}**",
        "- Gate: `python3 scripts/verify_openbao_compatibility.py`",
        "- A capability cannot close from documentation or scoped tests alone; it requires native implementation, a named product caller, versioned interoperability evidence and applicable independent operational evidence.",
        "",
    ]
    return "\n".join(lines)


def verify_legacy(system, paths):
    rules = [
        (x["id"], re.compile(x["regex"], re.I))
        for x in system["forbiddenLegacyPathRules"]
    ]
    hits = []
    for path in paths:
        if path in system["canonicalPaths"]:
            continue
        for name, rx in rules:
            if rx.search(path):
                hits.append((path, name))
                break
    need(not hits, "legacy paths " + repr(hits[:20]))
    allowed = set(system["referenceScanPolicy"]["allowedReferenceFiles"])
    exts = set(system["referenceScanPolicy"]["scanExtensions"])
    rr = [
        (x["id"], re.compile(x["regex"], re.I))
        for x in system["forbiddenLegacyReferenceRules"]
    ]
    hits = []
    for path in paths:
        if path in allowed or Path(path).suffix.lower() not in exts:
            continue
        try:
            text = (ROOT / path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for name, rx in rr:
            if rx.search(text):
                hits.append((path, name))
                break
    need(not hits, "dangling legacy references " + repr(hits[:20]))


def deleted_json_basename_pattern(old_path):
    basename = re.escape(Path(old_path).name)
    return re.compile(rf"(?<![A-Za-z0-9_.-]){basename}(?![A-Za-z0-9_.-])")


def verify_cleanup_base(system):
    policy = system["knownLegacyDeletion"]
    probe = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--is-inside-work-tree"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if probe.returncode != 0:
        return {
            "evaluated": False,
            "reason": "not_a_git_worktree",
            "expectedDeletionCount": policy["exactPathCount"],
        }
    base = policy["exactBaseHead"]
    base_tree = policy["exactBaseTree"]
    need(git("rev-parse", base + "^{commit}") == base, "cleanup base commit")
    need(git("rev-parse", base + "^{tree}") == base_tree, "cleanup base tree")
    for path, expected in policy["exactGitObjects"].items():
        need(
            git("rev-parse", base + ":" + path) == expected,
            "cleanup base object " + path,
        )
    snap = policy["copiedSnapshotPath"]
    snapshot = [
        x
        for x in git("ls-tree", "-r", "--name-only", base, "--", snap).splitlines()
        if x
    ]
    need(
        len(snapshot) == policy["copiedSnapshotDescendantCount"],
        "cleanup snapshot descendant count",
    )
    need(
        len(snapshot) == len(set(snapshot))
        and all(x.startswith(snap + "/") for x in snapshot),
        "cleanup snapshot inventory",
    )
    expected = sorted(snapshot + policy["directPaths"])
    need(
        len(expected) == policy["exactPathCount"]
        and len(expected) == len(set(expected)),
        "cleanup exact inventory count",
    )
    raw = git("diff", "--name-status", "--no-renames", base + "..HEAD", "--")
    deleted = []
    unexpected_status = []
    for line in raw.splitlines():
        if not line:
            continue
        parts = line.split("\t", 1)
        need(len(parts) == 2, "cleanup diff row")
        status, path = parts
        if status == "D":
            deleted.append(path)
        elif status.startswith("R") or status.startswith("C"):
            unexpected_status.append(line)
    need(
        not unexpected_status,
        "cleanup rename/copy status " + repr(unexpected_status[:10]),
    )
    # Preserve the historical retirement without forbidding later reviewed deletions.
    need(set(expected) <= set(deleted), "retired legacy paths reintroduced")
    code_exts = {
        ".rs",
        ".py",
        ".toml",
        ".yaml",
        ".yml",
        ".sh",
        ".bzl",
        ".bazel",
        ".js",
        ".ts",
        ".tsx",
        ".go",
        ".c",
        ".cc",
        ".h",
        ".hpp",
    }
    retained = []
    for path in tracked():
        if (
            path == "docs/governance/DOCUMENT_SYSTEM.json"
            or Path(path).suffix.lower() not in code_exts
        ):
            continue
        try:
            retained.append(
                (path, (ROOT / path).read_text(encoding="utf-8", errors="ignore"))
            )
        except OSError:
            pass
    consumer_hits = []
    for old_path in expected:
        if not old_path.lower().endswith(".json"):
            continue
        basename_pattern = deleted_json_basename_pattern(old_path)
        for path, text in retained:
            if old_path in text or basename_pattern.search(text):
                consumer_hits.append({"retainedPath": path, "deletedJson": old_path})
    need(not consumer_hits, "deleted JSON consumer " + repr(consumer_hits[:10]))
    ancestor = subprocess.run(
        ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", base, "HEAD"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    need(ancestor.returncode == 0, "cleanup base is not ancestor")
    head = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    parents = git("rev-list", "--parents", "-n", "1", "HEAD").split()[1:]
    return {
        "evaluated": True,
        "baseHead": base,
        "baseTree": base_tree,
        "head": head,
        "tree": tree,
        "parents": parents,
        "snapshotDescendantCount": len(snapshot),
        "expectedDeletionCount": len(expected),
        "observedDeletionCount": len(deleted),
        "exactObjectCount": len(policy["exactGitObjects"]),
        "retainedDeletedJsonConsumerHits": 0,
        "inventorySha256": hashlib.sha256(
            ("\n".join(expected) + "\n").encode()
        ).hexdigest(),
    }


def verify() -> int:
    verify_exact_workflow_references()
    module_index = load(FILES["module_docs"])
    algorithm_index = load(FILES["algorithm_specs"])
    readiness_index = load(READINESS_INDEX)
    technical_paths = [x["path"] for x in module_index["modules"]]
    algorithm_paths = [x["path"] for x in algorithm_index["documents"]]
    readiness_paths = [x["path"] for x in readiness_index["documents"]]
    req = [
        "README.md",
        "docs/DEVELOPMENT.md",
        "docs/STATUS.md",
        "docs/modules/README.md",
        "docs/learning/README.md",
        "docs/learning/ALGORITHM_STATUS.md",
        "docs/learning/PAPER_EVIDENCE_BINDINGS.json",
        "docs/readiness/README.md",
        READINESS_INDEX,
        READINESS_PROTOCOLS,
        READINESS_GAPS,
        "docs/readiness/STATUS.md",
        "docs/cns/README.md",
        CNS_ARCHITECTURE,
        "docs/cns/ORGAN_PROTOCOLS.json",
        CNS_GAPS,
        "docs/cns/STATUS.md",
        "docs/cns/TECHNICAL.md",
        "docs/hnmf/README.md",
        HNMF_REGISTRY,
        HNMF_GAPS,
        "docs/hnmf/MIGRATION.md",
        "docs/hnmf/TECHNICAL.md",
        "scripts/hepta-docs.py",
        MODULE_VERIFIER,
        ALGORITHM_VERIFIER,
        READINESS_VERIFIER,
        CNS_VERIFIER,
        HNMF_VERIFIER,
        "scripts/hepta-paper-evidence.py",
        ".github/workflows/hepta-development-docs.yml",
        ".github/workflows/hepta-algorithm-docs.yml",
        ".github/workflows/hepta-implementation-readiness.yml",
        ".github/workflows/hepta-cns-embodiment.yml",
        ".github/workflows/hnmf-qualification.yml",
        *FILES.values(),
        *technical_paths,
        *algorithm_paths,
        *readiness_paths,
    ]
    for rel in req:
        need((ROOT / rel).is_file(), "missing " + rel)
    d = {k: load(v) for k, v in FILES.items()}
    for k, s in SCHEMAS.items():
        need(d[k].get("schema") == s, "schema " + k)
    for k, v in d.items():
        need(
            v.get("planId") == PLAN_ID and v.get("planVersion") == VERSION,
            "plan binding " + k,
        )
        f = v.get("authorityFlags")
        need(
            isinstance(f, dict) and list(f) == AUTHORITY_KEYS,
            k + " authority key closure",
        )
        need(not any(f.values()), k + " positive authority")
    cur = d["current"]
    r = cur["repository"]
    need(
        (r["id"], r["fullName"], r["defaultBranch"]) == (REPO_ID, REPO, DEFAULT_BRANCH),
        "repository identity",
    )
    need(
        r["exactBaseHead"] == "b621768b70a09d56626bb8a2c331e3dc424e6a4d"
        and r["exactBaseTree"] == "f2e82fd525d337efae355adf6f19398812d4180c",
        "base identity",
    )
    policy = cur["dynamicObservationPolicy"]
    need(
        policy["cachedGitOrCiStatusAllowed"] is False
        and policy["externalExactCandidateReceiptRequired"] is True,
        "dynamic observation authority",
    )
    need(
        policy["futureTimestampAllowed"] is False
        and int(policy["maximumClockSkewSeconds"]) == 300,
        "dynamic observation future policy",
    )
    need(
        0 < int(policy["dynamicReceiptTtlSeconds"]) <= 604800, "dynamic observation TTL"
    )
    candidate = cur["candidate"]
    need(candidate.get("pullRequest") is None, "cached pull-request number")
    for key in ("targetBranch", "sourceHead", "sourceTree", "mergeCandidate"):
        need(
            candidate.get(key) == "resolved_by_external_exact_candidate_receipt",
            "cached dynamic candidate " + key,
        )
    need(
        candidate.get("relationship") == "not_cached_dynamic_external_receipt_required",
        "cached branch relationship",
    )
    system = d["system"]
    need(
        system["canonicalHumanDevelopmentDocument"] == "docs/DEVELOPMENT.md",
        "human authority",
    )
    need(
        system.get("subordinateRegistries")
        == [
            {
                "id": "HEPTA-ADAPTIVE-ALGORITHMS",
                "registryPath": "docs/learning/ALGORITHM_SPECS.json",
                "statusPath": "docs/learning/ALGORITHM_STATUS.md",
                "validator": "python3 scripts/hepta-algorithm-docs.py verify",
                "workflow": ".github/workflows/hepta-algorithm-docs.yml",
                "authorityGranted": False,
            },
            {
                "id": "HEPTA-V8-PRECODING-READINESS",
                "registryPath": READINESS_INDEX,
                "statusPath": "docs/readiness/STATUS.md",
                "validator": "python3 scripts/hepta-readiness.py verify",
                "workflow": ".github/workflows/hepta-implementation-readiness.yml",
                "authorityGranted": False,
            },
            {
                "id": "HEPTA-CNS-ORGAN-ARCHITECTURE",
                "registryPath": CNS_ARCHITECTURE,
                "statusPath": "docs/cns/STATUS.md",
                "validator": "python3 scripts/hepta-cns.py verify",
                "workflow": ".github/workflows/hepta-cns-embodiment.yml",
                "authorityGranted": False,
            },
            {
                "id": "HEPTA-HNMF-QUALIFICATION",
                "registryPath": HNMF_REGISTRY,
                "statusPath": None,
                "validator": "python3 scripts/hepta-hnmf.py verify",
                "workflow": ".github/workflows/hnmf-qualification.yml",
                "authorityGranted": False,
            },
        ],
        "subordinate registry closure",
    )
    need(
        d["protocols"].get("subordinateProtocolRegistries")
        == [
            {
                "id": "HEPTA-V8-PRECODING-READINESS",
                "path": READINESS_PROTOCOLS,
                "validator": "python3 scripts/hepta-readiness.py verify",
                "namespace": "implementation_readiness",
                "protocolCount": 31,
                "authorityDelta": "none",
            }
        ],
        "subordinate protocol registry closure",
    )
    need(set(system["canonicalPaths"]) == set(req), "canonical path set")
    closures = {x["path"]: x for x in system["registryShapeClosures"]}
    need(
        set(closures) == set(FILES.values()) - {"docs/governance/DOCUMENT_SYSTEM.json"},
        "shape closure coverage",
    )
    for k, rel in FILES.items():
        if k == "system":
            continue
        row = closures[rel]
        need(row["topLevelKeys"] == list(d[k]), "top-level closure " + rel)
        need(row["recursiveShapeSha256"] == shape_sha(d[k]), "recursive closure " + rel)
    paths = tracked()
    verify_legacy(system, paths)
    cleanup = verify_cleanup_base(system)
    need(
        cleanup["evaluated"] or not (ROOT / ".git").exists(),
        "cleanup inventory not evaluated",
    )
    mods = d["modules"]["modules"]
    mids = {m["id"] for m in mods}
    need(len(mids) == len(mods), "module IDs")
    roots = {}
    writers = {}
    for m in mods:
        need(
            m["owner"] and m["deputy"] and m["rootBindings"],
            "module ownership " + m["id"],
        )
        for rb in m["rootBindings"]:
            need(rb["path"] not in roots, "root owner " + rb["path"])
            roots[rb["path"]] = m["id"]
        for dom in m["writes"]:
            need(dom not in writers, "writer " + dom)
            writers[dom] = m["id"]
        for dep in m["uses"]:
            need(dep in mids, "module dependency " + m["id"] + "->" + dep)
    acyclic(
        [m["id"] for m in mods],
        [{"from": x, "to": m["id"]} for m in mods for x in m["uses"]],
        "module graph",
    )
    contracts = d["contracts"]["contracts"]
    cids = {x["id"] for x in contracts}
    need(len(cids) == len(contracts), "contract IDs")
    for c in contracts:
        need(
            c["producer"] in mids
            and set(c["consumers"]) <= mids
            and c["bounded"]
            and c["authorityDelta"] == "none",
            "contract " + c["id"],
        )
    protocols = d["protocols"]["protocols"]
    pids = {x["id"] for x in protocols}
    need(len(pids) == len(protocols), "protocol IDs")
    for p in protocols:
        need(
            p["maximumEncodedBytes"] > 0
            and p["denyUnknownCriticalFields"]
            and p["fields"],
            "protocol " + p["id"],
        )
        names = [x["name"] for x in p["fields"]]
        need(len(names) == len(set(names)), "protocol duplicate field " + p["id"])
        for f in p["fields"]:
            if f["type"] in {
                "utf8",
                "bounded_array",
                "bounded_object",
                "bounded_vector",
                "bounded_fixed_point_vector",
                "bounded_probability_vector",
                "id128",
                "sha256",
            }:
                need(
                    "maxBytes" in f
                    or f["type"]
                    not in {
                        "utf8",
                        "bounded_array",
                        "bounded_object",
                        "bounded_vector",
                        "bounded_fixed_point_vector",
                        "bounded_probability_vector",
                    },
                    "unbounded field " + p["id"] + "." + f["name"],
                )
    domains = d["data"]["domains"]
    need(len(domains) == len({x["id"] for x in domains}), "data IDs")
    for x in domains:
        need(
            x["authoritativeWriter"] in mids
            and x["schemaOwner"] == x["authoritativeWriter"],
            "data writer " + x["id"],
        )
    packages = d["work"]["packages"]
    pkgids = {p["id"] for p in packages}
    need(len(pkgids) == len(packages), "package IDs")
    need(
        d["work"].get("currentPackage") == cur["currentWorkPackage"]
        and cur["currentWorkPackage"] in pkgids,
        "current work-package projection",
    )
    counts = Counter(p["module"] for p in packages)
    qprofiles = {x["id"] for x in d["qualification"]["profiles"]}
    for p in packages:
        need(
            p["module"] in mids and p["owner"] and p["deputy"],
            "package module " + p["id"],
        )
        need(p["qualificationProfile"] in qprofiles, "package profile " + p["id"])
        need(type(p["sourceMutationAllowed"]) is bool, "package mutation " + p["id"])
        need(
            bool(p["allowedWritePaths"]) == p["sourceMutationAllowed"],
            "package paths " + p["id"],
        )
        need(
            p["deliverables"]
            and p["acceptanceCriteria"]
            and p["resourceBudget"]
            and p["rollback"]
            and p["stopConditions"],
            "package envelope " + p["id"],
        )
        for c in p["consumesContracts"] + p["producesContracts"]:
            need(c in cids, "package contract " + p["id"] + " " + c)
        for f in ("developmentAfter", "activationAfter", "evidenceAfter"):
            for dep in p[f]:
                need(dep in pkgids and dep != p["id"], f + " " + p["id"])
    need(set(counts) == mids, "module package coverage")
    for name, field in [
        ("development", "developmentAfter"),
        ("activation", "activationAfter"),
        ("evidence_dag", "evidenceAfter"),
    ]:
        dag = d[name]
        need(set(dag["nodes"]) == pkgids, name + " nodes")
        expected = {(x, p["id"]) for p in packages for x in p[field]}
        actual = {(x["from"], x["to"]) for x in dag["edges"]}
        need(expected == actual, name + " edges")
        acyclic(dag["nodes"], dag["edges"], name)
    dev = reach(d["development"]["nodes"], d["development"]["edges"])
    act = reach(d["activation"]["nodes"], d["activation"]["edges"])
    lease_summary = validate_path_leases(
        d["paths"], packages, dev, act, pull_request_changed_paths()
    )
    evid = {x["id"] for x in d["evidence"]["evidenceTypes"]}
    for ladder in d["claims"]["ladders"]:
        levels = [x["id"] for x in ladder["levels"]]
        need(ladder["current"] in levels, "claim current " + ladder["id"])
        for level in ladder["levels"]:
            need(
                set(level["requires"]) <= evid,
                "claim evidence " + ladder["id"] + "." + level["id"],
            )
    for q in d["qualification"]["profiles"]:
        need(
            set(q["requires"]) <= evid
            and q["mandatoryTestClasses"]
            and q["independentDecisionRoles"],
            "qualification " + q["id"],
        )
    for x in d["objectives"]["hardConstraints"]:
        need(x["learnable"] is False, "learnable hard constraint " + x["id"])
    for p in d["objectives"]["baselineProfiles"]:
        need(
            abs(sum(float(x["baselineWeight"]) for x in p["dimensions"]) - 1) < 1e-9,
            "weights " + p["id"],
        )
    need(
        d["ndu"]["allowedSubjectClasses"] == ["system", "domain", "agent", "episode"],
        "NDU subject scope",
    )
    need(
        d["prompt"]["security"]["untrustedUpgradeToInstructionAllowed"] is False,
        "prompt trust",
    )
    need(
        d["learning"]["currentRunMutationAllowed"] is False
        and d["learning"]["plasticity"]["topologyOnlineActivationAllowed"] is False,
        "online mutation",
    )
    need(
        d["artifacts"]["loadPolicy"]["currentRunReplacementAllowed"] is False
        and d["artifacts"]["loadPolicy"]["mixedArtifactGenerationAllowed"] is False,
        "artifact load",
    )
    need(
        d["learning"]["longitudinal"]["minimumIndependentSnapshots"] >= 3
        and d["learning"]["longitudinal"]["minimumCalendarWindows"] >= 2,
        "longitudinal minimum",
    )
    need(
        d["algorithm_specs"]["documentationGapState"] == "closed"
        and d["algorithm_specs"]["globalClosure"]["state"] == "closed",
        "adaptive documentation closure",
    )
    need(
        d["algorithm_specs"]["globalClosure"]["workPackageId"] in pkgids,
        "adaptive documentation package",
    )
    need(
        len(d["algorithm_specs"]["requiredProtocols"]) >= 20,
        "adaptive protocol closure",
    )
    for t in d["threats"]["threats"]:
        need(
            t["owner"] in mids and t["prevent"] and t["detect"] and t["respond"],
            "threat " + t["id"],
        )
    sub = subordinate_state()
    need(
        sub["readiness"].get("overlayId") == "HEPTA-V8-PRECODING-READINESS"
        and sub["readiness"].get("globalClosure", {}).get("state") == "closed"
        and len(sub["readiness"]["documents"]) == 9
        and len(sub["readiness_protocols"]["protocols"]) == 31
        and len(sub["readiness_gaps"]["gaps"]) == 54,
        "readiness subordinate closure",
    )
    need(
        sub["cns"].get("claimBoundary", {}).get("repositoryReferenceClosure") is True
        and sub["cns"].get("claimBoundary", {}).get("productionEmbodiment") is False
        and len(sub["cns"]["organs"]) == 24
        and len(sub["cns_gaps"]["gaps"]) == 22,
        "CNS subordinate closure",
    )
    need(
        sub["hnmf"].get("claimPosture", {}).get("productionActivation") is False
        and len(sub["hnmf_gaps"]["gaps"]) == 18,
        "HNMF subordinate closure",
    )
    need((ROOT / "docs/STATUS.md").read_text() == status_text(d), "STATUS stale")
    module_check = subprocess.run(
        [sys.executable, str(ROOT / MODULE_VERIFIER), "verify"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    need(
        module_check.returncode == 0,
        "module docs verifier " + (module_check.stderr or module_check.stdout).strip(),
    )
    algorithm_check = subprocess.run(
        [sys.executable, str(ROOT / ALGORITHM_VERIFIER), "verify"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    need(
        algorithm_check.returncode == 0,
        "algorithm docs verifier "
        + (algorithm_check.stderr or algorithm_check.stdout).strip(),
    )
    for label, verifier in [
        ("readiness", READINESS_VERIFIER),
        ("CNS", CNS_VERIFIER),
        ("HNMF", HNMF_VERIFIER),
    ]:
        check = subprocess.run(
            [sys.executable, str(ROOT / verifier), "verify"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        need(
            check.returncode == 0,
            label + " verifier " + (check.stderr or check.stdout).strip(),
        )
    wf = (ROOT / ".github/workflows/hepta-development-docs.yml").read_text()
    try:
        verify_synthetic_merge(wf, ROOT)
    except ValueError as exc:
        die("synthetic merge workflow: " + str(exc))
    for token in [
        "source-head:",
        "merge-candidate:",
        "github.event.pull_request.head.sha",
        "github.event.pull_request.base.sha",
        "persist-credentials: false",
        "python3 scripts/hepta-docs.py verify",
        "python3 scripts/hepta-algorithm-docs.py verify-sources",
        "python3 scripts/hepta-readiness.py self-test",
        "python3 scripts/hepta-readiness.py generate-status --check",
        "python3 scripts/hepta-cns.py self-test",
        "python3 scripts/hepta-cns.py generate-status --check",
        "python3 scripts/hepta-hnmf.py self-test",
        "python3 scripts/hepta-docs.py inventory-legacy",
        "python3 scripts/hepta-docs.py cleanup-inventory",
        "python3 scripts/hepta-docs.py self-test",
        "python3 scripts/hepta-docs.py receipt-verify",
        "include-hidden-files: true",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        "contents: read",
    ]:
        need(token in wf, "workflow " + token)
    for token in [
        "contents: write",
        "git push",
        "update-ref",
        "pull-requests: write",
        "paths-ignore:",
        "github.event.pull_request.merge_commit_sha",
    ]:
        need(token not in wf, "workflow mutation or stale identity " + token)
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_DEVELOPMENT_DOCS_V8",
                "planVersion": VERSION,
                "modules": len(mods),
                "contracts": len(contracts),
                "protocols": len(protocols),
                "dataDomains": len(domains),
                "workPackages": len(packages),
                "moduleTechnicalDocuments": len(d["module_docs"]["modules"]),
                "sourceBindings": len(d["source_bindings"]["bindings"]),
                "adaptiveSpecifications": len(d["algorithm_specs"]["documents"]),
                "paperSources": len(d["paper_traceability"]["papers"]),
                "readinessSpecifications": len(sub["readiness"]["documents"]),
                "readinessProtocols": len(sub["readiness_protocols"]["protocols"]),
                "readinessDocumentationGaps": len(sub["readiness_gaps"]["gaps"]),
                "cnsOrgans": len(sub["cns"]["organs"]),
                "cnsReferenceGaps": len(sub["cns_gaps"]["gaps"]),
                "hnmfReferenceGaps": len(sub["hnmf_gaps"]["gaps"]),
                "legacyPaths": 0,
                "unresolvedPathConflicts": 0,
                **lease_summary,
            },
            sort_keys=True,
        )
    )
    return 0


def generate():
    d = {k: load(v) for k, v in FILES.items()}
    (ROOT / "docs/STATUS.md").write_text(status_text(d))
    print("WROTE docs/STATUS.md")
    return 0


def inventory():
    s = load(FILES["system"])
    paths = tracked()
    rules = [
        (x["id"], re.compile(x["regex"], re.I)) for x in s["forbiddenLegacyPathRules"]
    ]
    hits = []
    for path in paths:
        if path in s["canonicalPaths"]:
            continue
        for name, rx in rules:
            if rx.search(path):
                hits.append({"path": path, "rule": name})
                break
    print(
        json.dumps(
            {
                "schema": "hepta.legacy-development-inventory.v2",
                "count": len(hits),
                "matches": hits,
            },
            indent=2,
        )
    )
    return 1 if hits else 0


def cleanup_inventory(output):
    system = load(FILES["system"])
    payload = {
        "schema": "hepta.development-docs-cleanup-inventory.v1",
        "planVersion": VERSION,
        "cleanup": verify_cleanup_base(system),
        "authorityGranted": False,
    }
    need(payload["cleanup"]["evaluated"], "cleanup inventory requires Git worktree")
    target = Path(output)
    if not target.is_absolute():
        target = ROOT / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


def receipt(kind, expected_sha, output):
    need(kind in {"source-head", "merge-candidate"}, "receipt kind")
    actual = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    need(not expected_sha or actual == expected_sha, "receipt expected SHA")
    ctx = event_context()
    pr = ctx["pr"]
    base = ctx["base"]
    source = ctx["source"]
    event_merge = ctx["eventMerge"]
    number = ctx["number"]
    parents = git("rev-list", "--parents", "-n", "1", "HEAD").split()[1:]
    if pr:
        need(base and source and number, "pull-request event identity")
        if kind == "source-head":
            need(actual == source, "source receipt head")
        else:
            need(actual == expected_sha, "merge receipt expected head")
            need(
                len(parents) == 2 and parents[0] == base and parents[1] == source,
                "merge receipt ordered parents",
            )
    elif kind == "merge-candidate":
        die("merge receipt requires pull-request event")
    base_tree = git("rev-parse", base + "^{tree}") if base else None
    source_tree = git("rev-parse", source + "^{tree}") if source else tree
    merge_candidate = actual if kind == "merge-candidate" else None
    merge_tree = tree if kind == "merge-candidate" else None
    cleanup = verify_cleanup_base(load(FILES["system"]))
    need(cleanup["evaluated"], "receipt cleanup inventory")
    now = datetime.now(timezone.utc)
    policy = load(FILES["current"])["dynamicObservationPolicy"]
    verified_at = normalized_utc(now)
    time_evidence = validate_observation(verified_at, policy, now)
    payload = {
        "schema": RECEIPT_SCHEMA,
        "planVersion": VERSION,
        "kind": kind,
        "repository": REPO,
        "pullRequest": number,
        "baseCommit": base,
        "baseTree": base_tree,
        "sourceHead": source or actual,
        "sourceTree": source_tree,
        "mergeCandidate": merge_candidate,
        "mergeTree": merge_tree,
        "eventMergeCandidate": event_merge,
        "eventMergeCandidateTrusted": False,
        "commit": actual,
        "tree": tree,
        "parents": parents,
        "expectedCommit": expected_sha,
        "workflowPath": ".github/workflows/hepta-development-docs.yml",
        "workflowSha256": hashlib.sha256(
            (ROOT / ".github/workflows/hepta-development-docs.yml").read_bytes()
        ).hexdigest(),
        "verifierSha256": hashlib.sha256(
            (ROOT / "scripts/hepta-docs.py").read_bytes()
        ).hexdigest(),
        "moduleVerifierSha256": hashlib.sha256(
            (ROOT / MODULE_VERIFIER).read_bytes()
        ).hexdigest(),
        "algorithmVerifierSha256": hashlib.sha256(
            (ROOT / ALGORITHM_VERIFIER).read_bytes()
        ).hexdigest(),
        "algorithmRegistrySha256": hashlib.sha256(
            (ROOT / FILES["algorithm_specs"]).read_bytes()
        ).hexdigest(),
        "readinessVerifierSha256": hashlib.sha256(
            (ROOT / READINESS_VERIFIER).read_bytes()
        ).hexdigest(),
        "readinessRegistrySha256": hashlib.sha256(
            (ROOT / READINESS_INDEX).read_bytes()
        ).hexdigest(),
        "cnsVerifierSha256": hashlib.sha256(
            (ROOT / CNS_VERIFIER).read_bytes()
        ).hexdigest(),
        "cnsArchitectureSha256": hashlib.sha256(
            (ROOT / CNS_ARCHITECTURE).read_bytes()
        ).hexdigest(),
        "hnmfVerifierSha256": hashlib.sha256(
            (ROOT / HNMF_VERIFIER).read_bytes()
        ).hexdigest(),
        "hnmfRegistrySha256": hashlib.sha256(
            (ROOT / HNMF_REGISTRY).read_bytes()
        ).hexdigest(),
        "verifiedAt": verified_at,
        "timeEvidence": time_evidence,
        "maximumClockSkewSeconds": policy["maximumClockSkewSeconds"],
        "dynamicReceiptTtlSeconds": policy["dynamicReceiptTtlSeconds"],
        "cleanup": cleanup,
        "authorityGranted": False,
    }
    target = Path(output)
    if not target.is_absolute():
        target = ROOT / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


def receipt_verify(input_path, kind, expected_sha):
    need(kind in {"source-head", "merge-candidate"}, "receipt verification kind")
    need(bool(expected_sha), "receipt verification expected SHA")
    payload = load_path(input_path)
    actual = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    parents = git("rev-list", "--parents", "-n", "1", "HEAD").split()[1:]
    need(actual == expected_sha, "receipt verification checkout SHA")
    need(payload.get("schema") == RECEIPT_SCHEMA, "receipt schema")
    need(
        payload.get("planVersion") == VERSION and payload.get("kind") == kind,
        "receipt plan/kind",
    )
    need(
        payload.get("repository") == REPO and payload.get("authorityGranted") is False,
        "receipt authority",
    )
    need(
        payload.get("expectedCommit") == expected_sha
        and payload.get("commit") == actual,
        "receipt commit",
    )
    need(
        payload.get("tree") == tree and payload.get("parents") == parents,
        "receipt tree/parents",
    )
    need(
        payload.get("workflowPath") == ".github/workflows/hepta-development-docs.yml",
        "receipt workflow path",
    )
    need(
        payload.get("workflowSha256")
        == hashlib.sha256(
            (ROOT / ".github/workflows/hepta-development-docs.yml").read_bytes()
        ).hexdigest(),
        "receipt workflow digest",
    )
    need(
        payload.get("verifierSha256")
        == hashlib.sha256((ROOT / "scripts/hepta-docs.py").read_bytes()).hexdigest(),
        "receipt verifier digest",
    )
    need(
        payload.get("moduleVerifierSha256")
        == hashlib.sha256((ROOT / MODULE_VERIFIER).read_bytes()).hexdigest(),
        "receipt module verifier digest",
    )
    need(
        payload.get("algorithmVerifierSha256")
        == hashlib.sha256((ROOT / ALGORITHM_VERIFIER).read_bytes()).hexdigest(),
        "receipt algorithm verifier digest",
    )
    need(
        payload.get("algorithmRegistrySha256")
        == hashlib.sha256((ROOT / FILES["algorithm_specs"]).read_bytes()).hexdigest(),
        "receipt algorithm registry digest",
    )
    for field, rel, label in [
        ("readinessVerifierSha256", READINESS_VERIFIER, "readiness verifier"),
        ("readinessRegistrySha256", READINESS_INDEX, "readiness registry"),
        ("cnsVerifierSha256", CNS_VERIFIER, "CNS verifier"),
        ("cnsArchitectureSha256", CNS_ARCHITECTURE, "CNS architecture"),
        ("hnmfVerifierSha256", HNMF_VERIFIER, "HNMF verifier"),
        ("hnmfRegistrySha256", HNMF_REGISTRY, "HNMF registry"),
    ]:
        need(
            payload.get(field) == hashlib.sha256((ROOT / rel).read_bytes()).hexdigest(),
            "receipt " + label + " digest",
        )
    policy = load(FILES["current"])["dynamicObservationPolicy"]
    fresh = validate_observation(payload.get("verifiedAt"), policy)
    stored = payload.get("timeEvidence")
    need(
        isinstance(stored, dict)
        and stored.get("status") == "PASS_HEPTA_DYNAMIC_TIME_EVIDENCE",
        "receipt time evidence status",
    )
    for key in (
        "observedAt",
        "maximumClockSkewSeconds",
        "ttlSeconds",
        "futureTimestampAllowed",
    ):
        need(stored.get(key) == fresh.get(key), "receipt time evidence " + key)
    need(
        payload.get("maximumClockSkewSeconds") == policy["maximumClockSkewSeconds"],
        "receipt clock skew policy",
    )
    need(
        payload.get("dynamicReceiptTtlSeconds") == policy["dynamicReceiptTtlSeconds"],
        "receipt TTL policy",
    )
    need(
        payload.get("eventMergeCandidateTrusted") is False,
        "event merge candidate trust",
    )
    ctx = event_context()
    pr = ctx["pr"]
    base = ctx["base"]
    source = ctx["source"]
    number = ctx["number"]
    if pr:
        need(payload.get("pullRequest") == number, "receipt PR number")
        need(
            payload.get("baseCommit") == base and payload.get("sourceHead") == source,
            "receipt base/source",
        )
        need(
            payload.get("baseTree") == git("rev-parse", base + "^{tree}"),
            "receipt base tree",
        )
        need(
            payload.get("sourceTree") == git("rev-parse", source + "^{tree}"),
            "receipt source tree",
        )
        if kind == "source-head":
            need(actual == source, "verified source identity")
            need(
                payload.get("mergeCandidate") is None
                and payload.get("mergeTree") is None,
                "source merge identity",
            )
        else:
            need(parents == [base, source], "verified merge ordered parents")
            need(
                payload.get("mergeCandidate") == actual
                and payload.get("mergeTree") == tree,
                "verified merge identity",
            )
    else:
        need(
            kind == "source-head" and payload.get("sourceHead") == actual,
            "push source identity",
        )
    cleanup = verify_cleanup_base(load(FILES["system"]))
    need(
        payload.get("cleanup", {}).get("inventorySha256")
        == cleanup.get("inventorySha256"),
        "receipt cleanup inventory",
    )
    need(
        payload.get("cleanup", {}).get("observedDeletionCount")
        == cleanup.get("observedDeletionCount"),
        "receipt cleanup count",
    )
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_EXECUTION_RECEIPT_V5",
                "kind": kind,
                "commit": actual,
                "tree": tree,
                "verifiedAt": fresh["checkedAt"],
                "authorityGranted": False,
            },
            sort_keys=True,
        )
    )
    return 0


def self_test():
    cases = []
    try:
        json.loads('{"a":1,"a":2}', object_pairs_hook=pairs)
        raise AssertionError
    except DuplicateKey:
        cases.append("duplicate_key")
    try:
        acyclic(
            ["a", "b"], [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}], "fixture"
        )
        raise AssertionError
    except SystemExit:
        cases.append("cycle")
    need(overlaps("a/**", "a/b") and not overlaps("a/b", "a2/b"), "overlap fixture")
    cases.append("overlap")

    fixture_path = ".github/workflows/shared.yml"
    fixture_review = {
        "identitySource": "github_pull_request_review",
        "repositorySource": "github.event.repository.id",
        "pullRequestSource": "github.event.pull_request.number",
        "baseSource": "github.event.pull_request.base.sha",
        "headSource": "github.event.pull_request.head.sha",
        "reviewCommitSource": "github.event.review.commit_id",
        "reviewerIdSource": "github.event.review.user.id",
        "authorIdSource": "github.event.pull_request.user.id",
        "requiredState": "approved",
        "reviewCommitMustEqualHead": True,
        "reviewerMustDifferFromAuthor": True,
        "invalidateOnHeadChange": True,
        "reusable": False,
        "maximumAttestationAgeSeconds": 86400,
    }
    fixture_lease = {
        "leaseId": "LEASE-MATRIX-TASKFLOW-001",
        "packageA": "MATRIX-1",
        "packageB": "TASKFLOW-1",
        "normalizedExactPaths": [fixture_path],
        "pathSetSha256": lease_path_set_sha([fixture_path]),
        "purpose": "shared_qualification",
        "status": "requires_external_attestation",
        "reviewBinding": fixture_review,
        "lifecycle": LEASE_LIFECYCLE,
        "authorityGranted": False,
        "authorityDelta": "none",
    }
    fixture_registry = {
        "schema": "hepta.path-ownership.v3",
        "schemaVersion": 3,
        "rules": {
            "onePrimaryOwnerPerPath": True,
            "foreignNamespaceRequiresCoOwner": True,
            "overlapRequiresDagOrderingOrLease": True,
            "unboundedRepositoryScopeAllowed": False,
        },
        "activeLeases": [fixture_lease],
    }
    fixture_packages = [
        {"id": "MATRIX-1", "allowedWritePaths": [fixture_path]},
        {"id": "TASKFLOW-1", "allowedWritePaths": [fixture_path]},
    ]
    fixture_reach = {"MATRIX-1": set(), "TASKFLOW-1": set()}
    need(
        validate_path_leases(
            fixture_registry,
            fixture_packages,
            fixture_reach,
            fixture_reach,
        )
        == {
            "declaredLeaseCount": 1,
            "leasedPathCount": 1,
            "touchedLeaseCount": 0,
            "externallyAttestedLeaseCount": 0,
        },
        "valid static exact path lease request",
    )
    cases.append("static_exact_path_lease_request")

    def cloned(value):
        return json.loads(json.dumps(value))

    def rejects(name, expected, registry, packages=None, changed_paths=None):
        try:
            validate_path_leases(
                registry,
                packages or fixture_packages,
                fixture_reach,
                fixture_reach,
                changed_paths,
            )
            die(name + " accepted")
        except SystemExit as exc:
            if expected not in str(exc):
                raise
        cases.append(name)

    registry = cloned(fixture_registry)
    registry["activeLeases"] = []
    rejects("reject_missing_lease", "missing or unused path lease", registry)

    packages = [
        {
            "id": "MATRIX-1",
            "allowedWritePaths": [".github/workflows/hepta-intelligence-*.yml"],
        },
        {
            "id": "TASKFLOW-1",
            "allowedWritePaths": [
                ".github/workflows/hepta-intelligence-qualification.yml"
            ],
        },
    ]
    registry = cloned(fixture_registry)
    registry["activeLeases"] = []
    rejects(
        "reject_unleased_internal_glob_match",
        "missing or unused path lease",
        registry,
        packages,
    )

    rejects(
        "reject_no_review_exact_touch",
        "external path lease attestation required",
        fixture_registry,
        fixture_packages,
        {fixture_path},
    )

    packages = cloned(fixture_packages)
    second_path = ".github/workflows/second.yml"
    for package in packages:
        package["allowedWritePaths"].append(second_path)
    rejects(
        "reject_second_unlisted_overlap",
        "lease path mismatch",
        fixture_registry,
        packages,
    )

    registry = cloned(fixture_registry)
    paths = registry["activeLeases"][0]["normalizedExactPaths"]
    paths.append(second_path)
    paths.sort()
    registry["activeLeases"][0]["pathSetSha256"] = lease_path_set_sha(paths)
    rejects("reject_unused_extra_path", "lease path mismatch", registry)

    registry = cloned(fixture_registry)
    paths = registry["activeLeases"][0]["normalizedExactPaths"]
    paths[0] = ".github/workflows/**"
    registry["activeLeases"][0]["pathSetSha256"] = lease_path_set_sha(paths)
    rejects(
        "reject_wildcard_lease",
        "canonical exact POSIX path",
        registry,
    )

    packages = [
        {"id": "MATRIX-1", "allowedWritePaths": ["shared"]},
        {"id": "TASKFLOW-1", "allowedWritePaths": ["shared/workflow.yml"]},
    ]
    rejects(
        "reject_prefix_widening",
        "prefix widening cannot be leased",
        fixture_registry,
        packages,
    )

    registry = cloned(fixture_registry)
    lease = registry["activeLeases"][0]
    lease["packageA"], lease["packageB"] = lease["packageB"], lease["packageA"]
    rejects("reject_reversed_pair", "canonical package pair", registry)

    for name, path in [
        ("reject_path_alias", ".github//workflows/shared.yml"),
        ("reject_path_escape", "../shared.yml"),
    ]:
        registry = cloned(fixture_registry)
        registry["activeLeases"][0]["normalizedExactPaths"] = [path]
        registry["activeLeases"][0]["pathSetSha256"] = lease_path_set_sha([path])
        rejects(
            name,
            "canonical exact POSIX path" if "//" in path else "path alias or escape",
            registry,
        )

    registry = cloned(fixture_registry)
    registry["activeLeases"][0]["pathSetSha256"] = "0" * 64
    rejects("reject_path_digest_mismatch", "path-set digest", registry)

    registry = cloned(fixture_registry)
    registry["activeLeases"][0]["reviewBinding"]["invalidateOnHeadChange"] = False
    rejects("reject_stale_head_policy", "exact-head external review policy", registry)

    registry = cloned(fixture_registry)
    registry["activeLeases"][0]["reviewBinding"]["reviewerMustDifferFromAuthor"] = False
    rejects(
        "reject_non_independent_review_policy",
        "exact-head external review policy",
        registry,
    )

    registry = cloned(fixture_registry)
    registry["activeLeases"][0]["authorityGranted"] = True
    rejects("reject_positive_lease_authority", "authority posture", registry)

    two_paths = sorted([fixture_path, second_path])
    packages = [
        {"id": "MATRIX-1", "allowedWritePaths": two_paths},
        {"id": "TASKFLOW-1", "allowedWritePaths": two_paths},
    ]
    registry = cloned(fixture_registry)
    registry["activeLeases"][0]["normalizedExactPaths"] = two_paths
    registry["activeLeases"][0]["pathSetSha256"] = lease_path_set_sha(two_paths)
    rejects(
        "reject_partial_changed_lease_set",
        "changed leased path set must equal manifest",
        registry,
        packages,
        {fixture_path},
    )

    rejects(
        "reject_changed_path_prefix_alias",
        "changed path prefix aliases a lease",
        fixture_registry,
        fixture_packages,
        {".github/workflows"},
    )

    need(shape_sha({"a": 1}) != shape_sha({"a": "1"}), "shape fixture")
    cases.append("shape")
    need(
        list({k: False for k in AUTHORITY_KEYS}) == AUTHORITY_KEYS, "authority fixture"
    )
    cases.append("authority")
    fixture_name = "hepta-cleanup-fixture-7c3d.json"
    basename_pattern = deleted_json_basename_pattern("legacy/" + fixture_name)
    need(basename_pattern.search('"' + fixture_name + '"'), "deleted JSON reference")
    for text in ["bazel_" + fixture_name, fixture_name + ".backup"]:
        need(not basename_pattern.search(text), "deleted JSON basename boundary")
    cases.append("deleted_json_basename_boundary")
    fixed = datetime(2026, 9, 1, tzinfo=timezone.utc)
    policy = {
        "futureTimestampAllowed": False,
        "maximumClockSkewSeconds": 300,
        "dynamicReceiptTtlSeconds": 86400,
    }
    validate_observation(normalized_utc(fixed + timedelta(seconds=300)), policy, fixed)
    cases.append("bounded_future_time")
    for name, observed in [
        ("reject_future_time", fixed + timedelta(seconds=301)),
        ("reject_stale_time", fixed - timedelta(seconds=86401)),
    ]:
        try:
            validate_observation(normalized_utc(observed), policy, fixed)
            raise AssertionError
        except SystemExit:
            cases.append(name)
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_DEVELOPMENT_DOCS_V8_SELF_TEST",
                "cases": cases,
                "authorityGranted": False,
            },
            sort_keys=True,
        )
    )
    return 0


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name in ["verify", "generate-status", "inventory-legacy", "self-test"]:
        sp.add_parser(name)
    cp = sp.add_parser("cleanup-inventory")
    cp.add_argument("--output", required=True)
    rp = sp.add_parser("receipt")
    rp.add_argument("--kind", required=True)
    rp.add_argument("--expected-sha", default="")
    rp.add_argument("--output", required=True)
    vp = sp.add_parser("receipt-verify")
    vp.add_argument("--input", required=True)
    vp.add_argument("--kind", required=True)
    vp.add_argument("--expected-sha", required=True)
    args = ap.parse_args()
    if args.cmd == "verify":
        return verify()
    if args.cmd == "generate-status":
        return generate()
    if args.cmd == "inventory-legacy":
        return inventory()
    if args.cmd == "self-test":
        return self_test()
    if args.cmd == "cleanup-inventory":
        return cleanup_inventory(args.output)
    if args.cmd == "receipt":
        return receipt(args.kind, args.expected_sha, args.output)
    return receipt_verify(args.input, args.kind, args.expected_sha)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(1)
