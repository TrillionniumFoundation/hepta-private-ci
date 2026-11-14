#!/usr/bin/env python3
"""Run bounded source mutations against learning.operator safety invariants."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "codex-rs/Cargo.toml"


@dataclass(frozen=True)
class Mutant:
    name: str
    path: str
    original: str
    replacement: str
    command: tuple[str, ...]
    replace_last: bool = False


OPERATOR_TEST = (
    "cargo",
    "test",
    "--manifest-path",
    str(MANIFEST),
    "--locked",
    "-p",
    "codex-hepta-bellman-operator",
)
OWNER_TEST = (
    "cargo",
    "test",
    "--manifest-path",
    str(MANIFEST),
    "--locked",
    "-p",
    "codex-hepta-agentd",
    "--test",
    "terminal_cell_owner",
    "real_owner_decision_outcome_freeze_fit_registry_reload_and_withdrawal",
    "--",
    "--exact",
    "--test-threads=1",
)

MUTANTS = (
    Mutant(
        name="duplicate-evidence-admission",
        path="codex-rs/hepta-bellman-operator/src/learned.rs",
        original="if !seen_evidence.insert(sample.evidence_digest) {",
        replacement="if false && !seen_evidence.insert(sample.evidence_digest) {",
        command=OPERATOR_TEST,
    ),
    Mutant(
        name="payload-pin-digest-binding",
        path="codex-rs/hepta-bellman-operator/src/loaded.rs",
        original=(
            "if pin.payload_digest.is_zero() || Digest32::of_bytes(bytes) != pin.payload_digest {"
        ),
        replacement=(
            "if pin.payload_digest.is_zero() && Digest32::of_bytes(bytes) != pin.payload_digest {"
        ),
        command=OPERATOR_TEST,
    ),
    Mutant(
        name="fit-time-ledger-revalidation",
        path="codex-rs/hepta-bellman-operator/src/owner_terminal.rs",
        original="owner.revalidate_dataset_snapshot(&frozen.dataset, now)?;",
        replacement="let _ = (owner, now);",
        command=OWNER_TEST,
        replace_last=True,
    ),
)


def run(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["CARGO_TERM_COLOR"] = "never"
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def replace(text: str, mutant: Mutant) -> str:
    count = text.count(mutant.original)
    if count == 0:
        raise ValueError(f"mutation anchor missing: {mutant.name}")
    if mutant.replace_last:
        index = text.rfind(mutant.original)
        return text[:index] + mutant.replacement + text[index + len(mutant.original) :]
    if count != 1:
        raise ValueError(f"mutation anchor is ambiguous: {mutant.name} count={count}")
    return text.replace(mutant.original, mutant.replacement, 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output_path = (ROOT / args.output).resolve()
    if ROOT.resolve() not in output_path.parents:
        print("output must remain inside repository workspace", file=sys.stderr)
        return 1

    baseline_commands: dict[tuple[str, ...], dict[str, object]] = {}
    results: list[dict[str, object]] = []
    try:
        for command in dict.fromkeys(mutant.command for mutant in MUTANTS):
            completed = run(command)
            baseline_commands[command] = {
                "command": list(command),
                "returnCode": completed.returncode,
            }
            if completed.returncode != 0:
                print(completed.stdout, file=sys.stderr)
                raise RuntimeError(f"baseline command failed: {' '.join(command)}")

        for mutant in MUTANTS:
            path = ROOT / mutant.path
            original_bytes = path.read_bytes()
            original_text = original_bytes.decode("utf-8")
            mutated_text = replace(original_text, mutant)
            try:
                path.write_text(mutated_text, encoding="utf-8")
                completed = run(mutant.command)
                killed = completed.returncode != 0
                results.append(
                    {
                        "name": mutant.name,
                        "source": mutant.path,
                        "command": list(mutant.command),
                        "returnCode": completed.returncode,
                        "killed": killed,
                        "outputTail": completed.stdout[-4000:],
                    }
                )
                if not killed:
                    raise RuntimeError(f"surviving safety mutant: {mutant.name}")
            finally:
                path.write_bytes(original_bytes)

        clean = subprocess.run(
            ("git", "diff", "--exit-code", "--", *(mutant.path for mutant in MUTANTS)),
            cwd=ROOT,
            check=False,
        )
        if clean.returncode != 0:
            raise RuntimeError("mutation sources were not restored")

        payload = {
            "schema": "hepta.learning-operator.mutation.v1",
            "baselineCommands": list(baseline_commands.values()),
            "mutants": results,
            "requiredMutants": len(MUTANTS),
            "killedMutants": sum(1 for result in results if result["killed"]),
            "thresholdPercent": 100,
            "passed": all(result["killed"] for result in results),
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError) as error:
        print(f"learning.operator mutation failure: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
