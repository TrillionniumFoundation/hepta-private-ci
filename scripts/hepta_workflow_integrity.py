"""Read a bounded workflow subset and validate real checkout/reusable jobs.

This is deliberately not a general YAML interpreter. Unsupported YAML constructs
fail closed; shell block scalars remain opaque rather than supplying policy keys.
"""

import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Callable

MAX_BYTES = 256 * 1024
MAX_WORKFLOWS = 32
MAX_DEPTH = 8
LOCAL_WORKFLOW = re.compile(r"\./(\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml)")
Violation = tuple[str, str, int, str]
# Reviewed GitHub workflow permissions; newly introduced scopes need review.
# https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#permissions
READ_ONLY_PERMISSIONS = frozenset(
    {
        "actions",
        "artifact-metadata",
        "attestations",
        "checks",
        "code-quality",
        "contents",
        "deployments",
        "discussions",
        "issues",
        "packages",
        "pages",
        "pull-requests",
        "security-events",
        "statuses",
        "vulnerability-alerts",
    }
)


def _read_only_permissions(value: object) -> bool:
    return isinstance(value, dict) and all(
        key in READ_ONLY_PERMISSIONS | {"id-token"}
        and isinstance(access, str)
        and (access == "none" or (access == "read" and key in READ_ONLY_PERMISSIONS))
        for key, access in value.items()
    )


def git_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
    )
    return environment


def _plain_line(line: str) -> str:
    quote = None
    escaped = False
    for index, character in enumerate(line):
        if escaped:
            escaped = False
        elif character == "\\" and quote == '"':
            escaped = True
        elif character in "\"'":
            quote = (
                None if quote == character else character if quote is None else quote
            )
        elif (
            character == "#"
            and quote is None
            and (not index or line[index - 1].isspace())
        ):
            return line[:index].rstrip()
    return line.rstrip()


def _scalar(value: str) -> str:
    if value.startswith(("&", "*", "!", "{")):
        raise ValueError("unsupported YAML scalar or alias")
    if value.startswith(("'", '"')):
        if len(value) < 2 or value[-1] != value[0]:
            raise ValueError("unsupported multiline quoted scalar")
        return value[1:-1]
    return value


def _workflow(text: str) -> dict:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("workflow exceeds bounded input")
    source = text.splitlines()
    lines = []
    index = 0
    while index < len(source):
        number = index + 1
        line = _plain_line(source[index])
        index += 1
        if not line.strip():
            continue
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise ValueError("tab indentation is unsupported")
        indent = len(line) - len(line.lstrip())
        body = line.strip()
        block = re.fullmatch(r"(?:-\s+)?[A-Za-z_][A-Za-z0-9_-]*:\s*([|>][-+]?)", body)
        if block:
            # Consume executable/prose scalars at their real indentation. Their
            # text cannot masquerade as permissions, uses or checkout options.
            while index < len(source):
                child = source[index]
                if child.strip() and len(child) - len(child.lstrip()) <= indent:
                    break
                index += 1
            body = body[: body.rfind(":") + 1] + " __block_scalar__"
        lines.append((indent, body, number))
    if not lines or len(lines) > 12000:
        raise ValueError("empty or oversized workflow structure")

    def entry(body: str) -> tuple[str, str]:
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_-]*):(?:\s+(.*))?", body)
        if not match:
            raise ValueError("unsupported YAML mapping or merge key")
        return match[1], match[2] or ""

    def block(index: int, indent: int, depth: int):
        if depth > 32:
            raise ValueError("workflow structure nesting limit")
        sequence = lines[index][1].startswith("- ")
        result = [] if sequence else {}
        while index < len(lines) and lines[index][0] == indent:
            _, body, _ = lines[index]
            index += 1
            if sequence:
                if not body.startswith("- "):
                    raise ValueError("mixed YAML sequence and mapping")
                body = body[2:]
                if ":" not in body:
                    result.append(_scalar(body))
                    continue
                key, value = entry(body)
                row = {}
            else:
                key, value = entry(body)
                row = result
                if key in row:
                    raise ValueError("duplicate workflow mapping key")
            if value:
                row[key] = _scalar(value)
            elif index < len(lines) and lines[index][0] > indent:
                row[key], index = block(index, lines[index][0], depth + 1)
            else:
                row[key] = {}
            if sequence:
                if index < len(lines) and lines[index][0] > indent:
                    other, index = block(index, lines[index][0], depth + 1)
                    if not isinstance(other, dict) or set(row) & set(other):
                        raise ValueError("invalid or duplicate workflow step key")
                    row.update(other)
                result.append(row)
            if index < len(lines) and lines[index][0] > indent:
                raise ValueError("unsupported workflow indentation")
        return result, index

    parsed, end = block(0, 0, 0)
    if end != len(lines) or not isinstance(parsed, dict):
        raise ValueError("workflow must be one top-level mapping")
    return parsed


def _read_workflow(root: Path, path: str) -> str:
    target = root
    for component in Path(path).parts:
        target /= component
        metadata = target.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("reusable workflow link rejected")
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_size > MAX_BYTES
    ):
        raise ValueError("reusable workflow must be a bounded regular file")

    def identity(value):
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_nlink,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
            value.st_uid,
            value.st_gid,
        )

    fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or identity(opened) != identity(metadata):
            raise ValueError("reusable workflow changed before open")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(MAX_BYTES + 1)
        after = os.fstat(fd)
        named = target.lstat()
        if (
            len(raw) > MAX_BYTES
            or identity(opened) != identity(after)
            or identity(opened) != identity(named)
        ):
            raise ValueError("reusable workflow changed during read")
        return raw.decode("utf-8")
    finally:
        os.close(fd)


def _candidate_blob(root: Path, path: str, text: str, candidate: str):
    if not re.fullmatch(r"[a-f0-9]{40}", candidate):
        raise ValueError("immutable candidate commit required")
    tree = subprocess.check_output(
        [
            "git",
            "-C",
            str(root),
            "--literal-pathspecs",
            "-c",
            "core.fsmonitor=false",
            "ls-tree",
            "-z",
            candidate,
            "--",
            path,
        ],
        stderr=subprocess.DEVNULL,
        env=git_environment(),
    ).split(b"\0")
    if len(tree) != 2 or not tree[0]:
        raise ValueError("workflow is absent from immutable candidate")
    metadata, name = tree[0].decode("utf-8").split("\t", 1)
    mode, kind, blob = metadata.split()
    raw = text.encode("utf-8")
    actual = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
    if (
        name != path
        or mode not in {"100644", "100755"}
        or kind != "blob"
        or actual != blob
    ):
        raise ValueError("workflow differs from immutable candidate regular blob")


def workflow_violations(
    path: str,
    text: str,
    root: Path,
    inspect_text: Callable[[str, str], list[Violation]] | None = None,
    candidate: str | None = None,
) -> list[Violation]:
    """Validate this candidate's local call graph; no external refs are proof."""
    violations: list[Violation] = []
    observed: set[str] = set()
    if candidate is not None:
        try:
            if not re.fullmatch(r"[a-f0-9]{40}", candidate):
                raise ValueError("immutable candidate commit required")
            kind = subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(root),
                    "-c",
                    "core.fsmonitor=false",
                    "cat-file",
                    "-t",
                    candidate,
                ],
                stderr=subprocess.DEVNULL,
                env=git_environment(),
            ).strip()
            if kind != b"commit":
                raise ValueError("immutable candidate object must be a commit")
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            return [(path, "invalid-local-reusable-workflow", 1, str(error))]

    def reject(path: str, rule: str, excerpt: str):
        violations.append((path, rule, 1, excerpt))

    def visit(path: str, text: str, stack: tuple[str, ...]):
        if path in stack or len(stack) >= MAX_DEPTH:
            reject(path, "reusable-workflow-cycle-or-depth", path)
            return
        if path in observed:
            return
        observed.add(path)
        if len(observed) > MAX_WORKFLOWS:
            reject(path, "reusable-workflow-count-limit", path)
            return
        if stack and inspect_text is not None:
            violations.extend(inspect_text(path, text))
        if candidate is not None:
            try:
                if not stack and _read_workflow(root, path) != text:
                    raise ValueError("caller differs from bounded working-tree capture")
                _candidate_blob(root, path, text, candidate)
            except (
                OSError,
                UnicodeError,
                ValueError,
                subprocess.CalledProcessError,
            ) as error:
                reject(path, "invalid-local-reusable-workflow", str(error))
                return
        try:
            document = _workflow(text)
        except ValueError as error:
            reject(path, "unsupported-workflow-structure", str(error))
            return
        permissions = document.get("permissions")
        if not isinstance(permissions, dict) or permissions.get("contents") != "read":
            reject(path, "missing-safe-workflow-token", "permissions.contents: read")
        if not _read_only_permissions(permissions):
            reject(
                path,
                "workflow-write-permission",
                "literal reviewed read/none permissions required",
            )
        triggers = document.get("on")
        if isinstance(triggers, dict):
            privileged = "pull_request_target" in triggers
        elif isinstance(triggers, str):
            if not re.fullmatch(r"[a-z][a-z0-9_]*", triggers):
                reject(
                    path,
                    "unsupported-workflow-structure",
                    "literal workflow trigger required",
                )
            privileged = triggers == "pull_request_target"
        elif isinstance(triggers, list):
            if not all(
                isinstance(trigger, str) and re.fullmatch(r"[a-z][a-z0-9_]*", trigger)
                for trigger in triggers
            ):
                reject(
                    path,
                    "unsupported-workflow-structure",
                    "literal workflow trigger sequence required",
                )
            privileged = "pull_request_target" in triggers
        elif triggers is None:
            # Historical policy self-test fixtures omit on; they grant no
            # authority and are not valid hosted workflow configurations.
            privileged = False
        else:
            reject(
                path, "unsupported-workflow-structure", "unsupported workflow triggers"
            )
            privileged = False
        if privileged:
            reject(
                path, "untrusted-privileged-trigger", "pull_request_target is forbidden"
            )
        jobs = document.get("jobs")
        if not isinstance(jobs, dict) or not jobs:
            reject(
                path, "unsupported-workflow-structure", "nonempty jobs mapping required"
            )
            return
        direct_jobs = 0
        checkouts = 0
        for job in jobs.values():
            if not isinstance(job, dict):
                reject(path, "unsupported-workflow-structure", "job mapping required")
                continue
            job_permissions = job.get("permissions", {})
            if not _read_only_permissions(job_permissions):
                reject(
                    path,
                    "workflow-write-permission",
                    "literal reviewed read/none job permissions required",
                )
            if "uses" in job:
                target = job["uses"]
                match = (
                    LOCAL_WORKFLOW.fullmatch(target)
                    if isinstance(target, str)
                    else None
                )
                if not match:
                    reject(path, "external-reusable-workflow", str(target))
                    continue
                if "steps" in job or "runs-on" in job:
                    reject(
                        path,
                        "unsupported-workflow-structure",
                        "reusable job also declares execution",
                    )
                    continue
                child = match[1]
                if child in (*stack, path) or len(stack) + 1 >= MAX_DEPTH:
                    reject(child, "reusable-workflow-cycle-or-depth", child)
                    continue
                if child not in observed and len(observed) >= MAX_WORKFLOWS:
                    reject(child, "reusable-workflow-count-limit", child)
                    return
                if child in observed:
                    continue
                try:
                    child_text = _read_workflow(root, child)
                    child_document = _workflow(child_text)
                    triggers = child_document.get("on")
                    if (
                        not isinstance(triggers, dict)
                        or "workflow_call" not in triggers
                    ):
                        raise ValueError("callee must declare workflow_call")
                except (
                    OSError,
                    UnicodeError,
                    ValueError,
                    subprocess.CalledProcessError,
                ) as error:
                    reject(child, "invalid-local-reusable-workflow", str(error))
                    continue
                visit(child, child_text, (*stack, path))
                continue
            direct_jobs += 1
            steps = job.get("steps")
            if not isinstance(steps, list):
                reject(
                    path,
                    "unsupported-workflow-structure",
                    "ordinary job steps required",
                )
                continue
            for step in steps:
                if not isinstance(step, dict):
                    reject(
                        path, "unsupported-workflow-structure", "step mapping required"
                    )
                    continue
                use = step.get("uses", "")
                if isinstance(use, str) and (
                    use == "actions/checkout" or use.startswith("actions/checkout@")
                ):
                    checkouts += 1
                    options = step.get("with")
                    if (
                        not isinstance(options, dict)
                        or options.get("persist-credentials") != "false"
                    ):
                        reject(
                            path,
                            "missing-safe-workflow-token",
                            "checkout.with.persist-credentials: false",
                        )
        if direct_jobs and not checkouts:
            reject(
                path,
                "missing-safe-workflow-token",
                "actual checkout with persist-credentials: false",
            )

    visit(path, text, ())
    return violations
