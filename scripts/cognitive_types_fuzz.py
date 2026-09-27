#!/usr/bin/env python3
"""Run the real native sanitizer harness in an isolated, exact-source worktree.

The source checkout remains read-only. Retain the resolved fuzz lockfile as an
explicit build input; it is not confused with the repository's workspace lock.
A bounded libFuzzer run is execution evidence, not exhaustive correctness.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import hepta_ci_exec


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel"))
    source = git(root, "rev-parse", "HEAD")
    tree = git(root, "rev-parse", "HEAD^{tree}")
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("fuzz execution requires clean source")
    output = args.output.resolve()
    if output.is_relative_to(root):
        raise ValueError("evidence must be outside source")
    output.mkdir(parents=True, exist_ok=False)
    corpus = output / "corpus"
    crashes = output / "crashes"
    corpus.mkdir()
    crashes.mkdir()
    fixture = root / "codex-rs/hepta-cognitive-types/tests/fixtures/closure_vectors.json"
    vectors = json.loads(fixture.read_bytes())["vectors"]
    for index, vector in enumerate(vectors):
        envelope = {"contract": vector["contract"], "schema": vector["schema"],
                    "schemaVersion": 1, "payload": vector["payload"]}
        (corpus / f"seed-{index:03d}").write_text(json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    argv = ["cargo", "+nightly-2026-09-01", "fuzz", "run", "decode_contracts", str(corpus),
            "--", "-max_total_time=300", "-max_len=263168", "-rss_limit_mb=2048", "-timeout=5",
            f"-artifact_prefix={crashes}/"]
    previous_directory = Path.cwd()
    previous_environment = dict(os.environ)
    receipt = {"schema": "hepta.cognitive-types.native-fuzz.v1", "source_sha": source,
               "tree_sha": tree, "argv": argv, "seed_count": len(vectors),
               "corpus_input_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
               "status": "running", "production_accepted": False}
    result_path = output / "receipt.json"
    result_path.write_text(json.dumps(receipt, indent=2) + "\n")
    with tempfile.TemporaryDirectory(prefix="cognitive-fuzz-") as temporary:
        checkout = Path(temporary) / "source"
        git(root, "worktree", "add", "--detach", str(checkout), source)
        try:
            os.chdir(checkout / "codex-rs/hepta-cognitive-types")
            os.environ["CARGO_TARGET_DIR"] = str(Path(temporary) / "target")
            execution = hepta_ci_exec.execute_logged(argv, output / "native.log", timeout_seconds=1800)
            receipt["execution"] = execution
            lock = checkout / "codex-rs/hepta-cognitive-types/fuzz/Cargo.lock"
            if lock.is_file():
                shutil.copyfile(lock, output / "resolved-fuzz-Cargo.lock")
                receipt["resolved_fuzz_lock_sha256"] = hashlib.sha256(lock.read_bytes()).hexdigest()
            unexpected = git(checkout, "ls-files", "--others", "--exclude-standard").splitlines()
            unchanged = not git(checkout, "diff", "HEAD", "--") and all(
                path == "codex-rs/hepta-cognitive-types/fuzz/Cargo.lock" for path in unexpected)
            log = (output / "native.log").read_text(errors="replace")
            # Require the libFuzzer completion marker, not cargo build success.
            ran = "Done " in log and " runs in " in log
            passed = (execution["returncode"] == 0 and not execution["timed_out"]
                      and not execution["output_limit_exceeded"] and unchanged and ran and lock.is_file())
            receipt["status"] = "passed" if passed else "failed"
            receipt["tracked_source_unchanged"] = unchanged
        finally:
            os.chdir(previous_directory)
            os.environ.clear()
            os.environ.update(previous_environment)
            git(root, "worktree", "remove", "--force", str(checkout))
    if source != git(root, "rev-parse", "HEAD") or git(root, "status", "--porcelain", "--untracked-files=all"):
        receipt["status"] = "failed"
        receipt["source_identity_error"] = True
    temporary_receipt = output / "receipt.pending.json"
    with temporary_receipt.open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary_receipt.replace(result_path)
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
