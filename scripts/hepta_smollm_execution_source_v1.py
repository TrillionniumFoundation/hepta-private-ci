#!/usr/bin/env python3
"""Verify one explicitly selected execution source for historical V2 material.

This source record grants no model compatibility, qualification or installation.
The original V2 profile, source manifest, target and plan remain immutable.
"""

import argparse
import hashlib
import json
import os
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
PROFILE_V5 = "hepta-integrated-chain-execution-v5"
CHAIN_COMMIT_V5 = "12fe5f2c1f19704fe7eb635dede6839ed8b1e91e"
CHAIN_TREE_V5 = "c44112da731e3f958e55eb024e5762d6723ea2c9"
MANIFEST_NAME_V5 = "smollm2-public-initial-v2.execution-sources-v5.json"
MANIFEST_SHA256_V5 = "2a706d08ecc1e92b4844662e16441a4342ac8e49dba9d5aae212a4a93bf8bc21"
# Freeze only after the final reviewed Chain source and its ordered merge exist.
PROFILE_V6 = "hepta-integrated-chain-execution-v6"
CHAIN_COMMIT_V6 = "44d3def32f515b98fc41f074fe1b88e97f046191"
CHAIN_TREE_V6 = "f3e07fc21a74e9a4367610ba10f5883213609320"
MANIFEST_NAME_V6 = "smollm2-public-initial-v2.execution-sources-v6.json"
MANIFEST_SHA256_V6 = "2ed9941e5e2051f4773364b2e379c9e8866a0fde0a3a5afd6f5b5357244d5dc8"
PROFILE_V7 = "hepta-integrated-chain-execution-v7"
CHAIN_COMMIT_V7 = "a10c39025cdc03d3265b031d6547b11e0350da2c"
CHAIN_TREE_V7 = "f82a65891b8c5d094ad9a67450751253ec150910"
MANIFEST_NAME_V7 = "smollm2-public-initial-v2.execution-sources-v7.json"
MANIFEST_SHA256_V7 = "f39b96cbac0e429c7fc3712217a9fdbbe03248d2b5c12e4ebe1fe15be7a5eef8"
PROFILE_V8 = "hepta-integrated-chain-execution-v8"
CHAIN_COMMIT_V8 = "73ab6e9a83bcc836e261d93f9bb23ceafe556758"
CHAIN_TREE_V8 = "65a2100f3feccc29a096a3348c109d77f0a656c2"
MANIFEST_NAME_V8 = "smollm2-public-initial-v2.execution-sources-v8.json"
MANIFEST_SHA256_V8 = "e712ccdd8218e81ade0ac7202f00259fc60c1ebd5f10a468323b7298df406ab5"
# Published only after the new Chain source and its ordered merge are verified.
PROFILE_V9 = "hepta-integrated-chain-execution-v9"
CHAIN_COMMIT_V9 = "c156c2310346d1367b8f9b1111171f412b5ffce2"
CHAIN_TREE_V9 = "6ee8553bf3960ff31268a65bfc0c54970dfc12fb"
MANIFEST_NAME_V9 = "smollm2-public-initial-v2.execution-sources-v9.json"
MANIFEST_SHA256_V9 = "cd1d7cdf1e53c890eb0483b0e57e9050de04cbdd51fcbd1f91837da80fb279d7"
# A new ordinary-runtime pair never inherits a previous source tuple's evidence.
PROFILE_V10 = "hepta-integrated-chain-execution-v10"
CHAIN_COMMIT_V10 = "04be5f02c84cf5cb626a53f34bc03a5bd6ff5137"
CHAIN_TREE_V10 = "d4f4a85c439982d8decec9265c1993408f3577cf"
MANIFEST_NAME_V10 = "smollm2-public-initial-v2.execution-sources-v10.json"
MANIFEST_SHA256_V10 = "97e5311a86a0dc6fcd62a29ca9cd8a323c9b34a6991790ae347cfbb57bf796ed"
# Freeze the runtime-bound ordinary source separately from historical V10.
PROFILE_V11 = "hepta-integrated-chain-execution-v11"
CHAIN_COMMIT_V11 = "cfa57cd04751427451302b5c10539b3984d7f8db"
CHAIN_TREE_V11 = "155213c2468edc411325f4f1853b471a6b25f355"
MANIFEST_NAME_V11 = "smollm2-public-initial-v2.execution-sources-v11.json"
MANIFEST_SHA256_V11 = "a951e866f66b0e251fc5a9f81d02a7f86954d1b3ca8ac483890fcb23a4955647"
# Current cross-repository source identity; historical profiles remain immutable.
PROFILE_V12 = "hepta-integrated-chain-execution-v12"
CHAIN_COMMIT_V12 = "ea909124cc460f364bd17b009073306014133f48"
CHAIN_TREE_V12 = "96712231eba3d333bdfebefa9c22c80ea1794d04"
MANIFEST_NAME_V12 = "smollm2-public-initial-v2.execution-sources-v12.json"
MANIFEST_SHA256_V12 = "cfa13f947bad8bcb7bc896f11448015164a9e9832ca8ff283bc32f9b0127193a"
RUNTIME_SOURCES_V11 = frozenset(
    (
        "formal/pon-nakamoto-v1/contract_wire.py",
        "formal/pon-nakamoto-v1/llm_adapter_contract.py",
        "config/pon/devnet-v1.json",
        "config/pon/ledger-v1.json",
        "config/pon/model-family-v1.json",
        "config/pon/work-profile-v1.json",
        "config/pon/model-family-smollm2-135m-v1.json",
        "scripts/llm_base_material.py",
        "scripts/llm_inherited_runtime.py",
        "scripts/llm_neural_read_worker.py",
        "scripts/llm_parent_material.py",
        "scripts/llm_python_runtime_contract.py",
        "scripts/llm_runtime_pilot.py",
    )
)
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


def registered_sources():
    """Own the closed profile registry for both CLI parsing and verification."""
    return {
        PROFILE: (CHAIN_COMMIT, MANIFEST_NAME, MANIFEST_SHA256),
        PROFILE_V2: (CHAIN_COMMIT_V2, MANIFEST_NAME_V2, MANIFEST_SHA256_V2),
        PROFILE_V3: (CHAIN_COMMIT_V3, MANIFEST_NAME_V3, MANIFEST_SHA256_V3),
        PROFILE_V4: (CHAIN_COMMIT_V4, MANIFEST_NAME_V4, MANIFEST_SHA256_V4),
        PROFILE_V5: (CHAIN_COMMIT_V5, MANIFEST_NAME_V5, MANIFEST_SHA256_V5),
        PROFILE_V6: (CHAIN_COMMIT_V6, MANIFEST_NAME_V6, MANIFEST_SHA256_V6),
        PROFILE_V7: (CHAIN_COMMIT_V7, MANIFEST_NAME_V7, MANIFEST_SHA256_V7),
        PROFILE_V8: (CHAIN_COMMIT_V8, MANIFEST_NAME_V8, MANIFEST_SHA256_V8),
        PROFILE_V9: (CHAIN_COMMIT_V9, MANIFEST_NAME_V9, MANIFEST_SHA256_V9),
        PROFILE_V10: (CHAIN_COMMIT_V10, MANIFEST_NAME_V10, MANIFEST_SHA256_V10),
        PROFILE_V11: (CHAIN_COMMIT_V11, MANIFEST_NAME_V11, MANIFEST_SHA256_V11),
        PROFILE_V12: (CHAIN_COMMIT_V12, MANIFEST_NAME_V12, MANIFEST_SHA256_V12),
    }


def registered_trees():
    """Keep commit-and-tree profiles explicit while retaining legacy identities."""
    return {
        PROFILE_V5: CHAIN_TREE_V5,
        PROFILE_V6: CHAIN_TREE_V6,
        PROFILE_V7: CHAIN_TREE_V7,
        PROFILE_V8: CHAIN_TREE_V8,
        PROFILE_V9: CHAIN_TREE_V9,
        PROFILE_V10: CHAIN_TREE_V10,
        PROFILE_V11: CHAIN_TREE_V11,
        PROFILE_V12: CHAIN_TREE_V12,
    }


def selected_source(profile):
    """Select only the reviewed identities; no caller may supply a commit."""
    sources = registered_sources()
    require(
        type(profile) is str and profile in sources,
        "explicit closed execution-source profile required",
    )
    return sources[profile]


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
        | ({"chain_tree"} if profile in registered_trees() else set())
        and value["schema"]
        == "hepta-smollm-public-initial-execution-sources-"
        + ("v2" if profile in registered_trees() else "v1")
        and value["profile"] == profile
        and value["chain_commit"] == commit,
        "closed exact execution-source identity",
    )
    if profile in registered_trees():
        require(
            re.fullmatch(r"[0-9a-f]{40}", registered_trees()[profile]) is not None
            and value["chain_tree"] == registered_trees()[profile],
            "exact integrated Chain tree required",
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


def require_legacy_worker_profile(profile):
    """The old study forward has no explicit runtime-snapshot admission input."""
    require(
        profile not in (PROFILE_V11, PROFILE_V12),
        "V11 or V12 cannot execute the legacy worker-v1 forward",
    )


def verify(chain, profile):
    """Reject unreviewed or mixed source bytes before any Chain import."""
    return _verify(chain, profile, None)


def verify_merged(chain, profile, base):
    """Check the actual ordered merge with the selected source-input guard."""
    require(
        profile in (PROFILE_V9, PROFILE_V10, PROFILE_V11, PROFILE_V12),
        "merged execution-source verification requires V9, V10, V11 or V12",
    )
    require(
        type(base) is str and re.fullmatch(r"[0-9a-f]{40}", base) is not None,
        "explicit exact merge base required",
    )
    return _verify(chain, profile, base)


def _verify(chain, profile, base):
    value = checked_manifest(profile)
    chain = Path(chain)
    require(
        chain.is_absolute() and chain.resolve() == chain, "absolute execution checkout"
    )
    # Reuse the existing reader's environment, replacement and hook policy.
    head = git("rev-parse", "HEAD", repository=chain)
    if base is None:
        require(head == value["chain_commit"], "exact integrated Chain commit required")
        if profile in (PROFILE_V10, PROFILE_V11, PROFILE_V12):
            # Use the same complete raw-byte and hidden-index policy as the
            # merge lane. Python-only checks cannot bind native Cargo sources,
            # lockfiles or build configuration used by ordinary runtime work.
            from hepta_ci_candidate import candidate_plan

            candidate_plan(
                source=value["chain_commit"],
                tested=head,
                lane="source-head",
                repository=chain,
            )
    else:
        # Reuse the existing candidate owner: matching trees alone cannot admit
        # unrelated ancestry, reversed parents, or a noncanonical merge. This reads
        # the actual checkout; it never switches HEAD or repairs source inputs.
        from hepta_ci_candidate import candidate_plan

        candidate = candidate_plan(
            source=value["chain_commit"],
            tested=head,
            lane="base-merge",
            base=base,
            repository=chain,
        )
        require(
            candidate["source_tree"] == value["chain_tree"],
            "exact integrated Chain source tree required",
        )
    if profile in registered_trees():
        require(
            git("rev-parse", "HEAD^{tree}", repository=chain) == value["chain_tree"],
            "exact integrated Chain tree required",
        )
    if profile in (PROFILE_V9, PROFILE_V10, PROFILE_V11, PROFILE_V12):
        version = profile.rsplit("-", 1)[-1].upper()
        input_paths = ("scripts", "formal", "config")
        if profile in (PROFILE_V10, PROFILE_V11, PROFILE_V12):
            input_paths += ("trillionnium/crates", "trillionnium/.cargo", ".cargo")
        # Both this interpreter and its children must leave the frozen import
        # directories unchanged. Do not repair the caller's environment or
        # delete existing bytecode: either would hide an invalid source input.
        require(
            sys.dont_write_bytecode
            and os.environ.get("PYTHONDONTWRITEBYTECODE") == "1",
            f"{version} requires disabled bytecode writes and inherited PYTHONDONTWRITEBYTECODE=1",
        )
        # Reuse the CI identity owner's flag policy without refreshing or
        # clearing the caller's index. Raw hashes still check every pinned file.
        require(
            not any(
                row and (row[0] == "S" or row[0].islower())
                for row in git(
                    "ls-files",
                    "-v",
                    "-z",
                    "--",
                    *input_paths,
                    repository=chain,
                ).split("\0")
            ),
            f"{version} execution source contains hidden index flags",
        )
        # Deliberately omit --exclude-standard: ignored packages, bytecode,
        # native extensions and directory symlinks can alter Python imports
        # while every manifest byte remains intact. This is a source-input
        # boundary, not a sandbox for arbitrary import hooks or runtime code.
        require(
            not git(
                "ls-files",
                "--others",
                "-z",
                "--",
                *input_paths,
                repository=chain,
            ),
            f"{version} execution source contains untracked or ignored inputs",
        )
    git(
        "diff",
        *(
            ("--no-ext-diff", "--no-textconv")
            if profile in (PROFILE_V9, PROFILE_V10, PROFILE_V11, PROFILE_V12)
            else ()
        ),
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
    if profile in (PROFILE_V11, PROFILE_V12):
        previous = PROFILE_V10 if profile == PROFILE_V11 else PROFILE_V11
        require(
            set(checked_manifest(previous)["files"]) | RUNTIME_SOURCES_V11
            <= set(value["files"]),
            f"{profile.rsplit('-', 1)[-1].upper()} requires the complete "
            f"{previous.rsplit('-', 1)[-1].upper()} and runtime admission source closure",
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
    result = {
        "schema": "hepta-smollm-public-initial-execution-source-verified-v1",
        "profile": profile,
        "chain_commit": value["chain_commit"],
        "manifest_sha256": selected_source(profile)[2],
        "historical_profile_sha256": HISTORICAL_PROFILE_SHA256,
        "historical_sources_sha256": HISTORICAL_SOURCES_SHA256,
        "verified_source_files": len(value["files"]),
        "model_compatibility_changed": False,
        "product_qualification": False,
        "installation_authorized": False,
    }
    if profile in registered_trees():
        result["chain_tree"] = value["chain_tree"]
    if base is not None:
        result.update(tested_commit=head, base_commit=base, lane="base-merge")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", type=Path, required=True)
    parser.add_argument(
        "--profile",
        choices=registered_sources(),
        required=True,
    )
    args = parser.parse_args()
    print(json.dumps(verify(args.chain, args.profile), sort_keys=True))


if __name__ == "__main__":
    main()
