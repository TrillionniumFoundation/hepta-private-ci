"""Run real, bounded engineering checks without resolving or adopting new dependencies."""

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import lock_repair as repair


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BUDGETS = {"metadata": 900, "native": 2700, "bazel": 1200}


def git(*args):
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, check=True, timeout=30
    ).stdout


def normalized_tree(raw, old_lock_blob, expected_new_blob):
    """Reconstitute only the old Cargo.lock entry in an observed Git tree object."""
    position, chunks, seen = 0, [], 0
    while position < len(raw):
        end = raw.index(b"\0", position)
        entry, oid = raw[position:end], raw[end + 1 : end + 21]
        if len(oid) != 20:
            raise ValueError("truncated Git tree entry")
        if entry == b"100644 Cargo.lock":
            if oid.hex() != expected_new_blob:
                raise ValueError("committed Cargo.lock is not the verified candidate")
            oid = bytes.fromhex(old_lock_blob)
            seen += 1
        chunks.append(entry + b"\0" + oid)
        position = end + 21
    if seen != 1:
        raise ValueError("expected one regular Cargo.lock entry")
    normalized = b"".join(chunks)
    return hashlib.sha1(
        b"tree " + str(len(normalized)).encode() + b"\0" + normalized
    ).hexdigest()


def verify_sources(constraints):
    expected = dict(constraints["original_inputs"])
    expected.update(constraints["repaired_candidate"])
    expected.update(constraints.get("additional_input_pins", {}))
    observed = {}
    for path, descriptor in expected.items():
        raw = (ROOT / path).read_bytes()
        repair.checked(raw, descriptor, path)
        observed[path] = repair.identity(raw)
    science = constraints["frozen_science"]
    if len(science["source_files"]) != science["source_file_count"]:
        raise ValueError("scientific source inventory count mismatch")
    if set(science["source_files"]) & set(repair.LOCKS):
        raise ValueError("lock replacement overlaps frozen science")
    for path, digest in science["source_files"].items():
        descriptor = repair.identity((ROOT / path).read_bytes())
        if descriptor["sha256"] != digest:
            raise ValueError(f"frozen scientific source changed: {path}")
        observed[path] = descriptor
    raw = (ROOT / repair.LOCKS[0]).read_bytes()
    lock_blob = hashlib.sha1(
        b"blob " + str(len(raw)).encode() + b"\0" + raw
    ).hexdigest()
    tree = normalized_tree(
        git("cat-file", "tree", "HEAD:codex-rs"),
        constraints["original_cargo_lock_git_blob"],
        lock_blob,
    )
    if tree != constraints["original_codex_rs_git_tree"]:
        raise ValueError(
            "Rust source tree changed beyond the registered Cargo.lock replacement"
        )
    git("diff", "--exit-code", "HEAD", "--", "codex-rs")
    for path in HERE.glob("*.py"):
        observed[str(path.relative_to(ROOT))] = repair.identity(path.read_bytes())
    observed[str((HERE / "constraints.json").relative_to(ROOT))] = repair.identity(
        (HERE / "constraints.json").read_bytes()
    )
    return observed


def load_dependency(path, label):
    spec = importlib.util.spec_from_file_location(label, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(args, constraints):
    output = args.output_dir.resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("validation evidence must be outside the source checkout")
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema": "hepta.parameter-field.lock-closure-validation.1",
        "requested_phase": args.phase,
        "expected_machine": args.expected_machine,
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "source_base": constraints["source_base"],
        "source_head": None,
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "qualification": False,
        "dependency_graph_approved": False,
        "graph_review_required": True,
        "validation_passed": False,
        "commands": [],
        "tests": [],
        "errors": [],
        "status": "in_progress",
        "scope": "Engineering evidence for this phase, exact source and host only; no scientific outcome or adoption conclusion.",
    }
    started = time.monotonic()
    deadline = started + BUDGETS[args.phase]

    def save():
        receipt["elapsed_wall_seconds"] = time.monotonic() - started
        temporary = output / "receipt.json.tmp"
        temporary.write_text(json.dumps(receipt, indent=2) + "\n")
        temporary.replace(output / "receipt.json")

    save()
    inputs_before = None
    try:
        if receipt["platform"] != {"system": "Linux", "machine": args.expected_machine}:
            raise ValueError(
                "host architecture does not match the requested Linux validation arm"
            )
        receipt["source_head"] = git("rev-parse", "HEAD").decode().strip()
        inputs_before = verify_sources(constraints)
        receipt["inputs_before"] = inputs_before
        capture = load_dependency(
            "scripts/capture_cargo_deny_diagnostic.py", "lock_capture"
        )
        policy = load_dependency(
            "scripts/hepta_dependency_validation.py", "lock_policy"
        )
        save()

        def invoke(label, command, cwd, maximum, limit=1024 * 1024):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("aggregate phase deadline exhausted")
            result = capture.capture(
                command,
                cwd,
                output,
                label,
                timeout=min(maximum, remaining),
                limit=limit,
            )
            result["label"] = label
            result["working_directory"] = str(cwd.relative_to(ROOT))
            receipt["commands"].append(result)
            save()
            return result

        def require_success(result):
            if result["timed_out"] or result["exit_code"] != 0:
                raise ValueError(
                    f"command failed: {result['label']} exit={result['exit_code']} timeout={result['timed_out']}"
                )

        for tool in ("cargo", "rustc"):
            result = invoke(
                tool + "_version", [tool, "--version"], ROOT / "codex-rs", 60
            )
            require_success(result)
            stream = result["streams"]["stdout"]
            text = (output / stream["prefix"]["path"]).read_bytes() + (
                output / stream["tail"]["path"]
            ).read_bytes()
            if not stream["complete"] or not text.startswith(
                (tool + " 1.95.0 ").encode()
            ):
                raise ValueError("expected the inherited Rust/Cargo 1.95.0 toolchain")
        if args.phase == "metadata":
            result = invoke(
                "cargo_metadata_locked",
                ["cargo", "metadata", "--locked", "--format-version=1"],
                ROOT / "codex-rs",
                780,
            )
            require_success(result)
        elif args.phase == "bazel":
            result = invoke(
                "bazel_lock_check", ["just", "bazel-lock-check"], ROOT, 1100
            )
            require_success(result)
        else:
            junit_path = ROOT / policy.junit_relative_path(
                tomllib.loads((ROOT / "codex-rs/.config/nextest.toml").read_text()),
                (ROOT / "justfile").read_text(),
            )
            regression = policy.regression_contract(
                (ROOT / policy.REGRESSION_PATH).read_bytes(),
                constraints["original_inputs"][policy.REGRESSION_PATH]["sha256"],
            )
            for spec in policy.GROUPS:
                junit_path.unlink(missing_ok=True)
                result = invoke(
                    spec["label"],
                    policy.test_command(spec),
                    ROOT,
                    1800,
                    8 * 1024 * 1024,
                )
                if (
                    not junit_path.is_file()
                    or junit_path.stat().st_size > 2 * 1024 * 1024
                ):
                    raise ValueError(
                        f"missing or excessive fresh JUnit: {spec['label']}"
                    )
                raw = junit_path.read_bytes()
                (output / (spec["label"] + ".junit.xml")).write_bytes(raw)
                entry = {"label": spec["label"], "junit": repair.identity(raw)}
                receipt["tests"].append(entry)
                save()
                entry["result"] = policy.junit_result(raw, result, spec, regression)
                save()
        receipt["phase_commands_passed"] = True
    except (
        OSError,
        ValueError,
        KeyError,
        TimeoutError,
        subprocess.SubprocessError,
    ) as error:
        receipt["errors"].append(f"{type(error).__name__}: {error}")
    finally:
        if inputs_before is not None:
            try:
                after = verify_sources(constraints)
                receipt["inputs_after"] = after
                if inputs_before != after:
                    raise ValueError("consumed source bytes changed during validation")
                receipt["source_and_locks_unchanged"] = True
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
                receipt["errors"].append(f"final integrity check: {error}")
        if time.monotonic() > deadline:
            receipt["errors"].append(
                "aggregate phase deadline exceeded, including final integrity checks"
            )
        receipt["validation_passed"] = bool(
            receipt.get("phase_commands_passed")
            and receipt.get("source_and_locks_unchanged")
            and not receipt["errors"]
        )
        receipt["status"] = "passed" if receipt["validation_passed"] else "failed"
        save()
    print(
        json.dumps(
            {
                key: receipt[key]
                for key in (
                    "requested_phase",
                    "status",
                    "validation_passed",
                    "qualification",
                    "errors",
                )
            }
        )
    )
    return 0 if receipt["validation_passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=tuple(BUDGETS), required=True)
    parser.add_argument(
        "--expected-machine", choices=("x86_64", "aarch64"), required=True
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        return run(args, json.loads((HERE / "constraints.json").read_text()))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f"Validation could not initialize: {error}\n")


if __name__ == "__main__":
    sys.exit(main())
