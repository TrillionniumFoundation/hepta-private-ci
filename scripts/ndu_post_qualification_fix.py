#!/usr/bin/env python3
"""Run scoped Clippy after a sealed consumer pass, retaining both source identities."""

import argparse
import os
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True

from ndu_port_candidate_common import LOCKS
from ndu_port_candidate_common import POLICIES
from ndu_port_candidate_common import Recorder
from ndu_port_candidate_common import candidate_source_mode
from ndu_port_candidate_common import check_toolchain
from ndu_port_candidate_common import checksum
from ndu_port_candidate_common import copy_files
from ndu_port_candidate_common import describe
from ndu_port_candidate_common import load_candidate
from ndu_port_candidate_common import relative_path
from ndu_port_candidate_common import verify_tree
from ndu_port_candidate_common import verify_vendor
from ndu_post_qualification_evidence import GROUPS
from ndu_post_qualification_evidence import require
from ndu_post_qualification_evidence import validate_tests


def text(runner, label, command, environment=None):
    runner.run(label, command, environment=environment)
    return (runner.output / runner.record["commands"][-1]["log"]).read_text().strip()


def index_path(runner):
    name = text(runner, "index-path", ["git", "rev-parse", "--git-path", "index"])
    path = Path(name)
    return path if path.is_absolute() else runner.root / path


def private_tree(runner, label, index, *, stage=False):
    environment = {"GIT_INDEX_FILE": str(index)}
    if stage:
        runner.run(
            label + "-stage", ["git", "add", "-u", "--", "."], environment=environment
        )
    return text(runner, label, ["git", "write-tree"], environment)


def index_entries(runner, label, index):
    output = text(
        runner,
        label,
        ["git", "ls-files", "--stage", "-z"],
        {"GIT_INDEX_FILE": str(index)},
    )
    result = {}
    for row in output.split("\0"):
        if row:
            header, name = row.split("\t", 1)
            mode, blob, stage = header.split()
            require(stage == "0", "Unmerged index is not eligible")
            relative_path(name)
            result[name] = {"mode": mode, "git_blob": blob}
    return result


def freeze_before(runner, record, artifact, group):
    require(
        not text(runner, "before-unstaged", ["git", "diff", "--name-only", "-z"]),
        "Candidate worktree must equal its staged index",
    )
    require(
        not text(runner, "before-untracked", ["git", "ls-files", "--others", "-z"]),
        "Candidate has extra files, including ignored files",
    )
    original = index_path(runner)
    before = runner.output / "before.index"
    shutil.copyfile(original, before)
    original_sha = checksum(original)
    before_tree = private_tree(runner, "before-tree", before)
    replay = runner.output / "replayed.index"
    environment = {"GIT_INDEX_FILE": str(replay)}
    runner.run(
        "replay-base",
        ["git", "read-tree", record["source_commit"]],
        environment=environment,
    )
    if candidate_source_mode(record) == "patched":
        runner.run(
            "replay-candidate",
            ["git", "apply", "--cached", str(artifact / "candidate.patch")],
            environment=environment,
        )
    elif (artifact / "candidate.patch").read_bytes() != b"":
        raise ValueError("Integrated replay requires an exactly empty delta")
    require(
        private_tree(runner, "replayed-tree", replay) == before_tree,
        "Staged contents or modes differ from the complete sealed candidate patch",
    )
    entries = index_entries(runner, "before-index-entries", before)
    allowed = {
        name
        for name in entries
        if name.endswith(".rs") and name.startswith(GROUPS[group]["directories"])
    }
    require(allowed, "Scoped first-party Rust source set is empty")
    sources = describe(runner.root, allowed)
    copy_files(runner.root, runner.output / "before-source", sources)
    require(
        checksum(original) == original_sha, "Source index changed during preparation"
    )
    runner.record.update(
        before_tree=before_tree,
        before_index_sha256=original_sha,
        allowed_fix_paths=sorted(allowed),
        before_source=sources,
    )
    return original, before, entries, allowed


def bind_tools(runner):
    check_toolchain(runner, "1.96.0")
    tools = {}
    for name, prefix in (
        ("cargo", "cargo 1.96.0 "),
        ("cargo-clippy", "clippy 0.1.96 "),
        ("clippy-driver", "clippy 0.1.96 "),
    ):
        path = Path(
            text(
                runner,
                "bound-" + name,
                ["rustup", "which", "--toolchain", "1.96.0", name],
            )
        )
        require(
            path.is_absolute() and path.is_file() and not path.is_symlink(),
            "Expected a real toolchain executable",
        )
        version = text(runner, name + "-version", [str(path), "--version"])
        require(
            version.startswith(prefix),
            f"Actual {name} version is not the pinned 1.96 component",
        )
        tools[name] = {"path": str(path), "sha256": checksum(path), "version": version}
    rustc = runner.record["cargo_compiler"]
    tools["rustc"] = {**rustc, "version": runner.record["rustc_verbose"]}
    directories = {Path(item["path"]).parent for item in tools.values()}
    require(
        len(directories) == 1,
        "Cargo, Clippy and rustc must come from the same toolchain",
    )
    just = Path(shutil.which("just") or "")
    require(
        just.is_absolute() and just.is_file(), "The actual just executable is missing"
    )
    tools["just"] = {
        "path": str(just.resolve()),
        "sha256": checksum(just),
        "version": text(runner, "bound-just-version", [str(just), "--version"]),
    }
    require(
        not any(os.environ.get(key) for key in ("CLIPPY_CONF_DIR", "CLIPPY_ARGS")),
        "Inherited Clippy overrides are not approved",
    )
    runner.env["PATH"] = str(next(iter(directories))) + os.pathsep + os.environ["PATH"]
    runner.record["tools"] = tools
    return str(just)


def capture_after(runner, frozen, record, recipe, test_path, evidence):
    original, before, entries, allowed = frozen
    after = runner.output / "after.index"
    shutil.copyfile(before, after)
    after_tree = private_tree(runner, "after-tree", after, stage=True)
    patch = runner.output / "fix.patch"
    environment = {"GIT_INDEX_FILE": str(before)}
    runner.run(
        "export-fix-patch",
        [
            "git",
            "diff",
            "--binary",
            "--full-index",
            "--no-renames",
            f"--output={patch}",
        ],
        environment=environment,
    )
    changed = {
        name
        for name in text(
            runner, "fix-paths", ["git", "diff", "--name-only", "-z"], environment
        ).split("\0")
        if name
    }
    after_entries = index_entries(runner, "after-index-entries", after)
    runner.record.update(
        after_tree=after_tree,
        fix_patch=describe(runner.output, ("fix.patch",))["fix.patch"],
        changed_paths=sorted(changed),
        source_changed=bool(changed),
        prior_behavioral_qualification_applies_to_after_source=False,
    )
    source = describe(runner.root, changed, allow_missing=True)
    copy_files(runner.root, runner.output / "after-source", source)
    runner.record["after_source"] = source
    runner.save()
    require(
        checksum(original) == runner.record["before_index_sha256"],
        "Clippy changed the original Git index",
    )
    require(
        not text(runner, "after-untracked", ["git", "ls-files", "--others", "-z"]),
        "Clippy created untracked or ignored files",
    )
    require(
        changed <= allowed,
        "Clippy changed paths outside the exact first-party Rust scope",
    )
    require(
        set(entries) == set(after_entries)
        and all(
            entries[name]["mode"] == after_entries[name]["mode"] for name in entries
        ),
        "Clippy changed file membership or executable modes",
    )
    require(
        describe(runner.root, LOCKS) == {name: record["files"][name] for name in LOCKS},
        "Clippy changed a lock",
    )
    require(
        describe(runner.root, POLICIES) == record["policy_inputs"],
        "Clippy changed original dependency policy",
    )
    verify_vendor(runner.root, recipe, source_mode=candidate_source_mode(record))
    require(
        describe(test_path.parent, evidence) == evidence,
        "Clippy changed original test evidence",
    )
    require(
        text(runner, "after-head", ["git", "rev-parse", "HEAD"])
        == record["source_commit"],
        "Clippy changed HEAD",
    )
    for tool in runner.record.get("tools", {}).values():
        require(checksum(Path(tool["path"])) == tool["sha256"], "A bound tool changed")
    if not changed:
        require(
            after_tree == runner.record["before_tree"], "Empty diff changed source tree"
        )
        verify_tree(runner, record, recipe)
    runner.record["protected_inputs_unchanged"] = True


def execute(args):
    runner = Recorder(args.repository, args.output, "post-qualification-clippy")
    runner.env["GIT_OPTIONAL_LOCKS"] = "0"
    runner.record.update(
        schema="hepta.ci.post-qualification-clippy.v1",
        group=args.group,
        prior_behavioral_qualification_applies_to_after_source=False,
        protected_inputs_unchanged=False,
    )
    frozen = None
    success = False
    try:
        require(args.group in GROUPS, "Unsupported fixed Clippy group")
        target = Path(os.environ.get("CARGO_TARGET_DIR", ""))
        require(
            target.is_absolute()
            and target.is_dir()
            and not target.resolve().is_relative_to(runner.root),
            "Reuse setup-ci's existing absolute external CARGO_TARGET_DIR",
        )
        runner.record.update(
            cargo_target_directory=str(target.resolve()),
            target_directory_binding="Matrix phase verified; YAML uses the same workflow environment because the earlier workspace receipt does not record inherited target-dir.",
        )
        record, recipe = load_candidate(
            runner, args.candidate, args.expected_result_sha256, args.expected_source
        )
        verify_tree(runner, record, recipe)
        runner.record.update(
            source_commit=args.expected_source,
            candidate_result_sha256=args.expected_result_sha256,
            recipe_sha256=record["recipe_sha256"],
        )
        evidence = validate_tests(
            runner, args.test_result, args.group, record, args.expected_result_sha256
        )
        frozen = freeze_before(runner, record, args.candidate, args.group)
        just = bind_tools(runner)
        command = [just, "fix", "--locked", "--profile", "ci-test"]
        for package in GROUPS[args.group]["packages"]:
            command.extend(("-p", package))
        command.extend(GROUPS[args.group]["features"])
        runner.record["clippy_exit_code"] = runner.run(
            "scoped-clippy-fix", command, required=False
        )
        require(
            runner.record["clippy_exit_code"] == 0,
            "Scoped Clippy failed; partial edits are retained",
        )
        success = True
    except Exception as error:
        runner.record.update(error_type=type(error).__name__, error=str(error))
    finally:
        if frozen is not None:
            try:
                capture_after(
                    runner, frozen, record, recipe, args.test_result, evidence
                )
            except Exception as error:
                success = False
                runner.record.update(
                    after_capture_error_type=type(error).__name__,
                    after_capture_error=str(error),
                )
        if success:
            changed = runner.record["source_changed"]
            runner.record.update(
                status="clippy_passed_review_required"
                if changed
                else "clippy_passed_source_unchanged",
                prior_behavioral_qualification_applies_to_after_source=not changed,
            )
        else:
            runner.record["status"] = "failed"
        runner.record["qualification"] = (
            "Original consumer results remain bound to before_tree only. A nonempty fix.patch requires review and separate final-source qualification; Clippy is not a behavioral test."
        )
        runner.save()
    return 0 if success else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--expected-result-sha256", required=True)
    parser.add_argument("--group", choices=GROUPS, required=True)
    parser.add_argument("--test-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return execute(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
