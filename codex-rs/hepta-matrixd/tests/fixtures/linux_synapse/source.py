"""Producer artifact -> unchanged restored checkout -> isolated qualification commit."""

from datetime import datetime, timezone
from pathlib import Path
import re
import stat
import sys
import types

from .commands import Commands
from .contract import ENTRY
from .files import (
    copy_file,
    describe,
    physical,
    regular,
    verify,
    write_bytes,
    write_json,
)


class PortGuard:
    """Adapt the existing, source-bound port guards without changing their policy."""

    def __init__(self, root, output, commands):
        self.root, self.output, self.commands = root, output, commands
        self.record = {"original_dependency_policy_unchanged": False}
        self.snapshots = 0

    def text(self, label, command):
        return self.commands.text(command[0], command[1:], label=label)

    def run(self, label, command):
        return self.commands.run(command[0], command[1:], label=label)

    def save(self):
        write_json(self.output / f"policy-guard-{self.snapshots:03d}.json", self.record)
        self.snapshots += 1


def git_clean(commands):
    status = commands.text(
        "git",
        ["status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching"],
        label="source-status",
    )
    if status:
        raise ValueError(
            "Qualification worktree contains changed, untracked or ignored files"
        )
    return status


def load_verified_helper(source_bytes, helper):
    """Compile bytes already bound to HEAD; neither .pyc nor workspace stdlib shadows."""
    common = types.ModuleType("hepta_bound_port_guard")
    common.__file__ = str(helper)
    previous = sys.path
    standard = (
        Path(sys.base_prefix)
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
    )
    try:
        sys.path = [str(standard), str(standard / "lib-dynload")]
        exec(
            compile(source_bytes, str(helper), "exec", dont_inherit=True),
            common.__dict__,
        )
    finally:
        sys.path = previous
    return common


def replay_candidate_tree(commands, producer_dir, candidate, source_sha, output):
    patch = producer_dir / "candidate.patch"
    verify(patch, candidate["artifacts"]["candidate.patch"])
    environment = {"GIT_INDEX_FILE": str(output / "candidate-replay.index")}
    commands.run(
        "git",
        ["read-tree", source_sha],
        label="independent-base-index",
        environment=environment,
    )
    commands.run(
        "git",
        ["apply", "--check", "--cached", str(patch)],
        label="check-exact-producer-patch",
        environment=environment,
    )
    commands.run(
        "git",
        ["apply", "--cached", str(patch)],
        label="replay-exact-producer-patch",
        environment=environment,
    )
    _, expected_path = commands.run(
        "git", ["write-tree"], label="producer-patch-tree", environment=environment
    )
    expected = expected_path.read_text().strip()
    original_index = Path(
        commands.text(
            "git", ["rev-parse", "--git-path", "index"], label="original-index-path"
        )
    )
    if not original_index.is_absolute():
        original_index = commands.cwd / original_index
    copy_file(original_index, output / "actual-candidate.index")
    _, actual_path = commands.run(
        "git",
        ["write-tree"],
        label="actual-candidate-index-tree",
        environment={"GIT_INDEX_FILE": str(output / "actual-candidate.index")},
    )
    actual = actual_path.read_text().strip()
    if actual != expected:
        raise ValueError(
            "Candidate Git tree differs from the producer patch, including file modes"
        )
    return actual


def trusted_common(commands, source_sha):
    """The same pre-execution guard serves clean restore and already staged inputs."""
    if commands.text("git", ["rev-parse", "HEAD"], label="original-head") != source_sha:
        raise ValueError(
            "Restored checkout HEAD differs before loading any candidate helper"
        )
    commands.run(
        "git", ["diff", "--exit-code"], label="preimport-index-equals-worktree"
    )
    for suffix, args in (
        ("untracked", ["--others", "--exclude-standard"]),
        ("ignored", ["--others", "--ignored", "--exclude-standard"]),
    ):
        if commands.text("git", ["ls-files", *args], label=f"preimport-{suffix}"):
            raise ValueError(
                "Restored source has extra inputs before loading its helper"
            )
    helper_name = "scripts/ndu_port_candidate_common.py"
    helper = regular(commands.cwd / helper_name)
    _, committed_helper = commands.run(
        "git",
        ["show", f"{source_sha}:{helper_name}"],
        label="preimport-head-helper-blob",
    )
    mode = commands.text(
        "git",
        ["ls-tree", source_sha, "--", helper_name],
        label="preimport-head-helper-mode",
    )
    if not re.fullmatch(
        r"100(?:644|755) blob [0-9a-f]{40}\t" + re.escape(helper_name), mode
    ):
        raise ValueError(
            "HEAD helper is not one regular executable/non-executable Git blob"
        )
    expected_mode = 0o755 if mode.startswith("100755 ") else 0o644
    if (
        describe(helper) != describe(committed_helper)
        or stat.S_IMODE(helper.stat().st_mode) != expected_mode
    ):
        raise ValueError(
            "Candidate helper differs byte-for-byte or in mode from the exact trusted HEAD"
        )
    # SourceFileLoader may execute a timestamp/size-matching staged .pyc even
    # when bytecode writing is disabled. Compile the verified HEAD blob itself.
    return load_verified_helper(committed_helper.read_bytes(), helper), helper


def restore_source(
    restored_root, producer_dir, result_sha, source_sha, output, commands
):
    """Use every original port restore/policy/graph guard without a host Rust build."""
    git_clean(commands)
    common, _helper = trusted_common(commands, source_sha)
    guard = PortGuard(restored_root, output, commands)
    candidate, recipe = common.restore_candidate(
        guard, producer_dir, result_sha, source_sha
    )
    tree = replay_candidate_tree(commands, producer_dir, candidate, source_sha, output)
    guard.record.update(
        candidate_tree=tree,
        host_rust_toolchain_used=False,
        compilation_toolchain_authority="separately sealed native ARM64 builder",
    )
    guard.save()
    write_json(output / "RESTORED_SOURCE.json", guard.record)
    return tree


def prepare_source(
    restored_root, producer_dir, result_sha, source_sha, destination, output, commands
):
    """No implicit overlay: new Linux support must already be in the producer HEAD."""
    restored_root, producer_dir = physical(restored_root), physical(producer_dir)
    destination, output = physical(destination), physical(output)
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("Producer source commit must be an exact Git SHA-1")
    if any(path.is_relative_to(restored_root) for path in (destination, output)):
        raise ValueError(
            "Qualification worktree and evidence must be outside the restored checkout"
        )
    if destination.exists() or commands.cwd != restored_root:
        raise ValueError(
            "Qualification worktree must be new and guard cwd must match restored source"
        )
    common, helper = trusted_common(commands, source_sha)
    guard = PortGuard(restored_root, output, commands)
    candidate, recipe = common.load_candidate(
        guard, producer_dir, result_sha, source_sha
    )
    common.verify_tree(guard, candidate, recipe)
    commands.run("git", ["diff", "--exit-code"], label="index-equals-working-source")
    for suffix, args in (
        ("untracked", ["--others", "--exclude-standard"]),
        ("ignored", ["--others", "--ignored", "--exclude-standard"]),
    ):
        if commands.text("git", ["ls-files", *args], label=f"original-{suffix}"):
            raise ValueError("Restored producer source contains extra compile inputs")
    commands.run(
        "git", ["cat-file", "-e", f"HEAD:{ENTRY}"], label="linux-entry-in-producer-head"
    )
    candidate_tree = replay_candidate_tree(
        commands, producer_dir, candidate, source_sha, output
    )
    original_common = Path(
        commands.text(
            "git",
            ["rev-parse", "--path-format=absolute", "--git-common-dir"],
            label="original-git-common",
        )
    ).resolve(strict=True)
    objects = physical(original_common / "objects")
    if not objects.is_dir() or "\n" in str(objects):
        raise ValueError("Original object database is not a canonical local authority")
    authority = output / "qualification-git"
    commands.run(
        "git",
        ["init", "--bare", "--template=", str(authority)],
        label="private-git-authority",
    )
    # Only immutable Git objects are shared, never the original config, credentials,
    # hooks or remote authentication. The private bare repository has no remotes.
    write_bytes(authority / "objects/info/alternates", (str(objects) + "\n").encode())
    timestamp = datetime.now(timezone.utc).isoformat()
    commit_environment = {
        "GIT_AUTHOR_NAME": "Hepta qualification",
        "GIT_AUTHOR_EMAIL": "qualification@invalid",
        "GIT_COMMITTER_NAME": "Hepta qualification",
        "GIT_COMMITTER_EMAIL": "qualification@invalid",
        "GIT_AUTHOR_DATE": timestamp,
        "GIT_COMMITTER_DATE": timestamp,
    }
    _, commit_output = commands.run(
        "git",
        [f"--git-dir={authority}", "commit-tree", candidate_tree, "-p", source_sha],
        label="qualification-only-commit",
        environment=commit_environment,
        input_bytes=(
            f"Linux Synapse qualification only\n\nProducer RESULT sha256: {result_sha}\n"
        ).encode(),
    )
    commit = commit_output.read_text().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Qualification commit-tree returned an invalid identity")
    commands.run(
        "git",
        [
            f"--git-dir={authority}",
            "worktree",
            "add",
            "--detach",
            str(destination),
            commit,
        ],
        label="independent-qualification-worktree",
    )
    qualified = Commands(
        output / "source-final-commands",
        commands.tools,
        commands.environment,
        destination,
    )
    git_clean(qualified)
    if (
        qualified.text("git", ["rev-parse", "HEAD^{tree}"], label="qualification-tree")
        != candidate_tree
    ):
        raise ValueError(
            "Qualification-only commit did not preserve the exact candidate tree"
        )
    if (
        commands.text("git", ["rev-parse", "HEAD"], label="original-head-after")
        != source_sha
    ):
        raise ValueError("Original restore worktree HEAD changed")
    common.verify_tree(guard, candidate, recipe)
    provenance = output / "producer"
    for name in ("RESULT.json", "candidate.patch", "source.patch", "recipe.json"):
        copy_file(producer_dir / name, provenance / name)
    seal = {
        "schema": "hepta.synapse.linux.source-seal.v1",
        "scope": "native-linux-arm64",
        "producer_source_commit": source_sha,
        "producer_result_sha256": result_sha,
        "producer_candidate_patch": describe(provenance / "candidate.patch"),
        "producer_source_patch": describe(provenance / "source.patch"),
        "producer_recipe_sha256": candidate["recipe_sha256"],
        "producer_helper": describe(helper),
        "candidate_tree": candidate_tree,
        "qualification_commit": commit,
        "qualification_tree": candidate_tree,
        "qualification_commit_timestamp": timestamp,
        "source_root": str(destination),
        "original_restored_root": str(restored_root),
        "original_head_unchanged": True,
        "private_git_authority": str(authority),
        "original_object_directory": str(objects),
        "original_git_config_mounted": False,
        "source_clean": True,
        "test_overlay": None,
        "promotion_allowed": False,
        "bound_files": {
            name: describe(destination / name)
            for name in (
                "codex-rs/Cargo.lock",
                "MODULE.bazel.lock",
                "codex-rs/Cargo.toml",
                "justfile",
                "scripts/run-nextest.py",
                "codex-rs/.config/nextest.toml",
                ENTRY,
                "codex-rs/hepta-matrixd/tests/real_synapse_e2e.rs",
                "codex-rs/hepta-matrixd/tests/fixtures/run-hermetic-synapse.sh",
                "codex-rs/hepta-matrixd/tests/fixtures/synapse-loopback-proxy.py",
            )
        },
    }
    write_json(output / "SOURCE_SEAL.json", seal)
    return seal
