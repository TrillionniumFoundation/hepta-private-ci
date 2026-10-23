#!/usr/bin/env python3
"""Fail-closed local source-worktree verification for a frozen A/B/C baseline.

This checks local Git objects, visible worktree dirt, and index concealment.
It does NOT attest a compiled binary, external dependencies, real tasks, or an
independent runtime/effect result. Its output must never authorize cutover.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

from compare import ComparisonError, checked_baseline

REPOS = ("hepta", "runtime", "codex")
SHA = re.compile(r"[0-9a-f]{40}\Z")


class SourceGuardError(ValueError):
    pass


def _git(path: Path, *args: str) -> bytes:
    # Host Git overrides could silently redirect object/index lookups.  Work
    # with the selected checkout only, without hooks, filters or fsmonitor.
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    env.update(
        {
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    cmd = [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=" + os.devnull,
        "-c",
        "core.untrackedCache=false",
        "-C",
        str(path),
        *args,
    ]
    try:
        proc = subprocess.run(
            cmd, env=env, capture_output=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SourceGuardError(f"git invocation failed: {error}") from error
    if proc.returncode:
        message = proc.stderr.decode("utf-8", "replace")[:300].strip()
        raise SourceGuardError(f"git {args[0]} failed: {message}")
    if len(proc.stdout) > 2_000_000:
        raise SourceGuardError("git inspection output exceeds bound")
    return proc.stdout


def _sha(text: object, label: str) -> str:
    if not isinstance(text, str) or not SHA.fullmatch(text) or text == "0" * 40:
        raise SourceGuardError(f"invalid pinned {label}")
    return text


def _verify_source_bytes(root: Path) -> None:
    # Git status applies clean/encoding/ident transformations. Compare the raw
    # filesystem bytes to HEAD objects as well, without running any filter.
    for entry in _git(root, "ls-tree", "-r", "-z", "--full-tree", "HEAD").split(b"\0"):
        if not entry:
            continue
        metadata, relative = entry.split(b"\t", 1)
        mode, kind, expected = metadata.split()
        if mode == b"160000":
            raise SourceGuardError("submodule source needs separate pinning")
        if kind != b"blob" or mode not in (b"100644", b"100755", b"120000"):
            raise SourceGuardError("unsupported tracked source mode")
        path = root / os.fsdecode(relative)
        if relative.startswith(b"/") or b".." in relative.split(b"/"):
            raise SourceGuardError("invalid tracked source path")
        for parent in path.parents:
            if parent == root:
                break
            if parent.is_symlink() or not parent.is_dir():
                raise SourceGuardError("tracked source parent is not a real directory")
        try:
            if mode == b"120000":
                if not path.is_symlink():
                    raise SourceGuardError("tracked source symlink changed")
                data = os.fsencode(os.readlink(path))
                actual = hashlib.sha1(
                    b"blob " + str(len(data)).encode() + b"\0" + data
                ).hexdigest()
            else:
                file_mode = path.lstat().st_mode
                if not stat.S_ISREG(file_mode):
                    raise SourceGuardError("tracked source is not a regular file")
                if bool(file_mode & stat.S_IXUSR) != (mode == b"100755"):
                    raise SourceGuardError(
                        "tracked source executable bit differs from pinned Git mode"
                    )
                with path.open("rb") as source:
                    size = os.fstat(source.fileno()).st_size
                    digest = hashlib.sha1(b"blob " + str(size).encode() + b"\0")
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
                    actual = digest.hexdigest()
        except OSError as error:
            raise SourceGuardError(f"tracked source unreadable: {error}") from error
        if actual != expected.decode("ascii"):
            raise SourceGuardError(
                "raw tracked source bytes differ from pinned Git blob"
            )


def verify_worktrees(baseline: object, paths: dict[str, str]) -> dict:
    if (
        not isinstance(baseline, dict)
        or baseline.get("schema") != "hepta.native-abc.v1"
    ):
        raise SourceGuardError("A/B/C baseline schema mismatch")
    sources = baseline.get("sources")
    if (
        not isinstance(sources, dict)
        or set(sources) != set(REPOS)
        or set(paths) != set(REPOS)
    ):
        raise SourceGuardError("exactly hepta, runtime and codex are required")

    verified = {}
    for owner in REPOS:
        expected = sources[owner]
        if not isinstance(expected, dict) or set(expected) != {"commit", "tree"}:
            raise SourceGuardError(f"{owner}: pinned commit and tree required")
        commit = _sha(expected["commit"], f"{owner} commit")
        tree = _sha(expected["tree"], f"{owner} tree")
        try:
            path = Path(paths[owner]).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise SourceGuardError(
                f"{owner}: repository path unavailable: {error}"
            ) from error
        if not path.is_dir():
            raise SourceGuardError(f"{owner}: repository root must be a directory")
        top = _git(path, "rev-parse", "--show-toplevel").decode().strip()
        if Path(top).resolve() != path:
            raise SourceGuardError(f"{owner}: path is not the repository root")
        # Inspect names only: configuration values may contain credentials.
        # This must precede object reads: partial clones can lazily run a
        # repository-configured transport while resolving a missing tree.
        keys = _git(path, "config", "--includes", "--null", "--name-only", "--list")
        names = [key.lower() for key in keys.split(b"\0")]
        if any(
            key == b"extensions.partialclone"
            or (
                key.startswith(b"remote.")
                and key.endswith((b".promisor", b".partialclonefilter"))
            )
            for key in names
        ):
            raise SourceGuardError(
                f"{owner}: partial/promisor Git sources are not permitted"
            )
        if any(key.startswith(b"filter.") for key in names):
            raise SourceGuardError(f"{owner}: configured Git filters are not permitted")
        observed_commit = (
            _git(path, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
        )
        observed_tree = (
            _git(path, "rev-parse", "--verify", "HEAD^{tree}").decode().strip()
        )
        if observed_commit != commit or observed_tree != tree:
            raise SourceGuardError(f"{owner}: checked-out Git commit/tree drift")

        # Status must not enter a submodule with its own uninspected filters.
        # Reject index gitlinks before status, and never recurse into submodules.
        for entry in _git(path, "ls-files", "--stage", "-z").split(b"\0"):
            if entry.startswith(b"160000 "):
                raise SourceGuardError(
                    f"{owner}: submodule source needs separate pinning"
                )
        # Porcelain status catches tracked, staged and visible untracked dirt.
        if _git(
            path,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignore-submodules=all",
        ):
            raise SourceGuardError(
                f"{owner}: modified, staged or untracked files present"
            )
        # A build may read ignored files even when porcelain status is clean.
        # Demand a source-only checkout before a reproducibility claim; callers
        # can keep generated outputs in separate worktrees or build directories.
        if _git(path, "ls-files", "--others", "--ignored", "--exclude-standard", "-z"):
            raise SourceGuardError(f"{owner}: ignored untracked files present")
        _verify_source_bytes(path)
        # Hidden index flags can conceal locally modified tracked inputs from
        # status, making a supposedly exact-source execution irreproducible.
        for entry in _git(path, "ls-files", "-v", "-z").split(b"\0"):
            if entry and (entry[:1].islower() or entry[:1] == b"S"):
                raise SourceGuardError(
                    f"{owner}: assume-unchanged/skip-worktree index entry"
                )
        verified[owner] = {"commit": commit, "tree": tree, "worktree_clean": True}

    # The existing comparison baseline validates tasks, model, target and
    # budgets.  A source match alone does not close that experiment gate.
    try:
        checked_baseline(baseline)
        ready, blocker = True, None
    except (ComparisonError, KeyError, TypeError, ValueError) as error:
        ready, blocker = False, str(error)
    return {
        "status": (
            "LOCAL_SOURCE_MATCH_EXPERIMENT_PINS_PRESENT"
            if ready
            else "LOCAL_SOURCE_MATCH_EXPERIMENT_PINS_MISSING"
        ),
        "verified_worktrees": verified,
        "experiment_pins_present": ready,
        "experiment_pin_blocker": blocker,
        "actual_built_source_attested": False,
        "hermetic_dependency_closure_attested": False,
        "independent_acceptance": False,
        "physical_execution_proven": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    for repo in REPOS:
        parser.add_argument("--" + repo, required=True)
    args = parser.parse_args(argv)
    try:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        result = verify_worktrees(
            baseline, {owner: getattr(args, owner) for owner in REPOS}
        )
    except (SourceGuardError, OSError, json.JSONDecodeError) as error:
        print(f"HOLD_NO_GO_SOURCE: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, indent=2))
    # Source-only matches are useful diagnostics but NOT a valid A/B/C baseline.
    return 0 if result["experiment_pins_present"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
