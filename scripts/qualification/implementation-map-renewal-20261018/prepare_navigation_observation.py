#!/usr/bin/env python3
"""Prepare new navigation observations outside a clean, fully fetched repository.

This tool never writes the repository, changes the original checker, runs native
code, migrates valid maps, fabricates ancestry, or renews execution receipts.
Review the output, then let the repository owner apply and commit it separately.
"""

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True

NONANCESTOR_ANCHORS = {
    "e8e81b7d541a81e75635cc1c0a713edaedb999d5",
    "8914a46dfc5984532f03dd2d559bf547ca4f1e69",
}
EXPECTED_MODULES = {
    "automation.taskflow",
    "cognitive.read",
    "control.engineering",
    "control.runtime",
    "inference.control",
    "intelligence.control",
    "kernel.operations",
    "knowledge.graph",
    "learning.artifacts",
    "learning.ledger",
    "learning.operator",
    "learning.plasticity",
    "memory.federation",
    "memory.retrieval",
    "objective.compiler",
    "platform.types",
    "runtime.codex",
    "runtime.supervisor",
    "utility.ndu",
}
# These name prior source observations. Preserve their original values inside
# the exact archived map, rather than presenting them as current candidate data.
HISTORICAL_METADATA = {
    "sourceBaseRole",
    "sourceBaseSemantics",
    "observedImplementationBase",
    "currentSourceEvidence",
    "headAttestation",
    "exactSourceCandidate",
    "productCompositionSourceCandidate",
    "exactHeadQualificationPolicy",
}


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def literal_sha(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError("exact literal SHA-1 required")
    return value


def read_git_blob(repo, blob):
    # Match the owner's no-replacements/no-lazy-fetch Git boundary, but return
    # bytes without str.strip(): the archive must retain the exact original blob.
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
    )
    return subprocess.run(
        [
            "git",
            "--literal-pathspecs",
            "-c",
            "core.fsmonitor=false",
            "cat-file",
            "blob",
            literal_sha(blob),
        ],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
    ).stdout


def load_owner(repo):
    sys.path.insert(0, str(repo / "scripts"))
    path = repo / "scripts/hepta-implementation-maps.py"
    spec = importlib.util.spec_from_file_location("original_implementation_maps", path)
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    if owner.ROOT.resolve() != repo:
        raise ValueError("original checker root mismatch")
    return owner


def original_nonancestor_failure(owner, row, candidate):
    """Retain an actual original-checker failure, never a missing-object proxy."""
    try:
        owner.checked_identity(row["sourceBase"], candidate)
    except subprocess.CalledProcessError as error:
        args = list(error.cmd)
        expected = [
            "merge-base",
            "--is-ancestor",
            row["sourceBase"]["commit"],
            candidate["commit"],
        ]
        if error.returncode != 1 or args[-4:] != expected:
            raise ValueError(
                "anchor unavailable/malformed; not a demonstrated nonancestor"
            ) from error
        return {
            "scope": "original checked_identity sourceBase ancestry check",
            "sourceBase": row["sourceBase"],
            "candidate": candidate,
            "command": args,
            "returncode": error.returncode,
            "stdout": error.stdout,
            "stderr": error.stderr,
            "fullRepositoryMapVerification": False,
        }
    raise ValueError("anchor is now a valid ancestor; use the original migrate command")


def fresh_navigation(owner, row, module, lanes, candidate, retained):
    if row.get("module", module["id"]) != module["id"]:
        raise ValueError("original map module identity mismatch")
    if owner.validate_claim_types(row):
        raise ValueError(
            "unexpected positive execution claim; manual evidence review required"
        )
    fresh = copy.deepcopy(row)
    historical_keys = sorted(HISTORICAL_METADATA.intersection(fresh))
    for key in historical_keys:
        fresh.pop(key)
    claim_changes = []
    boundary = fresh["claimBoundary"]
    specialized = boundary.get("requestLocalReadOnlyProductExecutionProved", False)
    if type(specialized) is not bool:
        raise ValueError("invalid specialized read-only execution claim")
    if specialized:
        if module["id"] != "utility.ndu":
            raise ValueError("unexpected specialized execution claim")
        boundary["requestLocalReadOnlyProductExecutionProved"] = False
        claim_changes.append(
            {
                "path": "claimBoundary.requestLocalReadOnlyProductExecutionProved",
                "oldDeclaration": True,
                "newDeclaration": False,
                "reason": "new source navigation executes no product; old declaration remains in exact archived map",
            }
        )
    # Explicit current navigation uses the stronger policy already accepted by
    # the unchanged checker. Exact-blob mode remains exact-blob mode.
    fresh["sourceIdentityPolicy"] = "candidate_or_exact_observation_v1"
    fresh = owner.migrate_map(fresh, module, lanes, candidate)
    fresh["sourceNavigationObservation"] = {
        "schema": "hepta.source-navigation-observation.v1",
        "kind": "fresh_navigation_after_nonancestor_source_observation",
        "scope": "source paths, exact Git objects and source call-composition navigation only",
        "candidate": candidate,
        "priorObservation": retained,
        "historicalMetadataRetainedInOriginalBlob": historical_keys,
        "claimChanges": claim_changes,
        "nativeExecutionPerformed": False,
        "historicalExecutionReceiptsRebound": False,
        "independentAcceptance": False,
        "activation": False,
        "release": False,
    }
    if owner.validate_claim_types(fresh):
        raise ValueError("fresh renderer introduced a positive execution claim")
    owner.validate_closed_world_bindings(fresh)
    owner.validate_operation_inventory(module["id"], fresh["operations"])
    roots = owner.resolve_source_roots(owner.ROOT, module)
    paths = owner.verify_source_identity(fresh, roots, candidate)
    if fresh.get("sourceObjects") is not None and fresh[
        "sourceObjects"
    ] != owner.current_source_objects(fresh):
        raise ValueError("fresh source object inventory mismatch")
    if fresh.get("exactSourceEvidence", {}).get("kind") == "path_blob_manifest_v1":
        failures = []
        owner.validate_path_blob_manifest(fresh, module["id"], failures)
        if failures:
            raise ValueError("; ".join(failures))
    return fresh, paths


def prepare(repo, expected_head, output, retained_prefix):
    repo, output = repo.resolve(), output.resolve()
    if output == repo or repo in output.parents:
        raise ValueError("output must be outside the repository")
    if output.exists():
        raise ValueError(
            "output must be a new path; retained failures must not be overwritten"
        )
    prefix = Path(retained_prefix)
    if (
        prefix.is_absolute()
        or ".." in prefix.parts
        or not prefix.parts
        or prefix.parts[0] != "qualification"
    ):
        raise ValueError("retained prefix must be a new qualification/ relative path")
    if (repo / prefix).exists():
        raise ValueError("retained destination already exists")
    owner = load_owner(repo)
    candidate = owner.current_source_base()
    if candidate["commit"] != literal_sha(expected_head):
        raise ValueError("candidate changed; prepare from the final clean code commit")
    owner.require_clean_candidate(candidate)
    if owner.git("rev-parse", "--is-shallow-repository") != "false":
        raise ValueError(
            "full Git history required; shallow not-found is not nonancestry evidence"
        )
    modules = owner.load("docs/modules/MODULES.json")["modules"]
    by_id = {module["id"]: module for module in modules}
    if len(by_id) != len(modules):
        raise ValueError("duplicate module registry entry")
    rows = {
        mid: owner.load(f"docs/modules/{mid}/IMPLEMENTATION_MAP.json") for mid in by_id
    }
    selected = {
        mid
        for mid, row in rows.items()
        if row["sourceBase"]["commit"] in NONANCESTOR_ANCHORS
    }
    if selected != EXPECTED_MODULES:
        raise ValueError(
            "19-map repair scope changed; inspect the actual new source first"
        )
    valid_modules = sorted(set(by_id) - selected)
    for mid in valid_modules:
        owner.checked_identity(rows[mid]["sourceBase"], candidate)
    lanes = owner.lane_by_module()
    payloads, details, checked_paths = {}, [], set()
    for mid in sorted(selected):
        relative = f"docs/modules/{mid}/IMPLEMENTATION_MAP.json"
        blob = owner.git("rev-parse", f"HEAD:{relative}")
        raw = read_git_blob(repo, blob)
        if raw != (repo / relative).read_bytes():
            raise ValueError(f"{mid}: worktree differs from exact stored map bytes")
        if (
            hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            != blob
        ):
            raise ValueError("original Git blob identity mismatch")
        failure = original_nonancestor_failure(owner, rows[mid], candidate)
        old_path = (prefix / "original-maps" / f"{mid}.json").as_posix()
        failure_path = (prefix / "original-failures" / f"{mid}.json").as_posix()
        failure_raw = encoded(failure)
        retained = {
            "mapPath": relative,
            "archivedBlobPath": old_path,
            "gitBlob": blob,
            "sha256": sha256(raw),
            "sourceBase": rows[mid]["sourceBase"],
            "strictAnchorFailurePath": failure_path,
            "strictAnchorFailureSha256": sha256(failure_raw),
        }
        fresh, paths = fresh_navigation(
            owner, rows[mid], by_id[mid], lanes, candidate, retained
        )
        checked_paths.update(paths)
        new_raw = encoded(fresh)
        payloads.update({relative: new_raw, old_path: raw, failure_path: failure_raw})
        details.append(
            {
                "module": mid,
                "retained": retained,
                "newMapSha256": sha256(new_raw),
                "sourcePaths": paths,
                "claimChanges": fresh["sourceNavigationObservation"]["claimChanges"],
            }
        )
    owner.require_clean_candidate(candidate, sorted(checked_paths))
    report = {
        "schema": "hepta.source-navigation-renewal-preparation.v1",
        "status": "PREPARED",
        "candidate": candidate,
        "originalCheckerGitBlob": owner.git(
            "rev-parse", "HEAD:scripts/hepta-implementation-maps.py"
        ),
        "modules": details,
        "unchangedValidAncestorModules": valid_modules,
        "originalMigrateCommandForValidAncestors": [
            "python3",
            "scripts/hepta-implementation-maps.py",
            "migrate",
            *[arg for mid in valid_modules for arg in ("--module", mid)],
        ],
        "repositoryWritten": False,
        "nativeExecutionPerformed": False,
        "historicalExecutionReceiptsRebound": False,
        "fullMapVerificationRequiredAfterOwnerCommit": True,
    }
    payloads[(prefix / "OBSERVATION.json").as_posix()] = encoded(report)
    output.mkdir(parents=True)
    for relative, raw in payloads.items():
        target = output / "payload" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw)
    (output / "PAYLOAD_SHA256.json").write_bytes(
        encoded({p: sha256(raw) for p, raw in sorted(payloads.items())})
    )
    print(
        json.dumps(
            {
                "status": "PREPARED",
                "candidate": candidate,
                "newMaps": len(details),
                "preservedOriginalBlobs": len(details),
                "output": str(output),
                "repositoryWritten": False,
                "nativeExecutionPerformed": False,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--retained-prefix", default="qualification/implementation-map-renewal-20261018"
    )
    args = parser.parse_args()
    prepare(args.repo, args.expected_head, args.out, args.retained_prefix)
