#!/usr/bin/env python3
"""Generate a local-only cognitive.read repair proposal beside qualification evidence.

This helper never updates a ref, pushes, edits a pull request, changes a feature
flag, or makes a qualification/release claim. It operates in a detached temporary
worktree and records a reviewable patch plus complete changed-file payloads.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import IO


def _git(root: Path, *args: str, env: dict[str, str]) -> str:
    return subprocess.check_output(
        ["git", "--literal-pathspecs", *args],
        cwd=root,
        env=env,
        text=True,
    ).strip()


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _run(argv: list[str], *, cwd: Path, env: dict[str, str], log: IO[str]) -> None:
    log.write(json.dumps(argv) + "\n")
    log.flush()
    subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
        check=True,
    )


def _credential_config(root: Path, env: dict[str, str]) -> list[str]:
    result = subprocess.run(
        [
            "git",
            "config",
            "--local",
            "--get-regexp",
            r"http\..*extraheader|credential\.|includeif\..*credentials",
        ],
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def _repair_durable_handoff_authoring(
    worktree: Path,
    *,
    env: dict[str, str],
    log: IO[str],
) -> str:
    """Make the reviewed NativeDispatch authoring transform indentation-safe.

    This patches only the authoring helper inside the detached proposal worktree,
    commits the helper fix normally, and leaves production source untouched until
    the ordinary durable-handoff authoring step runs from that exact commit.
    """

    path = worktree / "scripts" / "apply-cognitive-read-durable-handoff.py"
    body = path.read_text(encoding="utf-8")
    old_insert = '''    replace_once(
        NATIVE_APP,
        """            owner_context_digest,
            codex_payload_digest:""",
        """            owner_context_digest,
            cognitive_read_request_id: None,
            codex_payload_digest:""",
    )
'''
    old_bind = '''    replace_once(
        NATIVE_APP,
        "            cognitive_read_request_id: None,\\n",
        """            cognitive_read_request_id: context
                .as_ref()
                .map(CognitiveContextPreparation::request_id),
""",
    )
'''
    new_bind = '''    body = NATIVE_APP.read_text()
    pending = re.compile(
        r"(?m)^([ \\t]*)owner_context_digest,\\n"
        r"\\1codex_payload_digest:"
    )
    applied = re.compile(
        r"(?m)^([ \\t]*)owner_context_digest,\\n"
        r"\\1cognitive_read_request_id: context\\n"
        r"\\1    \\.as_ref\\(\\)\\n"
        r"\\1    \\.map\\(CognitiveContextPreparation::request_id\\),\\n"
        r"\\1codex_payload_digest:"
    )

    def bind_request_id(match: re.Match[str]) -> str:
        indent = match.group(1)
        return (
            f"{indent}owner_context_digest,\\n"
            f"{indent}cognitive_read_request_id: context\\n"
            f"{indent}    .as_ref()\\n"
            f"{indent}    .map(CognitiveContextPreparation::request_id),\\n"
            f"{indent}codex_payload_digest:"
        )

    next_body, count = pending.subn(bind_request_id, body)
    if count == 1:
        NATIVE_APP.write_text(next_body)
    elif count == 0 and len(applied.findall(body)) == 1:
        pass
    else:
        raise ValueError(
            "normal native dispatch request binding is absent or non-unique: "
            f"pending={count}, applied={len(applied.findall(body))}"
        )
'''
    if old_insert not in body or old_bind not in body:
        if new_bind in body and body.count(new_bind) == 1:
            return _git(worktree, "rev-parse", "HEAD", env=env)
        raise RuntimeError("durable handoff authoring source shape drift")
    body = body.replace(old_insert, new_bind, 1).replace(old_bind, "", 1)
    path.write_text(body, encoding="utf-8")
    _run(
        ["python3", "-m", "py_compile", str(path.relative_to(worktree))],
        cwd=worktree,
        env=env,
        log=log,
    )
    _run(["git", "diff", "--check"], cwd=worktree, env=env, log=log)
    _run(
        ["git", "add", "--", str(path.relative_to(worktree))],
        cwd=worktree,
        env=env,
        log=log,
    )
    _run(
        [
            "git",
            "commit",
            "-m",
            "fix(cognitive.read): make durable handoff authoring indentation-safe",
        ],
        cwd=worktree,
        env=env,
        log=log,
    )
    if _git(worktree, "status", "--porcelain", env=env):
        raise RuntimeError("durable handoff authoring fix left a dirty worktree")
    return _git(worktree, "rev-parse", "HEAD", env=env)


def _capture_committed_proposal(
    worktree: Path,
    proposal: Path,
    files_root: Path,
    candidate: str,
    prepared_head: str,
    *,
    env: dict[str, str],
) -> tuple[list[str], list[str]]:
    patch = subprocess.check_output(
        ["git", "diff", "--binary", candidate, prepared_head],
        cwd=worktree,
        env=env,
    )
    (proposal / "source.patch").write_bytes(patch)
    changed_text = subprocess.check_output(
        ["git", "diff", "--name-status", candidate, prepared_head],
        cwd=worktree,
        env=env,
        text=True,
    )
    (proposal / "changed-files.txt").write_text(changed_text)
    commits = subprocess.check_output(
        ["git", "log", "--format=fuller", f"{candidate}..{prepared_head}"],
        cwd=worktree,
        env=env,
        text=True,
    )
    (proposal / "commits.txt").write_text(commits)

    changed = subprocess.check_output(
        ["git", "diff", "--name-only", "-z", candidate, prepared_head],
        cwd=worktree,
        env=env,
    ).decode().split("\0")
    copied: list[str] = []
    deleted: list[str] = []
    for item in changed:
        if not item:
            continue
        path = worktree / item
        if path.is_file():
            destination = files_root / item
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            copied.append(item)
        else:
            deleted.append(item)
    return copied, deleted


def generate_source_proposal(root: Path, evidence: Path, candidate: str) -> dict[str, object]:
    """Return non-authoritative proposal metadata and write proposal files.

    Proposal generation is deliberately not a qualification gate. A failure is
    recorded in its own manifest but cannot be interpreted as source acceptance
    or rejection.
    """

    proposal = evidence / "source-proposal"
    files_root = proposal / "files"
    proposal.mkdir(parents=True, exist_ok=False)
    files_root.mkdir()
    log_path = proposal / "generation.log"
    manifest_path = proposal / "manifest.json"

    result: dict[str, object] = {
        "schema": "hepta.cognitive.read.local-source-proposal.v1",
        "kind": "local-repair-proposal",
        "qualification": False,
        "source_sha": candidate,
        "status": "failed",
        "activation": False,
        "production_implementation": False,
        "independent_acceptance": False,
        "release": False,
        "claim_boundary": (
            "Mutable local repair proposal only; never qualification, acceptance, "
            "activation, promotion or release evidence."
        ),
    }

    if re.fullmatch(r"[0-9a-f]{40}", candidate) is None:
        result["error"] = "invalid source SHA"
        manifest_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return result

    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    env.update(
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="cognitive.read local source proposal",
        GIT_AUTHOR_EMAIL="cognitive-read-proposal@invalid.example",
        GIT_COMMITTER_NAME="cognitive.read local source proposal",
        GIT_COMMITTER_EMAIL="cognitive-read-proposal@invalid.example",
        PYTHONPATH=str(root / "scripts"),
        CARGO_TERM_COLOR="never",
        NO_COLOR="1",
        RUST_MIN_STACK="8388608",
    )
    temp_root = Path(os.environ.get("RUNNER_TEMP", str(evidence.parent)))
    worktree = temp_root / f"cognitive-read-source-proposal-{candidate[:12]}-{os.getpid()}"
    proposal_head: str | None = None

    try:
        if _git(root, "rev-parse", "HEAD", env=env) != candidate:
            raise RuntimeError("proposal source does not match exact candidate")
        if _git(root, "status", "--porcelain", "--untracked-files=no", env=env):
            raise RuntimeError("proposal source has tracked changes")
        credentials = _credential_config(root, env)
        if credentials:
            raise RuntimeError("repository credential configuration remained after checkout")
        if worktree.exists():
            shutil.rmtree(worktree)

        with log_path.open("w", encoding="utf-8") as log:
            _run(
                ["git", "worktree", "add", "--detach", str(worktree), candidate],
                cwd=root,
                env=env,
                log=log,
            )
            _run(
                [
                    "python3",
                    "scripts/run-cognitive-read-convergence-repair.py",
                    "--expected-sha",
                    candidate,
                ],
                cwd=worktree,
                env=env,
                log=log,
            )
            repaired_head = _git(worktree, "rev-parse", "HEAD", env=env)
            proposal_head = repaired_head
            authoring_head = _repair_durable_handoff_authoring(
                worktree,
                env=env,
                log=log,
            )
            proposal_head = authoring_head
            _run(
                [
                    "python3",
                    "scripts/prepare-cognitive-read-durable-handoff.py",
                    "--expected-sha",
                    authoring_head,
                ],
                cwd=worktree,
                env=env,
                log=log,
            )
            prepared_head = _git(worktree, "rev-parse", "HEAD", env=env)
            proposal_head = prepared_head
            _run(
                [
                    "cargo",
                    "fmt",
                    "--manifest-path",
                    "codex-rs/Cargo.toml",
                    "--all",
                    "--",
                    "--check",
                ],
                cwd=worktree,
                env=env,
                log=log,
            )
            if _git(worktree, "status", "--porcelain", env=env):
                raise RuntimeError("repair proposal left an uncommitted worktree")

        copied, deleted = _capture_committed_proposal(
            worktree,
            proposal,
            files_root,
            candidate,
            prepared_head,
            env=env,
        )
        lock = worktree / "codex-rs" / "Cargo.lock"
        result.update(
            status="generated",
            source_tree=_git(worktree, "rev-parse", f"{candidate}^{{tree}}", env=env),
            repaired_sha=repaired_head,
            authoring_sha=authoring_head,
            prepared_sha=prepared_head,
            prepared_tree=_git(worktree, "rev-parse", f"{prepared_head}^{{tree}}", env=env),
            cargo_lock_sha256=_digest(lock),
            copied_files=copied,
            deleted_files=deleted,
            source_patch_sha256=_digest(proposal / "source.patch"),
            toolchain={
                "rustc": subprocess.check_output(
                    ["rustc", "--version"], cwd=worktree, env=env, text=True
                ).strip(),
                "cargo": subprocess.check_output(
                    ["cargo", "--version"], cwd=worktree, env=env, text=True
                ).strip(),
            },
        )
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        result["error"] = f"{type(error).__name__}: {error}"
        with log_path.open("a", encoding="utf-8") as log:
            log.write(result["error"] + "\n")
        if proposal_head is not None and worktree.is_dir():
            try:
                copied, deleted = _capture_committed_proposal(
                    worktree,
                    proposal,
                    files_root,
                    candidate,
                    proposal_head,
                    env=env,
                )
                result.update(
                    status="partial",
                    partial_sha=proposal_head,
                    partial_tree=_git(
                        worktree,
                        "rev-parse",
                        f"{proposal_head}^{{tree}}",
                        env=env,
                    ),
                    copied_files=copied,
                    deleted_files=deleted,
                    source_patch_sha256=_digest(proposal / "source.patch"),
                )
                dirty = _git(worktree, "status", "--porcelain", env=env)
                if dirty:
                    (proposal / "failed-working-tree-status.txt").write_text(
                        dirty + "\n"
                    )
                    (proposal / "failed-working-tree.patch").write_bytes(
                        subprocess.check_output(
                            ["git", "diff", "--binary", "HEAD", "--"],
                            cwd=worktree,
                            env=env,
                        )
                    )
            except (OSError, RuntimeError, subprocess.CalledProcessError) as capture_error:
                result["capture_error"] = (
                    f"{type(capture_error).__name__}: {capture_error}"
                )
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree)],
            cwd=root,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if worktree.exists():
            shutil.rmtree(worktree, ignore_errors=True)

    manifest_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result
