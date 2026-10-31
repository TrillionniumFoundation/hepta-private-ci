"""Compile one recovery probe against already-built original Rust dependencies."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args):
    area = Path(__file__).resolve().parent
    args.output.mkdir(parents=True, exist_ok=False)
    if hasattr(os, "sched_getaffinity"):
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    dependencies = {}
    for name in ("codex_hepta_neuron", "codex_hepta_types", "serde", "serde_json"):
        found = list(args.dependencies.glob("lib" + name + "-*.rlib"))
        if len(found) != 1:
            raise ValueError("Expected one pinned native dependency: " + name)
        dependencies[name] = found[0]
    binary = args.output / "codex-neuron-chain-recovery-probe"
    command = [str(args.rustc), "--edition=2024", "-C", "opt-level=2", "-C", "debuginfo=0",
               str(area / "chain_recovery_probe.rs"), "-L", "dependency=" + str(args.dependencies), "-o", str(binary)]
    for name, path in dependencies.items():
        command.extend(("--extern", name + "=" + str(path)))
    started = time.monotonic_ns()
    with (args.output / "build.log").open("xb") as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    with (args.output / "probe.log").open("xb") as log:
        subprocess.run([str(binary), str(args.packet), str(args.run), str(args.output / "cases")],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    report = json.loads((args.output / "cases/result.json").read_text())
    receipt = {"schema": "hepta.production-handoff.chain-build.v1", "status": report["status"],
        "rustc": subprocess.check_output([str(args.rustc), "--version"], text=True).strip(),
        "rustc_sha256": sha(args.rustc), "binary_sha256": sha(binary),
        "sources": {p.name: sha(p) for p in (area / "chain_recovery_probe.rs", area / "neuron_chain_recovery.rs")},
        "dependency_rlibs": {name: {"path": str(path), "sha256": sha(path)} for name, path in dependencies.items()},
        "packet_sha256": sha(args.packet), "input_result_sha256": sha(args.run / "result.json"),
        "probe_result_sha256": sha(args.output / "cases/result.json"),
        "single_cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        "wall_ns": time.monotonic_ns() - started,
        "scope": "original 9595221 journal dependencies; target f8c9419 bootstrap patch is not a deployed or fully compiled Agentd"}
    (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": report["status"], "checks": len(report["checks"]), "output": str(args.output)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rustc", "dependencies", "packet", "run", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    run(parser.parse_args())
