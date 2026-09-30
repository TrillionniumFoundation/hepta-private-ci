"""Bounded, read-only qualification evidence checks; never deployment authority.

Git object checks bind source/tested trees. Runner metadata checks establish
consistency, not remote attestation; the trusted workflow must require job success.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

MAX_EVIDENCE_BYTES = 2 * 1024 * 1024
PLATFORMS = {
    "linux-x86_64": ("Linux", "X64", "x86_64-unknown-linux-gnu"),
    "linux-arm64": ("Linux", "ARM64", "aarch64-unknown-linux-gnu"),
    "macos-arm64": ("macOS", "ARM64", "aarch64-apple-darwin"),
}


def canonical(value):
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def read_json(path):
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate evidence field")
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError("nonfinite evidence value")

    with path.open("rb") as stream:
        raw = stream.read(MAX_EVIDENCE_BYTES + 1)
    if len(raw) > MAX_EVIDENCE_BYTES:
        raise ValueError("evidence exceeds byte limit")
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
    if not isinstance(value, dict):
        raise ValueError("evidence must contain an object")
    return value


def publish(path, value):
    encoded = canonical(value)
    if len(encoded) > MAX_EVIDENCE_BYTES:
        raise ValueError("evidence exceeds byte limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def git(root, *args, input=None, env=None):
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    if env:
        clean_env.update(env)
    return subprocess.check_output(
        [
            "git",
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=root,
        env=clean_env,
        input=input,
        text=True,
        stderr=subprocess.PIPE,
    ).strip()


def git_blob(root, revision, path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.check_output(
        ["git", "--no-replace-objects", "show", f"{revision}:{path}"],
        cwd=root,
        env=env,
        stderr=subprocess.PIPE,
    )


def exact_sha(value):
    return (
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{40}", value) is not None
        and value != "0" * 40
    )


def candidate(root, source, base):
    if not all(exact_sha(value) for value in (source, base)):
        raise ValueError("source and base must be exact commit identities")
    for identity in (source, base):
        if git(root, "cat-file", "-t", identity) != "commit":
            raise ValueError("candidate identity must resolve to a commit")
    source_tree = git(root, "rev-parse", source + "^{tree}")
    merged_tree = git(root, "merge-tree", "--write-tree", base, source)
    merge_sha = git(
        root,
        "commit-tree",
        merged_tree,
        "-p",
        base,
        "-p",
        source,
        input="Qualification only; no selection or release\n",
        env={
            "GIT_AUTHOR_NAME": "hepta-qualification",
            "GIT_COMMITTER_NAME": "hepta-qualification",
            "GIT_AUTHOR_EMAIL": "qualification@invalid",
            "GIT_COMMITTER_EMAIL": "qualification@invalid",
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
        },
    )
    return {
        "source-head": (source, source_tree),
        "synthetic-merge": (merge_sha, merged_tree),
    }


def clean_checkout(root, tested_sha, tested_tree):
    if (
        git(root, "rev-parse", "HEAD") != tested_sha
        or git(root, "rev-parse", "HEAD^{tree}") != tested_tree
    ):
        raise ValueError("checkout differs from tested commit/tree")
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("qualification checkout must remain fully clean")


def actual_rust(root):
    raw = subprocess.check_output(["rustc", "-Vv"], cwd=root / "codex-rs", text=True)
    fields = dict(line.split(": ", 1) for line in raw.splitlines() if ": " in line)
    return {"release": fields["release"], "host": fields["host"]}


def check_record(spec, evidence, candidate_objects, context):
    errors = []
    gate_id = evidence.get("gate")
    gates = {item["id"]: item for item in spec["qualification"]["requiredGates"]}
    if not isinstance(gate_id, str) or gate_id not in gates:
        return ["unknown qualification gate"]
    gate = gates[gate_id]
    if evidence.get("module") != spec["module"]:
        errors.append("module differs from qualification owner")
    if any(
        not exact_sha(evidence.get(key))
        for key in ("sourceSha", "baseSha", "testedSha", "testedTree")
    ):
        errors.append("missing or invalid candidate identity")
    if (
        evidence.get("sourceSha") != context["sourceSha"]
        or evidence.get("baseSha") != context["baseSha"]
    ):
        errors.append("candidate differs from requested source/base")
    if (evidence.get("testedSha"), evidence.get("testedTree")) != candidate_objects[
        gate["lane"]
    ]:
        errors.append("tested commit/tree differs from exact lane")
    for key in ("lane", "platform"):
        if evidence.get(key) != gate[key]:
            errors.append(key + " differs from gate")
    for field in ("toolchain", "workflow", "runner", "bindings", "claimBoundary"):
        if not isinstance(evidence.get(field), dict):
            errors.append(field + " must contain an object")
    if errors and any(
        not isinstance(evidence.get(field), dict)
        for field in ("toolchain", "workflow", "runner", "bindings", "claimBoundary")
    ):
        return errors
    toolchain = evidence["toolchain"]
    if (
        toolchain.get("class") != gate["toolchain"]
        or toolchain.get("version") != spec["toolchains"][gate["toolchain"]]
    ):
        errors.append("toolchain differs from gate")
    workflow = evidence["workflow"]
    if (
        context["repository"] != spec["qualification"]["repository"]
        or context["name"] != spec["qualification"]["workflowName"]
    ):
        errors.append("workflow context differs from the canonical owner")
    for name in ("name", "repository", "runId", "runAttempt"):
        if workflow.get(name) != context[name]:
            errors.append("workflow " + name + " differs from current run")
    for name in ("runId", "runAttempt"):
        if (
            not isinstance(workflow.get(name), str)
            or re.fullmatch(r"[1-9][0-9]*", workflow[name]) is None
        ):
            errors.append("workflow " + name + " must be a positive decimal identity")
    if workflow.get("job") != gate_id:
        errors.append("workflow job differs from gate")
    runner = evidence["runner"]
    system, architecture, target = PLATFORMS[gate["platform"]]
    if (runner.get("os"), runner.get("arch"), runner.get("targetTriple")) != (
        system,
        architecture,
        target,
    ):
        errors.append("runner platform or target differs from gate")
    if evidence.get("observedRust") != {
        "release": spec["toolchains"][gate["toolchain"]],
        "host": target,
    }:
        errors.append("observed compiler differs from gate")
    for name in ("name", "image", "environment", "kernel", "python"):
        if (
            not isinstance(runner.get(name), str)
            or not runner[name].strip()
            or runner[name] == "unknown"
        ):
            errors.append("missing runner " + name)
    fingerprint = {k: v for k, v in runner.items() if k != "fingerprintSha256"}
    if (
        runner.get("fingerprintSha256")
        != hashlib.sha256(canonical(fingerprint)).hexdigest()
    ):
        errors.append("runner fingerprint differs from recorded metadata")
    expected_claim = {
        "qualificationGatePassed": evidence.get("result") == "success",
        "productionActivation": False,
        "release": False,
    }
    if evidence["claimBoundary"] != expected_claim or any(
        type(value) is not bool for value in evidence["claimBoundary"].values()
    ):
        errors.append("qualification claim boundary is inconsistent")
    return errors
