#!/usr/bin/env python3
"""Revalidate all six downloaded native bundles before creating an aggregate.

These are exact-source CI observations, NOT signatures or release authority.
Run inside the same Actions run/attempt as the producers. Never mix retries.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import hepta_ui_native_evidence as evidence
import hepta_ui_native_product_evidence as product_evidence

DIGEST = re.compile(r"[0-9a-f]{64}\Z")
NON_PROMOTING = (
    "physicalHostAcceptance",
    "accessibilityAcceptance",
    "productionSigningObserved",
    "releaseAuthorized",
)


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError(f"missing, unsafe or oversized evidence: {path}")
    value = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=unique_object
    )
    if not isinstance(value, dict):
        raise ValueError("evidence must be an object")
    return value


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def deterministic_subjects(
    root: Path, candidate: str, base: str
) -> dict[str, dict[str, str]]:
    for value in (candidate, base):
        if not evidence.SHA.fullmatch(value) or value == "0" * 40:
            raise ValueError("candidate/base must be complete nonzero commit IDs")
    tree = evidence.git(root, "merge-tree", "--write-tree", base, candidate)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "native-qualification",
        "GIT_AUTHOR_EMAIL": "native-qualification@users.noreply.github.com",
        "GIT_COMMITTER_NAME": "native-qualification",
        "GIT_COMMITTER_EMAIL": "native-qualification@users.noreply.github.com",
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
    }
    merge = (
        subprocess.check_output(
            ["git", "commit-tree", tree, "-p", base, "-p", candidate],
            cwd=root,
            # Text-mode pipes convert LF to CRLF on Windows and change the commit ID.
            input=b"deterministic ui.native qualification merge\n",
            env=env,
        )
        .decode("ascii")
        .strip()
    )
    return {
        "head": {
            "sourceSha": candidate,
            "sourceTreeSha": evidence.git(root, "rev-parse", f"{candidate}^{{tree}}"),
        },
        "merge": {"sourceSha": merge, "sourceTreeSha": tree},
    }


def aggregate(
    bundles: Path,
    *,
    candidate: str,
    base: str,
    workflow_sha: str,
    workflow_digest: str,
    run_id: str,
    attempt: str,
    subjects: dict[str, dict[str, str]],
    implementation: str | None = None,
) -> dict:
    for value in (candidate, base, workflow_sha):
        if not evidence.SHA.fullmatch(value) or value == "0" * 40:
            raise ValueError("invalid exact-source identity")
    if not DIGEST.fullmatch(workflow_digest):
        raise ValueError("missing workflow digest")
    if implementation is not None and (
        not evidence.SHA.fullmatch(implementation) or implementation == "0" * 40
    ):
        raise ValueError("invalid frozen implementation identity")
    if (
        not run_id.isdigit()
        or int(run_id) <= 0
        or not attempt.isdigit()
        or int(attempt) <= 0
    ):
        raise ValueError("real run ID and attempt required")
    if set(subjects) != {"head", "merge"} or subjects["head"]["sourceSha"] != candidate:
        raise ValueError("invalid expected subjects")
    matrix = evidence.qualification_matrix()["include"]
    names = {
        f"ui-native-qualification-{profile['runner']}-{profile['kind']}-{candidate}-attempt-{attempt}"
        for profile in matrix
    }
    if (
        not bundles.is_dir()
        or bundles.is_symlink()
        or {path.name for path in bundles.iterdir()} != names
    ):
        raise ValueError("exactly six expected same-candidate bundles are required")
    summaries, consistency = [], {}
    for profile in matrix:
        name = (
            f"ui-native-qualification-{profile['runner']}-{profile['kind']}-"
            f"{candidate}-attempt-{attempt}"
        )
        bundle = bundles / name
        if not bundle.is_dir() or any(
            path.is_symlink() for path in [bundle, *bundle.rglob("*")]
        ):
            raise ValueError("bundle contains a non-directory root or symlink")
        receipt_path = bundle / "native-evidence/qualification.json"
        receipt = read_json(receipt_path)
        expected = {
            **subjects[profile["kind"]],
            "candidateSha": candidate,
            "baseSha": base,
            "sourceKind": profile["kind"],
            "workflowSha": workflow_sha,
            "workflowFileSha256": workflow_digest,
            "runId": run_id,
            "runAttempt": attempt,
        }
        if receipt.get("schema") != evidence.SCHEMA or any(
            receipt.get(key) != value for key, value in expected.items()
        ):
            raise ValueError(
                f"{name}: foreign/missing subject, workflow or run identity"
            )
        if (
            receipt.get("qualificationPassed") is not True
            or receipt.get("scope") != "repository-controlled-candidate"
            or any(receipt.get(key) is not False for key in NON_PROMOTING)
        ):
            raise ValueError(f"{name}: failed qualification or unsupported promotion")
        platform = receipt.get("platform", {})
        if platform.get("os") != profile["os"] or any(
            not isinstance(platform.get(key), str) or not platform[key]
            for key in ("ImageOS", "ImageVersion", "RUNNER_ARCH")
        ):
            raise ValueError(f"{name}: missing or foreign platform/image")
        checks = receipt.get("checks", [])
        check_root = bundle / "native-evidence/checks"
        evidence.validate_checks(
            checks,
            check_root,
            {
                **subjects[profile["kind"]],
                "runId": run_id,
                "runAttempt": attempt,
            },
            profile["os"],
        )
        for check in checks:
            if read_json(check_root / f"{check['label']}.json") != check:
                raise ValueError(f"{name}: embedded and retained checks differ")
        package_root = bundle / "native-package"
        artifacts = receipt.get("artifacts", [])
        seen = set()
        if not isinstance(artifacts, list) or not artifacts:
            raise ValueError(f"{name}: missing package artifacts")
        for artifact in artifacts:
            item = artifact.get("name", "")
            if (
                not re.fullmatch(r"[A-Za-z0-9._-]+\.zip", item)
                or item in seen
                or not DIGEST.fullmatch(artifact.get("sha256", ""))
            ):
                raise ValueError(f"{name}: unsafe or duplicate package identity")
            seen.add(item)
            path = package_root / item
            if (
                not path.is_file()
                or type(artifact.get("bytes")) is not int
                or path.stat().st_size != artifact["bytes"]
                or file_digest(path) != artifact["sha256"]
            ):
                raise ValueError(f"{name}: missing or modified package")
        if {path.name for path in package_root.glob("*.zip")} != seen:
            raise ValueError(f"{name}: unbound package artifact")
        signature = {
            key: receipt.get(key)
            for key in (
                "sourceInventorySha256",
                "testManifestSha256",
                "dependencyLocks",
            )
        }
        if any(
            not isinstance(signature[key], str) or not DIGEST.fullmatch(signature[key])
            for key in ("sourceInventorySha256", "testManifestSha256")
        ):
            raise ValueError("missing inventory/test identity")
        locks = signature["dependencyLocks"]
        if (
            not isinstance(locks, dict)
            or set(locks) != {"apps/hepta-native/Cargo.lock", "codex-rs/Cargo.lock"}
            or any(
                not isinstance(value, str) or not DIGEST.fullmatch(value)
                for value in locks.values()
            )
        ):
            raise ValueError("missing dependency-lock identity")
        previous = consistency.setdefault(profile["kind"], signature)
        if previous != signature:
            raise ValueError(
                "same-subject inventories or dependency locks differ between platforms"
            )
        if profile["os"] == "Linux":
            product_summary = product_evidence.validate_bundle(
                bundle,
                {
                    **subjects[profile["kind"]],
                    "candidateSha": candidate,
                    "sourceKind": profile["kind"],
                    "workflowSha": workflow_sha,
                    "runId": run_id,
                    "runAttempt": attempt,
                    "runner": {
                        "ImageOS": platform["ImageOS"],
                        "ImageVersion": platform["ImageVersion"],
                        "RUNNER_ARCH": platform["RUNNER_ARCH"],
                    },
                },
            )
        else:
            if (bundle / product_evidence.PRODUCT_RELATIVE).exists():
                raise ValueError(f"{name}: foreign Linux product receipt")
            product_summary = None
        summaries.append(
            {
                "runner": profile["runner"],
                "os": profile["os"],
                "kind": profile["kind"],
                **subjects[profile["kind"]],
                "receiptSha256": file_digest(receipt_path),
                "artifacts": artifacts,
                "linuxProductObservation": product_summary,
            }
        )
    return {
        "schema": "hepta.ui.native.aggregate.v2",
        "candidateSha": candidate,
        "baseSha": base,
        "workflowSha": workflow_sha,
        "workflowFileSha256": workflow_digest,
        "runId": run_id,
        "runAttempt": attempt,
        "subjects": summaries,
        "qualificationPassed": True,
        "scope": "repository-controlled-candidate",
        "productionImplementation": False,
        "releaseAuthorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--bundles", type=Path, required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--workflow-sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        candidate_state = json.loads(
            evidence.git(
                args.root, "show", f"{args.candidate}:apps/hepta-native/CANDIDATE.json"
            )
        )
        workflow = subprocess.check_output(
            ["git", "show", f"{args.workflow_sha}:{evidence.WORKFLOW}"],
            cwd=args.root,
        )
        result = aggregate(
            args.bundles,
            candidate=args.candidate,
            base=args.base,
            workflow_sha=args.workflow_sha,
            workflow_digest=evidence.sha256(workflow),
            run_id=os.environ.get("GITHUB_RUN_ID", ""),
            attempt=os.environ.get("GITHUB_RUN_ATTEMPT", ""),
            subjects=deterministic_subjects(args.root, args.candidate, args.base),
            implementation=candidate_state["implementationSourceSha"],
        )
        evidence.write_json(args.out, result)
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"ui.native aggregate refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
