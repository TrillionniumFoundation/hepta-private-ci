#!/usr/bin/env python3
"""Render separate exact-candidate and governed evidence states."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from channel_matrix_evidence import COMMANDS, MAX_LOG_BYTES, file_digest, read_object
from channel_matrix_governed_attestation import verify_attestations


def command_state(directory: Path, label: str, source: dict, unchanged: bool) -> str:
    path = directory / f"{label}.command.json"
    if not path.exists():
        return "not_executed"
    row = read_object(path)
    log = directory / f"{label}.log"
    if (
        row.get("schema") != "hepta.channel-matrix-command.v1"
        or row.get("label") != label
        or row.get("arguments") != COMMANDS[label]
        or row.get("workingDirectory") != "codex-rs"
        or row.get("testedSha") != source["testedSha"]
        or row.get("sourceSnapshotSha256")
        != file_digest(directory / "source.json")
    ):
        raise ValueError("command identity mismatch")
    if not log.is_file() or log.is_symlink():
        raise ValueError("missing command log")
    size = log.stat().st_size
    if row.get("log") != {
        "path": log.name,
        "bytes": size,
        "sha256": file_digest(log),
        "withinBudget": size <= MAX_LOG_BYTES,
    }:
        raise ValueError("command log identity mismatch")
    if row.get("completed") is not True:
        return "not_completed"
    if type(row.get("exitCode")) is not int:
        raise ValueError("untyped command exit code")
    if row["exitCode"] != 0 or row.get("launchError") is not None:
        return "failed"
    if row.get("sourceUnchanged") is not True or not unchanged or size > MAX_LOG_BYTES:
        return "invalid_evidence"
    return "passed"


def summarize(directory: Path, governance_policy: Path | None = None) -> dict:
    states = {
        "source_navigation": "not_proved",
        "compilation": "not_executed",
        "native_tests": "not_executed",
        "strict_lint": "not_executed",
        "formatting": "not_executed",
        "target_qualification": "not_proved",
        "independent_acceptance": "not_proved",
    }
    identity = None
    governed = None
    if (directory / "source.json").exists():
        source = read_object(directory / "source.json")
        if source.get("schema") != "hepta.channel-matrix-source-snapshot.v1":
            raise ValueError("source schema mismatch")
        for name in ("testedSha", "testedTree", "sourceSha", "baseSha"):
            if not isinstance(source.get(name), str) or not re.fullmatch(
                "[0-9a-f]{40}", source[name]
            ):
                raise ValueError("invalid exact candidate")
        if source.get("lane") not in ("source-head", "base-merge") or not source.get(
            "files"
        ):
            raise ValueError("missing source inventory")
        identity = {
            "commit": source["testedSha"],
            "tree": source["testedTree"],
            "lane": source["lane"],
        }
        candidate_path = directory / "candidate.json"
        if candidate_path.exists():
            candidate = read_object(candidate_path)
            if (
                candidate.get("schema")
                != "hepta.channel-matrix-candidate-receipt.v1"
                or candidate.get("candidate")
                != {"commit": identity["commit"], "tree": identity["tree"]}
            ):
                raise ValueError("source/navigation identity mismatch")
            if (
                candidate.get("status")
                == "PASS_CHANNEL_MATRIX_CANDIDATE_BINDING"
            ):
                states["source_navigation"] = "passed"
        after = directory / "source-after.json"
        unchanged = after.exists() and file_digest(after) == file_digest(
            directory / "source.json"
        )
        for label, key in (
            ("compile", "compilation"),
            ("focused-tests", "native_tests"),
            ("clippy", "strict_lint"),
            ("format", "formatting"),
        ):
            states[key] = command_state(directory, label, source, unchanged)

    if governance_policy is not None:
        if identity is None:
            raise ValueError("governed receipts require an exact candidate")
        governed = verify_attestations(
            directory,
            {"commit": identity["commit"], "tree": identity["tree"]},
            governance_policy,
        )
        for scope in ("target_qualification", "independent_acceptance"):
            if governed["receipts"][scope] is not None:
                states[scope] = "passed"

    return {
        "schema": "hepta.channel-matrix-evidence-status.v2",
        "candidate": identity,
        "states": states,
        "governed_attestations": governed,
        "scope": (
            "derived_view_with_optional_cryptographically_verified_external_receipts"
            "_not_activation_or_release"
        ),
        "activation": False,
        "release": False,
        "authority_granted": False,
    }


def markdown(row: dict) -> str:
    lines = [
        "# Matrix evidence status",
        "",
        "Generated from exact-candidate receipts; not deployment authority.",
        "",
    ]
    if row["candidate"]:
        lines.append(
            f"Candidate: `{row['candidate']['commit']}` / "
            f"`{row['candidate']['tree']}`\n"
        )
    lines += ["| Evidence scope | State |", "|---|---|"]
    lines += [f"| {key} | {state} |" for key, state in row["states"].items()]
    lines += [
        "",
        (
            "Target qualification and independent acceptance require "
            "out-of-tree Ed25519-signed receipts under an explicitly supplied "
            "governance policy; neither implies activation or release."
        ),
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--governance-policy", type=Path)
    args = parser.parse_args()
    requested = args.directory
    directory = requested.resolve(strict=True)
    root = Path(__file__).resolve().parents[1]
    if (
        requested.is_symlink()
        or not directory.is_dir()
        or directory != requested.absolute()
        or directory.is_relative_to(root)
    ):
        parser.error(
            "generated status directory must be canonical and outside the candidate checkout"
        )
    try:
        row = summarize(directory, args.governance_policy)
        for name, payload in (
            ("status.json", json.dumps(row, indent=2, sort_keys=True) + "\n"),
            ("status.md", markdown(row)),
        ):
            with (directory / name).open("x", encoding="utf-8") as stream:
                stream.write(payload)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"FAIL_CHANNEL_MATRIX_STATUS: {type(exc).__name__}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
