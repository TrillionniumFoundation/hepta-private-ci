#!/usr/bin/env python3
"""Native old/new fixture stages within the existing exact-candidate receipt.

The old stage executes pinned production source plus one explicitly recorded
injected test harness; it does not qualify an unmodified historical head.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import context_compiler_candidate as candidate
import context_compiler_named_evidence as named_evidence

BASELINE_COMMIT = "42de79393a1b2424f43e4df4a025ea976ab0e093"
BASELINE_TREE = "bc5d2e13636ce8d58aea104f3b1695af85b239ad"
BASELINE_HARNESS_SHA256 = (
    "7dc34d6606d314f94257868ac22ed4748c2a277f44fe37e1686b7b3860cb4a99"
)
HARNESS = Path("codex-rs/hepta-automation/tests/neural_circuit_canonical.rs")
NATIVE_TEST = "neural_circuit_canonical_bytes_match_constructor_contract"
NATIVE_ARGV = (
    "just",
    "test",
    "--locked",
    "-p",
    "codex-hepta-automation",
    "--test",
    "neural_circuit_canonical",
    "-E",
    f"test(={NATIVE_TEST})",
    "--status-level",
    "pass",
    "--success-output",
    "immediate",
)
IMPORT = (
    "use codex_hepta_automation::NeuralCircuitSpecV1; // CANONICAL_API_TYPE_IMPORT\n"
)
BEGIN = "    // BEGIN CANONICAL_CONSTRUCTOR_ADAPTER\n"
END = "    // END CANONICAL_CONSTRUCTOR_ADAPTER\n"
FIELDS = (
    "circuit_id",
    "version",
    "predecessor_digest",
    "entry_node",
    "nodes",
    "edges",
    "capability_set",
    "route_policy_digest",
    "parameter_bundle_digest",
    "resource_profile_digest",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def baseline_harness(source: bytes) -> bytes:
    text = source.decode("utf-8")
    if any(text.count(marker) != 1 for marker in (IMPORT, BEGIN, END)):
        raise ValueError("constructor adapter markers missing or ambiguous")
    prefix, body = text.split(BEGIN)
    adapter, suffix = body.split(END)
    fields = "".join(f"        {field},\n" for field in FIELDS)
    expected = (
        "    NeuralCircuitCandidateV1::new(NeuralCircuitSpecV1 {\n"
        + fields
        + "    })\n"
    )
    if adapter != expected:
        raise ValueError("unexpected candidate constructor adapter")
    old = "    NeuralCircuitCandidateV1::new(\n" + fields + "    )\n"
    result = (prefix.replace(IMPORT, "") + BEGIN + old + END + suffix).encode()
    if sha256(result) != BASELINE_HARNESS_SHA256:
        raise ValueError("baseline harness pin mismatch")
    return result


def identity(root: Path) -> dict:
    candidate.clean(root)
    candidate.git(root, "ls-files", "--error-unmatch", HARNESS.as_posix())
    return {
        "testedCommit": candidate.git(root, "rev-parse", "HEAD"),
        "testedTree": candidate.git(root, "rev-parse", "HEAD^{tree}"),
    }


def source_freeze(root: Path) -> list[dict]:
    """Hash tracked bytes, including symlink text, independently of mtimes."""
    paths = candidate.git(root, "ls-files", "-z").split("\0")
    result = []
    for name in sorted(filter(None, paths)):
        path = root / name
        data = (
            os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
        )
        result.append(
            {"path": name, "sha256": sha256(data), "mode": path.lstat().st_mode}
        )
    return result


def switch_source(root: Path, before: list[dict]) -> None:
    # Both stages deliberately share the qualification target directory. Touch
    # every tracked input on each source switch so Cargo cannot reuse a newer
    # artifact merely because the checked-out source has an older mtime.
    for entry in before:
        os.utime(root / entry["path"], follow_symlinks=False)
    os.utime(root / HARNESS, follow_symlinks=False)
    if source_freeze(root) != before:
        raise ValueError("source changed during cache invalidation")


def run_native(root: Path, stage: Path, target: Path) -> list[str]:
    argv = list(NATIVE_ARGV)
    env = os.environ.copy()
    env.update(
        {
            "CARGO_TARGET_DIR": str(target),
            "HEPTA_CANONICAL_FIXTURE_OUTPUT": str(stage / "results.json"),
        }
    )
    with (stage / "native.log").open("wb") as log:
        process = subprocess.Popen(
            argv,
            cwd=root / "codex-rs",
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=False,
        )
        assert process.stdout is not None
        with process.stdout:
            for block in iter(lambda: process.stdout.read(64 * 1024), b""):
                log.write(block)
                log.flush()
                sys.stdout.buffer.write(block)
                sys.stdout.buffer.flush()
        if process.wait() != 0:
            raise ValueError("native canonical fixture failed")
    # Reuse the existing parsers; never fabricate or replay a runner summary.
    from context_compiler_execution import observed_tests

    if (
        observed_tests(
            named_evidence.bounded_lines(stage / "native.log"), runner="nextest"
        )
        != 1
    ):
        raise ValueError("canonical stage must execute exactly one native test")
    if not named_evidence.bind_named_tests(stage / "native.log", [NATIVE_TEST])[
        "namedNativeTestsPassed"
    ]:
        raise ValueError("canonical native test pass missing")
    return argv


def read_results(path: Path) -> bytes:
    data = path.read_bytes()
    value = json.loads(data)
    if value.get("schema") != "hepta.neural-circuit-canonical-fixtures.v1":
        raise ValueError("canonical fixture schema mismatch")
    if [item["name"] for item in value["fixtures"]] != [
        "unsorted-v1",
        "exact-predecessor-successor",
        "effect-capability-idempotency",
    ]:
        raise ValueError("canonical fixture inventory mismatch")
    for item in value["fixtures"]:
        circuit = json.loads(bytes(item["candidate_json_bytes"]))
        receipt = json.loads(bytes(item["compilation_receipt_json_bytes"]))
        if (
            circuit["circuit_digest"] != item["circuit_digest"]
            or receipt["circuit_digest"] != item["circuit_digest"]
            or receipt["taskflow_definition_digest"]
            != item["taskflow_definition_digest"]
            or receipt["authority_granted"] is not False
        ):
            raise ValueError("canonical result identities disagree")
    return data


def qualify(root: Path, output: Path, stage_name: str) -> None:
    root, output = root.resolve(), output.resolve()
    if output == root or root in output.parents:
        raise ValueError("canonical evidence must be outside candidate")
    tested = identity(root)
    candidate.git(
        root, "merge-base", "--is-ancestor", BASELINE_COMMIT, tested["testedCommit"]
    )
    if candidate.git(root, "rev-parse", f"{BASELINE_COMMIT}^{{tree}}") != BASELINE_TREE:
        raise ValueError("baseline tree mismatch")
    harness = (root / HARNESS).read_bytes()
    old_harness = baseline_harness(harness)
    before = source_freeze(root)
    stage = output / "canonical-compatibility" / stage_name
    stage.mkdir(parents=True, exist_ok=False)
    write_json(stage / "candidate-source-before.json", before)
    target = Path(os.environ.get("CARGO_TARGET_DIR", root / "codex-rs/target"))
    if not target.is_absolute():
        target = (root / "codex-rs" / target).resolve()
    evidence = {
        "candidateIdentity": tested,
        "baselineCommit": BASELINE_COMMIT,
        "baselineTree": BASELINE_TREE,
        "baselineHarnessSha256": BASELINE_HARNESS_SHA256,
        "candidateHarnessSha256": sha256(harness),
        "stage": stage_name,
        "argv": list(NATIVE_ARGV),
        "status": "failed",
        "scope": "native_canonical_fixture_compatibility_not_old_head_qualification",
        "sharedTarget": str(target),
    }
    # Persist failure-by-default before any child can be terminated by the
    # enclosing qualification timeout. Children inherit its process group.
    write_json(stage / "evidence.json", evidence)
    try:
        if stage_name == "baseline":
            # clone --shared borrows objects read-only but owns its index/refs;
            # no worktree registration, primary checkout/ref changes or fetch.
            with tempfile.TemporaryDirectory(
                prefix="canonical-baseline-", dir=output.parent
            ) as temp:
                old = Path(temp) / "source"
                candidate.git(
                    root, "clone", "--shared", "--no-checkout", str(root), str(old)
                )
                candidate.git(old, "checkout", "--detach", BASELINE_COMMIT)
                if candidate.git(old, "rev-parse", "HEAD^{tree}") != BASELINE_TREE:
                    raise ValueError("cloned baseline identity mismatch")
                candidate.clean(old)
                baseline_before = source_freeze(old)
                write_json(stage / "baseline-production-before.json", baseline_before)
                (old / HARNESS).write_bytes(old_harness)
                (stage / "injected-baseline-harness.rs").write_bytes(old_harness)
                evidence["injectedTestHarness"] = HARNESS.as_posix()
                try:
                    switch_source(old, baseline_before)
                    evidence["argv"] = run_native(old, stage, target)
                finally:
                    baseline_after = source_freeze(old)
                    write_json(stage / "baseline-production-after.json", baseline_after)
                    if (
                        baseline_before != baseline_after
                        or (old / HARNESS).read_bytes() != old_harness
                        or candidate.git(
                            old, "status", "--porcelain=v1", "--untracked-files=all"
                        )
                        != f"?? {HARNESS.as_posix()}"
                    ):
                        raise ValueError(
                            "baseline production or injected harness changed"
                        )
        else:
            baseline = stage.parent / "baseline"
            prior = json.loads((baseline / "evidence.json").read_text())
            for key in (
                "candidateIdentity",
                "baselineCommit",
                "baselineTree",
                "baselineHarnessSha256",
                "candidateHarnessSha256",
            ):
                if prior.get(key) != evidence[key]:
                    raise ValueError("baseline evidence identity mismatch")
            if (
                prior.get("status") != "passed"
                or json.loads((baseline / "candidate-source-before.json").read_text())
                != before
            ):
                raise ValueError("baseline execution missing or source changed")
            switch_source(root, before)
            evidence["argv"] = run_native(root, stage, target)
            old_result = read_results(baseline / "results.json")
            if sha256(old_result) != prior.get(
                "resultsSha256"
            ) or old_result != read_results(stage / "results.json"):
                raise ValueError("canonical outputs differ byte-for-byte")
            evidence["byteForByteMatch"] = True
        evidence["resultsSha256"] = sha256(read_results(stage / "results.json"))
        evidence["status"] = "passed"
    finally:
        try:
            after = source_freeze(root)
            write_json(stage / "candidate-source-after.json", after)
            if before != after or identity(root) != tested:
                raise ValueError("candidate production source changed")
        except BaseException:
            evidence["status"] = "failed"
            raise
        finally:
            write_json(stage / "evidence.json", evidence)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("baseline", "candidate"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        qualify(Path(__file__).resolve().parents[1], args.output_dir, args.stage)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"canonical stage failed: {type(error).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
