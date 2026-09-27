#!/usr/bin/env python3
"""Execute targeted source mutants in detached worktrees; never rewrite the candidate.

Only a compiled mutant with an observed nextest assertion failure is killed.
Compile/setup failures, timeouts and missing test summaries are errors, not kills.
This is a bounded regression mutation set, not an exhaustive mutation score.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

import hepta_ci_exec

PREFIX = "codex-rs/hepta-cognitive-types/src/"
MUTANTS = (
    ("logical-key", "wire_semantics.rs", "if !seen.insert(key) {", "if false && !seen.insert(key) {"),
    ("canonical-bytes", "wire.rs", "if canonical.as_slice() != bytes {", "if false && canonical.as_slice() != bytes {"),
    ("byte-budget", "wire_semantics.rs", "if bytes.len() > self.remaining {", "if false && bytes.len() > self.remaining {"),
    ("profile-tokenizer", "transitions.rs", "|| observed.tokenizer_digest != expected.tokenizer_digest", "|| false && observed.tokenizer_digest != expected.tokenizer_digest"),
)


def command(root: Path, argv: list[str]) -> str:
    return subprocess.check_output(argv, cwd=root, text=True).strip()


def classify(returncode: int, output: str) -> str:
    lines = re.findall(r"Summary\s+\[[^\]]+\]\s+(\d+) tests run:\s*([^\n]+)", output)
    if not lines:
        return "error"
    passed = sum(int(value) for _, status in lines for value in re.findall(r"\b(\d+) passed\b", status))
    failed = sum(int(value) for _, status in lines for value in re.findall(r"\b(\d+) failed\b", status))
    if passed + failed == 0:
        return "error"
    if returncode == 0 and passed > 0 and failed == 0:
        return "survived"
    if returncode != 0 and failed > 0:
        return "killed"
    return "error"


def run(root: Path, output: Path, name: str, env: dict[str, str]) -> dict[str, object]:
    argv = ["just", "test", "--locked", "-p", "codex-hepta-cognitive-types"]
    started = time.monotonic()
    previous_directory = Path.cwd()
    previous_environment = dict(os.environ)
    log = output / f"{name}.log"
    try:
        os.chdir(root)
        os.environ.update(env)
        execution = hepta_ci_exec.execute_logged(argv, log, timeout_seconds=1200)
    finally:
        os.chdir(previous_directory)
        os.environ.clear()
        os.environ.update(previous_environment)
    data = log.read_bytes()
    text = data.decode("utf-8", "replace")
    code = execution["returncode"]
    error = execution["timed_out"] or execution["output_limit_exceeded"]
    return {"name": name, "argv": argv, "returncode": code,
            "elapsed_seconds": time.monotonic() - started,
            "log_sha256": hashlib.sha256(data).hexdigest(),
            "execution": execution,
            "status": "error" if error else classify(code, text)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(command(Path.cwd(), ["git", "rev-parse", "--show-toplevel"]))
    if command(root, ["git", "status", "--porcelain", "--untracked-files=all"]):
        raise ValueError("mutation qualification requires a clean candidate")
    source = command(root, ["git", "rev-parse", "HEAD"])
    tree = command(root, ["git", "rev-parse", "HEAD^{tree}"])
    output = args.output.resolve()
    if output.is_relative_to(root):
        raise ValueError("mutation evidence must be outside the checkout")
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    env = dict(os.environ, CARGO_TERM_COLOR="never", CARGO_INCREMENTAL="0")
    with tempfile.TemporaryDirectory(prefix="cognitive-mutants-") as temporary:
        parent = Path(temporary)
        env["CARGO_TARGET_DIR"] = str(parent / "target")
        for name, filename, before, after in (("baseline", "", "", ""), *MUTANTS):
            checkout = parent / name
            command(root, ["git", "worktree", "add", "--detach", str(checkout), source])
            try:
                if filename:
                    path = checkout / PREFIX / filename
                    text = path.read_text()
                    if text.count(before) != 1:
                        raise ValueError(f"mutation anchor drift: {name}")
                    path.write_text(text.replace(before, after))
                row = run(checkout, output, name, env)
                if filename:
                    row["mutated_file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                rows.append(row)
                if name == "baseline" and row["status"] != "survived":
                    break
            finally:
                command(root, ["git", "worktree", "remove", "--force", str(checkout)])
    passed = len(rows) == len(MUTANTS) + 1 and rows[0]["status"] == "survived" and all(row["status"] == "killed" for row in rows[1:])
    unchanged = source == command(root, ["git", "rev-parse", "HEAD"]) and not command(root, ["git", "status", "--porcelain", "--untracked-files=all"])
    receipt = {"schema": "hepta.cognitive-types.targeted-mutations.v1", "source_sha": source,
               "tree_sha": tree, "status": "passed" if passed and unchanged else "failed",
               "rows": rows, "exhaustive": False, "production_accepted": False}
    with (output / "receipt.json").open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return 0 if passed and unchanged else 1


if __name__ == "__main__":
    raise SystemExit(main())
