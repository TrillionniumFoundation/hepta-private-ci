#!/usr/bin/env python3
"""Publish only declared text evidence from the original model run.

This is an output filter after execution, not a model gate or payload store.
The original index retains hashes of omitted files; those hashes do not mean
that checkpoints were retained or made available for independent replay.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat

MAX_FILE_BYTES = 64 * 1024 * 1024  # Original CI command-log ceiling.
MAX_EXPORT_BYTES = 1024 * 1024 * 1024
ROOT_TEXT = {
    "chain-source.txt",
    "hepta-source.txt",
    "research-chain-source.txt",
    "observation-chain-source.txt",
    "rustc.txt",
    "bubblewrap-version.txt",
    "codex-binary.sha256",
    "code-mode-host-binary.sha256",
    "final-source-diff.patch",
}
ROOT_JSON = {
    "host.json",
    "model-target.json",
    "native-input.json",
    "native-socket-paths.json",
    "pip-install.json",
    "runtime-snapshot.json",
    "required-outcomes.json",
    "evidence-index.json",
}
COMMANDS = (
    "required-cli-build",
    "scoped-rust",
    "ordinary-native",
    "three-rounds-native",
    "descendant-execution",
    "answer-eos-research-execution",
    "material-download-controls",
    "descendant-boundary-controls",
    "research-boundary-controls",
    "metadata-export-controls",
    "observation-boundary-controls",
    "observation-owner-controls",
    "live-control-boundary-controls",
    "sandbox-host-capability",
)
ROUND = r"(?:n/p/round-[123]|descendant-diagnostics/round-[123]|answer-eos-research-v3)"
ROLES = r"(?:candidate|current-backbone|fresh-budget-matched-lora|budget-matched-full-tune|randomized-rank-matched-lora|actual-current-incumbent)"
STAGE_TEXT = r"(?:actual-receipt\.json|supervisor\.json|cost-events\.jsonl|process\.log|predictions\.json|artifact\.json|live-control-release-v1\.json)"
RULES = tuple(
    re.compile(pattern)
    for pattern in (
        r"(?:" + "|".join(COMMANDS) + r")\.json(?:\.[0-9a-f]{32}\.log)?",
        r"genesis/(?:parent-material|derivation|experiment-plan)\.json",
        r"n/(?:ordinary-initial-context-result|r/ordinary-reopen-result|p/loop-observations)\.json",
        r"n/(?:p/ordinary-[0-3]|r/(?:first|second)|ordinary-effects)/(?:ordinary-session-result|ordinary-runtime-stop|ordinary-failure)\.json",
        r"n/p/round-[123]\.(?:(?:launch|exit)\.json|(?:stdout|stderr)\.log)",
        r"descendant-diagnostics/campaign\.json",
        ROUND
        + r"/(?:assessment|abort|candidate-parent-material|evaluation-roster|experiment-plan|phase-outcomes|round-freeze)\.json",
        ROUND + r"/(?:train|evaluate)-" + ROLES + "/" + STAGE_TEXT,
        ROUND + r"/train-candidate/parent-step-(?:input|result)(?:-v[23])?\.json",
        r"n/p/round-[123]/observation-plan-v1\.json",
        r"n/p/round-[123]/control-execution-entry-v1\.json",
        r"n/p/round-[123]/(?:train|evaluate)-" + ROLES + r"-live-input\.json",
        r"n/p/round-[123]/train-candidate/parent-step-(?:input|result)-observed-v1\.json",
        ROUND + r"/train-candidate/execution/" + STAGE_TEXT,
    )
)
FORBIDDEN_JSON_KEYS = {
    "weights",
    "state_dict",
    "modules",
    "tensor_values",
    "tensor_bytes",
    "data_base64",
    "raw_bytes",
    "private_key",
    "secret_key",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def allowed(relative):
    path = PurePosixPath(relative)
    if (
        str(path) != relative
        or path.is_absolute()
        or any(part in (".", "..") or part.startswith(".") for part in path.parts)
        or "\\" in relative
    ):
        return False
    return relative in ROOT_TEXT | ROOT_JSON or any(
        rule.fullmatch(relative) for rule in RULES
    )


def metadata(value):
    if isinstance(value, dict):
        require(not FORBIDDEN_JSON_KEYS.intersection(value), "payload-bearing JSON key")
        for item in value.values():
            metadata(item)
    elif isinstance(value, list):
        for item in value:
            metadata(item)


def read_text(root, relative):
    """Read through held non-symlink directories; never follow an artifact link."""
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = PurePosixPath(relative).parts
        for part in parts[:-1]:
            following = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
            )
            os.close(directory)
            directory = following
        descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=directory
        )
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            require(
                stat.S_ISREG(before.st_mode) and before.st_size <= MAX_FILE_BYTES,
                "regular bounded evidence file required",
            )
            raw = stream.read(MAX_FILE_BYTES + 1)
            after = os.fstat(stream.fileno())
            require(
                len(raw) == before.st_size
                and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
                "evidence changed during read",
            )
    finally:
        os.close(directory)
    text = raw.decode("utf-8")
    require("\x00" not in text, "binary data in text evidence")
    if relative.endswith(".json"):
        metadata(json.loads(text, object_pairs_hook=unique))
    elif relative.endswith(".jsonl"):
        for line in text.splitlines():
            metadata(json.loads(line, object_pairs_hook=unique))
    elif relative.endswith(".patch"):
        require(
            "GIT binary patch" not in text, "binary source patch is not text evidence"
        )
    return raw


def export(root, output, source_sha):
    require(
        root.is_absolute() and root.resolve() == root and root.is_dir(),
        "absolute non-symlink evidence root required",
    )
    require(
        output.is_absolute()
        and output.parent.resolve() == output.parent
        and not output.is_relative_to(root)
        and not root.is_relative_to(output),
        "separate absolute metadata destination required",
    )
    require(re.fullmatch(r"[0-9a-f]{40}", source_sha), "exact source SHA required")
    index_raw = read_text(root, "evidence-index.json")
    index = json.loads(index_raw, object_pairs_hook=unique)
    require(
        set(index)
        == {
            "source",
            "chain",
            "research_chain",
            "answer_eos_research_outcome",
            "files",
            "product_qualification",
            "three_installed_upgrades_proven",
            "held_runtime_closure_proven",
        }
        and index["source"] == source_sha
        and isinstance(index["files"], dict),
        "original source-bound evidence index required",
    )
    require(
        all(
            index[key] is False
            for key in (
                "product_qualification",
                "three_installed_upgrades_proven",
                "held_runtime_closure_proven",
            )
        ),
        "output filter cannot issue qualification",
    )
    for relative, row in index["files"].items():
        require(
            isinstance(relative, str)
            and len(relative) <= 4096
            and set(row) == {"sha256", "bytes"}
            and type(row["bytes"]) is int
            and row["bytes"] >= 0
            and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]),
            "invalid original file hash entry",
        )
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    copied = {}
    total = 0
    try:
        candidates = {
            **index["files"],
            "evidence-index.json": {
                "bytes": len(index_raw),
                "sha256": hashlib.sha256(index_raw).hexdigest(),
            },
        }
        for relative, expected in sorted(candidates.items()):
            if not allowed(relative):
                continue
            raw = read_text(root, relative)
            digest = hashlib.sha256(raw).hexdigest()
            require(
                {"bytes": len(raw), "sha256": digest} == expected,
                "allowed evidence differs from original index: " + relative,
            )
            total += len(raw)
            require(
                total <= MAX_EXPORT_BYTES,
                "metadata export exceeds its output-only bound",
            )
            destination = output / relative
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(raw)
            copied[relative] = expected
        manifest = dict(
            schema="hepta-model-metadata-artifact-v1",
            source=source_sha,
            files=copied,
            original_index_sha256=hashlib.sha256(index_raw).hexdigest(),
            omitted_file_count=len(set(index["files"]) - set(copied)),
            omitted_hash_scope="Original producer index only; omitted payloads are not retained or re-read here.",
            checkpoint_payloads_exported=False,
            archived_payloads_exported=False,
            independent_payload_replay_available=False,
            product_qualification=False,
        )
        (output / "metadata-export.json").write_text(
            json.dumps(manifest, indent=2) + "\n"
        )
    except BaseException:
        shutil.rmtree(output)
        raise
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    manifest = export(args.root, args.output, args.source_sha)
    print(
        json.dumps(
            dict(
                exported_files=len(manifest["files"]),
                omitted_files=manifest["omitted_file_count"],
                checkpoint_payloads_exported=False,
            )
        )
    )


if __name__ == "__main__":
    main()
