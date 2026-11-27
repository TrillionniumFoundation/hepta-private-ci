"""Replay a pinned candidate, retaining subprocess costs and engineering evidence."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

from scripts.joint_generation_v4_receipt import artifact_binding, source_binding


def execute(commit, compiler, output):
    root = Path(__file__).resolve().parents[1]
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "status": "started",
        "checks": [],
        "scientific_acceptance": "HOLD_NO_GO",
        "full_workspace_validation": False,
        "production_adoption_authorized": False,
        "energy_joules": None,
        "provider_charges": None,
        "runner": artifact_binding(__file__),
    }
    env = dict(os.environ)
    env.update(
        PYTHONPATH=os.pathsep.join((str(root / "scripts"), str(root))),
        OMP_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        PYTHONDONTWRITEBYTECODE="1",
    )

    def run(name, argv):
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        start = time.perf_counter()
        with (output / (name + ".log")).open("xb") as log:
            proc = subprocess.run(
                argv, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT
            )
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        row = {
            "name": name,
            "command": argv,
            "exit_code": proc.returncode,
            "wall_seconds": time.perf_counter() - start,
            "child_cpu_seconds": after.ru_utime
            + after.ru_stime
            - before.ru_utime
            - before.ru_stime,
            "cost_scope": "whole subprocess including imports and reaped descendants; nested phase clocks not added",
            "log": artifact_binding(output / (name + ".log")),
        }
        report["checks"].append(row)
        print(
            json.dumps({k: row[k] for k in ("name", "exit_code", "wall_seconds")}),
            flush=True,
        )
        if proc.returncode:
            raise RuntimeError(f"{name} failed; original log retained")
        return row

    try:
        report["source"] = source_binding(root, commit)
        if subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=root):
            raise ValueError("Replay requires a clean committed candidate")
        compiler = str(Path(compiler).resolve(strict=True))
        version = subprocess.check_output([compiler, "--version"], text=True).strip()
        entry = str(
            root / "codex-rs/hepta-infer-worker-host/src/bin/hepta-joint-propose.rs"
        )
        tests, binary = (
            str(output / "native-tests"),
            str(output / "hepta-joint-propose"),
        )
        run(
            "native-test-build",
            [compiler, "--edition=2024", "--test", entry, "-o", tests],
        )
        run("native-tests", [tests, "--test-threads=1"])
        built = run(
            "native-build", [compiler, "--edition=2024", "-O", entry, "-o", binary]
        )
        source = source_binding(root, commit)
        if source != report["source"]:
            raise ValueError("Source changed during native build")
        attestation = {
            "schema": "hepta.joint-v4.local-build-attestation.v1",
            "source_commit": commit,
            "source_tree": source["tree"],
            "source_inventory_sha256": source["source_inventory_sha256"],
            "binary_sha256": artifact_binding(binary)["sha256"],
            "command": built["command"],
            "exit_code": 0,
            "compiler_version": version,
        }
        build_path = output / "local-build-attestation.json"
        build_path.write_text(json.dumps(attestation, indent=2) + "\n")
        env["JOINT_V4_NATIVE_BINARY"] = binary
        modules = [
            "scripts.test_joint_generation_v4",
            "scripts.test_joint_generation_v4_ndu",
            "scripts.test_joint_generation_v4_receipt",
        ]
        modules += [
            "ndu_real_runtime.test_" + name
            for name in (
                "action_effects",
                "forecast_support",
                "state_codec",
                "recursive_contract",
                "causal_analysis",
                "causal_protocol",
            )
        ]
        run("python-tests", [sys.executable, "-m", "unittest", *modules, "-v"])
        run(
            "training-native-diagnostic",
            [
                sys.executable,
                "-m",
                "scripts.joint_generation_v4_diagnostic",
                "--output",
                str(output / "diagnostic"),
                "--native-binary",
                binary,
                "--expected-source-commit",
                commit,
                "--build-attestation",
                str(build_path),
            ],
        )
        if source_binding(root, commit) != report["source"]:
            raise ValueError("Source changed during replay")
        report["status"] = "passed"
    except BaseException as error:
        report.update(status="failed", failure=f"{type(error).__name__}: {error}")
        raise
    finally:
        report["artifacts"] = {
            str(p.relative_to(output)): {
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in sorted(output.rglob("*"))
            if p.is_file()
        }
        (output / "validation.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--rustc", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    execute(args.source_commit, args.rustc, args.output)
