"""Overlay only A6, validate two generated locks and retain a local Git candidate."""

from pathlib import Path
import re
import tomllib

from . import contract as c
from .runtime import (
    git_hash,
    json_value,
    leaf_pin,
    put,
    put_raw,
    require,
    sha256,
    stable_read,
)
from .source import proposal_bytes


def overlay_stage_a(ctx, spec, original):
    for row in spec["proposal_files"]:
        name = row["target"]
        target = ctx.root / name
        data = proposal_bytes(ctx, row)
        if row["before"] is None:
            require(
                name not in original
                and not target.exists()
                and not target.is_symlink(),
                "new utility source already exists: " + name,
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(data)
        else:
            before, _ = stable_read(target)
            require(
                leaf_pin(before, "100644") == row["before"]
                and original[name] == row["before"],
                "existing source differs from proposal preimage: " + name,
            )
            with target.open("wb") as stream:
                stream.write(data)
        target.chmod(0o644)
        observed, _ = stable_read(target)
        require(
            observed == data and leaf_pin(observed, "100644") == row["after"],
            "proposal overlay did not retain its exact source bytes",
        )
    ctx.check_time()


def package_key(row):
    return (row["name"], row["version"], row.get("source"))


def verify_cargo_lock(before_raw, after_raw):
    before = tomllib.loads(before_raw.decode("utf-8"))
    after = tomllib.loads(after_raw.decode("utf-8"))
    original = {package_key(row): row for row in before["package"]}
    proposed = {package_key(row): row for row in after["package"]}
    require(
        len(original) == len(before["package"])
        and len(proposed) == len(after["package"]),
        "duplicate lock package identity",
    )
    added = set(proposed) - set(original)
    require(
        len(added) == 1
        and next(iter(added))[0] == c.PACKAGE
        and next(iter(added))[2] is None
        and set(original) <= set(proposed),
        "Cargo generation changed more than the one new workspace package",
    )
    require(
        all(proposed[key] == value for key, value in original.items()),
        "an existing package/version/checksum/dependency row drifted",
    )
    old_headers = {key: value for key, value in before.items() if key != "package"}
    new_headers = {key: value for key, value in after.items() if key != "package"}
    require(old_headers == new_headers, "non-package lock contract changed")
    return {
        "old_package_count": len(original),
        "new_package_count": len(proposed),
        "added_package": proposed[next(iter(added))],
        "all_existing_package_rows_unchanged": True,
        "all_other_toml_fields_unchanged": True,
        "registry_version_or_checksum_drift": False,
    }


def verify_metadata(ctx, raw, lock_raw, spec):
    metadata, json_raw = json_value(raw), raw
    require(
        type(metadata) is dict and "packages" in metadata,
        "metadata stdout is not one complete JSON object",
    )
    require(
        metadata["version"] == 1 and metadata["resolve"] is not None,
        "full all-features metadata resolution is absent",
    )
    packages = metadata["packages"]
    by_id = {row["id"]: row for row in packages}
    require(len(by_id) == len(packages), "metadata repeats a package ID")
    members = metadata["workspace_members"]
    require(
        len(members) == len(set(members)) == spec["baseline_workspace_members"] + 1,
        "workspace membership did not add exactly one utility member",
    )
    new = [
        row for row in packages if row["name"] == c.PACKAGE and row["source"] is None
    ]
    require(
        len(new) == 1
        and new[0]["id"] in members
        and Path(new[0]["manifest_path"]).resolve()
        == ctx.root / "codex-rs/utils/time/Cargo.toml",
        "new utility is not the actual workspace package",
    )
    require(
        [target["kind"] for target in new[0]["targets"]] == [["lib"]]
        and new[0]["targets"][0]["name"] == "codex_utils_time"
        and new[0]["targets"][0]["doctest"] is False,
        "utility target shape differs from the source registration",
    )
    lock = tomllib.loads(lock_raw.decode())
    lock_keys = {package_key(row) for row in lock["package"]}
    require(
        all(package_key(row) in lock_keys for row in packages),
        "metadata contains a package absent from the actual generated lock",
    )
    nodes = {row["id"]: row for row in metadata["resolve"]["nodes"]}
    require(
        len(nodes) == len(metadata["resolve"]["nodes"]) and set(nodes) == set(by_id),
        "full metadata node/package coverage differs",
    )
    stack = [new[0]["id"]]
    reached = set()
    while stack:
        item = stack.pop()
        if item in reached:
            continue
        reached.add(item)
        require(
            item in nodes and item in by_id,
            "utility graph references an absent package",
        )
        require(by_id[item]["name"] != "chrono", "new utility still reaches Chrono")
        stack.extend(dep["pkg"] for dep in nodes[item]["deps"])
    times = [
        row for row in packages if row["name"] == "time" and row["version"] == "0.3.55"
    ]
    require(
        len(times) == 1
        and times[0]["id"] in reached
        and "parsing" in nodes[times[0]["id"]]["features"],
        "locked time 0.3.55 parsing feature is not active in the actual utility graph",
    )
    return (
        metadata,
        json_raw,
        {
            "packages": len(packages),
            "resolve_nodes": len(nodes),
            "workspace_members": len(members),
            "utility_package_id": new[0]["id"],
            "utility_reachable_packages": sorted(reached),
            "utility_reaches_chrono": False,
            "whole_repo_chrono_removed": False,
        },
    )


def retain_postimages(ctx, directory):
    result = {}
    for name in sorted(c.GENERATED_PATHS):
        target = ctx.root / name
        if not target.exists() and not target.is_symlink():
            result[name] = {"present": False}
            continue
        raw, info = stable_read(target)
        require(not (info.st_mode & 0o111), "generated source unexpectedly executable")
        put_raw(ctx.evidence / directory / name, raw)
        result[name] = {"present": True, **leaf_pin(raw, "100644")}
    put(ctx.evidence / (directory + ".manifest.json"), result)
    return result


def verify_generation_boundary(ctx, original_tree, original_snapshot, spec):
    """Verify every original leaf plus every permitted new utility leaf."""
    require(
        not ctx.git("diff", "--cached", "--name-only", "HEAD"),
        "generation unexpectedly staged source",
    )
    original_observed = ctx.snapshot(original_tree, c.GENERATED_PATHS)
    require(
        all(
            original_observed[name] == row
            for name, row in original_snapshot.items()
            if name not in c.GENERATED_PATHS
        ),
        "generation changed an unrelated physical source leaf",
    )
    tracked_changed = {
        raw.decode("utf-8")
        for raw in ctx.git("diff", "--name-only", "--no-renames", "-z", "HEAD").split(
            b"\0"
        )
        if raw
    }
    untracked = {
        raw.decode("utf-8")
        for raw in ctx.git("ls-files", "--others", "--exclude-standard", "-z").split(
            b"\0"
        )
        if raw
    }
    require(
        tracked_changed <= c.GENERATED_PATHS and untracked == set(c.STAGE_PATHS[1:]),
        "generation changed or created an unreviewed path",
    )
    for row in spec["proposal_files"]:
        if row["target"] in ("codex-rs/Cargo.toml", "codex-rs/utils/time/Cargo.toml"):
            raw, _ = stable_read(ctx.root / row["target"])
            require(
                leaf_pin(raw, "100644") == row["after"],
                "a formatter/fix changed the reviewed manifest contract",
            )
    return original_observed


def create_local_candidate(ctx, generation, original_snapshot, spec):
    """Create only local Git objects from the exact retained eight-path delta."""
    require(
        stable_read(ctx.root / ".git/HEAD", 128)[0]
        == (generation["head"] + "\n").encode(),
        "generation checkout must have a detached HEAD",
    )
    for name in c.GENERATED_PATHS:
        require((ctx.root / name).is_file(), "candidate postimage is missing")
    ctx.git("add", "--", *sorted(c.GENERATED_PATHS))
    changed = {
        row.decode()
        for row in ctx.git(
            "diff", "--cached", "--name-only", "--no-renames", "-z", generation["head"]
        ).split(b"\0")
        if row
    }
    require(
        set(c.STAGE_PATHS) <= changed <= c.GENERATED_PATHS
        and "codex-rs/Cargo.lock" in changed,
        "staged candidate is not precisely the Stage A source and generated locks",
    )
    tree = ctx.git("write-tree").decode().strip()
    require(re.fullmatch(r"[0-9a-f]{40}", tree) is not None, "local tree absent")
    original_raw = stable_read(ctx.evidence / "generation-head.commit.raw")[0]
    headers = original_raw.split(b"\n\n", 1)[0].decode().splitlines()
    committers = [line for line in headers if line.startswith("committer ")]
    require(len(committers) == 1, "generation commit lacks one committer")
    match = re.fullmatch(
        r"committer .+ <[^>\r\n]+> ([0-9]+) [+-][0-9]{4}", committers[0]
    )
    require(match is not None, "generation committer timestamp is malformed")
    epoch = int(match[1]) + 1
    author = "Hepta Stage A CI <hepta-stage-a@users.noreply.github.com>"
    raw = (
        f"tree {tree}\nparent {generation['head']}\n"
        f"author {author} {epoch} +0000\ncommitter {author} {epoch} +0000\n\n"
        "Stage A utility generated local review candidate\n"
    ).encode()
    head = git_hash("commit", raw)
    raw_path = ctx.evidence / "local-derived-candidate.commit.raw"
    put_raw(raw_path, raw)
    created = (
        ctx.git("hash-object", "-t", "commit", "-w", str(raw_path)).decode().strip()
    )
    require(created == head, "local commit object differs from its exact raw bytes")
    # No branch, remote ref, GitHub event, workflow ref, or published commit is
    # modified. Compare-and-swap updates this detached local HEAD only.
    ctx.git("update-ref", "--no-deref", "HEAD", head, generation["head"])
    candidate, readback = ctx.commit_identity(head)
    require(
        readback == raw
        and candidate == {"head": head, "tree": tree, "parents": [generation["head"]]},
        "local candidate raw/tree/sole-parent readback differs",
    )
    ctx.assert_clean()
    snapshot = ctx.snapshot(tree)
    require(
        set(snapshot) == set(original_snapshot) | set(c.STAGE_PATHS)
        and all(
            snapshot[name] == pin
            for name, pin in original_snapshot.items()
            if name not in c.GENERATED_PATHS
        ),
        "derived commit changed a path outside the actual Stage A delta",
    )
    snapshot_pin = put(ctx.evidence / "local-source-before-native.json", snapshot)
    raw_patch = ctx.git(
        "diff",
        "--binary",
        "--no-ext-diff",
        "--no-renames",
        generation["head"],
        head,
        "--",
        *sorted(c.GENERATED_PATHS),
    )
    patch_pin = put_raw(ctx.evidence / "local-derived-candidate.patch", raw_patch)
    envelope = {
        "status": "LOCAL_DERIVED_CANDIDATE_ONLY",
        "generation": generation,
        "local_tested_identity": candidate,
        "raw_commit": {"bytes": len(raw), "sha256": sha256(raw), "git_commit": head},
        "local_source_snapshot": snapshot_pin,
        "actual_delta": sorted(changed),
        "actual_postimage_patch": patch_pin,
        "github_write_performed": False,
        "local_commit_is_the_published_generation_head": False,
        "independent_Root_postimage_review_required": True,
        "independent_actual_publication_identity_readback_required": True,
        **c.FALSE_QUALIFICATION,
    }
    put(ctx.evidence / "candidate-identity-envelope.json", envelope)
    return candidate, snapshot, envelope
