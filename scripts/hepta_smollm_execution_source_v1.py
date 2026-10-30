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
PROFILE_V2 = "hepta-integrated-chain-execution-v2"
CHAIN_COMMIT_V2 = "540d72356a921da31dde1113537382e5c0f0c4fd"
MANIFEST_NAME_V2 = "smollm2-public-initial-v2.execution-sources-v2.json"
MANIFEST_SHA256_V2 = "7db8bb705a7bf17e08aba973a7a4d2f9c14693d4a6af782abdc7c254dc91699a"
PROFILE_V3 = "hepta-integrated-chain-execution-v3"
CHAIN_COMMIT_V3 = "89218d818a1766c5610b64f09d75fc3d2ff6007d"
MANIFEST_NAME_V3 = "smollm2-public-initial-v2.execution-sources-v3.json"
MANIFEST_SHA256_V3 = "9dcd7666bb6462712356ee73a5f17d5d3fdecfea44a3ff8dad01dca10a25dfa3"
PROFILE_V4 = "hepta-integrated-chain-execution-v4"
CHAIN_COMMIT_V4 = "c16507147b65285ea94dead22d3b93c5db7295af"
MANIFEST_NAME_V4 = "smollm2-public-initial-v2.execution-sources-v4.json"
MANIFEST_SHA256_V4 = "cc88782c649504cbab886ba5040f183e27fb87d278d682492d68253101bc8f31"
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


def selected_source(profile):
    """Select only the reviewed identities; no caller may supply a commit."""
    if profile == PROFILE:
        return CHAIN_COMMIT, MANIFEST_NAME, MANIFEST_SHA256
    if profile == PROFILE_V2:
        return CHAIN_COMMIT_V2, MANIFEST_NAME_V2, MANIFEST_SHA256_V2
    if profile == PROFILE_V3:
        return CHAIN_COMMIT_V3, MANIFEST_NAME_V3, MANIFEST_SHA256_V3
    if profile == PROFILE_V4:
        return CHAIN_COMMIT_V4, MANIFEST_NAME_V4, MANIFEST_SHA256_V4
    raise ValueError("explicit closed execution-source profile required")


def checked_manifest(profile):
    """Verify the selected frozen identity while retaining historical material."""
    commit, manifest_name, manifest_sha256 = selected_source(profile)
    require(
        re.fullmatch(r"[0-9a-f]{40}", commit) is not None
        and re.fullmatch(r"[0-9a-f]{64}", manifest_sha256) is not None,
        "unpublishable execution source has not been frozen",
    )
    manifest_path = PROFILES / manifest_name
    require(
        manifest_path.is_file()
        and not manifest_path.is_symlink()
        and 0 < manifest_path.stat().st_size <= 64 * 1024,
        "regular bounded execution-source manifest",
    )
    raw = manifest_path.read_bytes()
    require(
        len(raw) <= 64 * 1024 and digest(raw) == manifest_sha256,
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
        and value["profile"] == profile
        and value["chain_commit"] == commit,
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
    require(head == value["chain_commit"], "exact integrated Chain commit required")
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
        "profile": profile,
        "chain_commit": head,
        "manifest_sha256": selected_source(profile)[2],
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
    parser.add_argument(
        "--profile",
        choices=[PROFILE, PROFILE_V2, PROFILE_V3, PROFILE_V4],
        required=True,
    )
    args = parser.parse_args()
    print(json.dumps(verify(args.chain, args.profile), sort_keys=True))


if __name__ == "__main__":
    main()
