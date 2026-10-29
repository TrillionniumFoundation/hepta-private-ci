#!/usr/bin/env python3
"""Verify one explicitly selected execution source for historical V2 material.

This source record grants no model compatibility, qualification or installation.
The original V2 profile, source manifest, target and plan remain immutable.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hepta_ci_exec import git


PROFILE = "hepta-integrated-chain-execution-v1"
CHAIN_COMMIT = "147bae52e9abbc6f91f89f85e42c5dff4ae53d23"
PROFILES = (
    Path(__file__).resolve().parents[1] / "codex-rs/hepta-learning-artifacts/profiles"
)
MANIFEST_NAME = "smollm2-public-initial-v2.execution-sources-v1.json"
MANIFEST_SHA256 = "4b92ec8b9aa385148dc7bfc4d35630a05b5ced93fef1c503305ff8e28d0b1e6a"
HISTORICAL_PROFILE_SHA256 = (
    "695d12e8dce5c289a063effdbcc2289148b4708a4a6ead77199da734e0dba2c8"
)
HISTORICAL_SOURCES_SHA256 = (
    "c4a529e9710f18feaa4996457991876d3999d36bdde285903e72d7180f8bbd0c"
)


def require(value, reason):
    if not value:
        raise ValueError(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def unique(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "duplicate execution-source field")
        value[key] = item
    return value


def checked_manifest(profile):
    """Select exactly one frozen execution identity, never an environment SHA."""
    require(profile == PROFILE, "explicit closed execution-source profile required")
    require(
        re.fullmatch(r"[0-9a-f]{40}", CHAIN_COMMIT) is not None
        and re.fullmatch(r"[0-9a-f]{64}", MANIFEST_SHA256) is not None,
        "unpublishable execution source has not been frozen",
    )
    manifest_path = PROFILES / MANIFEST_NAME
    require(
        manifest_path.is_file()
        and not manifest_path.is_symlink()
        and 0 < manifest_path.stat().st_size <= 64 * 1024,
        "regular bounded execution-source manifest",
    )
    raw = manifest_path.read_bytes()
    require(
        len(raw) <= 64 * 1024 and digest(raw) == MANIFEST_SHA256,
        "exact execution-source manifest",
    )
    value = json.loads(raw, object_pairs_hook=unique)
    require(
        type(value) is dict
        and set(value)
        == {
            "schema",
            "profile",
            "chain_commit",
            "historical_profile_sha256",
            "historical_sources_sha256",
            "files",
        }
        and value["schema"] == "hepta-smollm-public-initial-execution-sources-v1"
        and value["profile"] == PROFILE
        and value["chain_commit"] == CHAIN_COMMIT,
        "closed exact execution-source identity",
    )
    for name, field, expected in (
        (
            "smollm2-public-initial-v2.profile",
            "historical_profile_sha256",
            HISTORICAL_PROFILE_SHA256,
        ),
        (
            "smollm2-public-initial-v2.sources.json",
            "historical_sources_sha256",
            HISTORICAL_SOURCES_SHA256,
        ),
    ):
        require(
            value[field] == expected
            and digest((PROFILES / name).read_bytes()) == expected,
            "historical V2 source and compatibility identities must remain unchanged",
        )
    return value


def selected_commit(historical_commit, profile):
    """Keep every legacy caller's exact guard unless the new profile is explicit."""
    if profile is None:
        return historical_commit
    return checked_manifest(profile)["chain_commit"]


def verify_selected(chain, profile):
    if profile is not None:
        return verify(chain, profile)
    return None


def verify(chain, profile):
    """Reject unreviewed or mixed source bytes before any Chain import."""
    value = checked_manifest(profile)
    chain = Path(chain)
    require(
        chain.is_absolute() and chain.resolve() == chain, "absolute execution checkout"
    )
    # Reuse the existing reader's environment, replacement and hook policy.
    head = git("rev-parse", "HEAD", repository=chain)
    require(head == CHAIN_COMMIT, "exact integrated Chain commit required")
    git(
        "diff",
        "--exit-code",
        "HEAD",
        "--",
        "scripts",
        "formal",
        "config",
        repository=chain,
    )
    require(
        not git(
            "status",
            "--porcelain",
            "--untracked-files=normal",
            "--",
            "scripts",
            "formal",
            "config",
            repository=chain,
        ),
        "execution source contains uncommitted or untracked inputs",
    )
    require(
        type(value["files"]) is dict and 0 < len(value["files"]) <= 64,
        "bounded execution-source closure",
    )
    historical = json.loads(
        (PROFILES / "smollm2-public-initial-v2.sources.json").read_bytes(),
        object_pairs_hook=unique,
    )
    require(
        set(historical["files"]) <= set(value["files"]),
        "complete original source closure required",
    )
    for relative, expected in value["files"].items():
        require(
            type(relative) is str
            and not Path(relative).is_absolute()
            and ".." not in Path(relative).parts
            and type(expected) is dict
            and set(expected) == {"size", "sha256"}
            and type(expected["size"]) is int
            and 0 < expected["size"] <= 4 * 1024 * 1024,
            "closed regular bounded execution source",
        )
        path = chain / relative
        require(
            path.resolve() == path
            and path.is_file()
            and path.stat().st_size == expected["size"],
            f"execution source size or path changed: {relative}",
        )
        source = path.read_bytes()
        require(
            len(source) == expected["size"] and digest(source) == expected["sha256"],
            f"execution source bytes changed: {relative}",
        )
    return {
        "schema": "hepta-smollm-public-initial-execution-source-verified-v1",
        "profile": PROFILE,
        "chain_commit": head,
        "manifest_sha256": MANIFEST_SHA256,
        "historical_profile_sha256": HISTORICAL_PROFILE_SHA256,
        "historical_sources_sha256": HISTORICAL_SOURCES_SHA256,
        "verified_source_files": len(value["files"]),
        "model_compatibility_changed": False,
        "product_qualification": False,
        "installation_authorized": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", type=Path, required=True)
    parser.add_argument("--profile", choices=[PROFILE], required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.chain, args.profile), sort_keys=True))


if __name__ == "__main__":
    main()
