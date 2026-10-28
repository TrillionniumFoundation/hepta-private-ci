"""Materialize exact source and complete scientific evidence for portable delivery."""

from pathlib import Path
import hashlib
import json
import os
import resource
import shutil
import subprocess
import time


REPOSITORY = Path(__file__).resolve().parents[4]
DELIVERABLES = REPOSITORY.parent / "deliverables"
PRESERVED = DELIVERABLES / "hepta-adaptive-v2-batch001-preserved"
BUNDLE = DELIVERABLES / "hepta_adaptive_neuron_v2_exact_evidence"
HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    started, cpu = time.perf_counter(), time.process_time()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    BUNDLE.mkdir(exist_ok=False)
    registration = REPOSITORY / "experiments/adaptive_neuron_v2/results/registration001"
    seal = json.loads((registration / "SOURCE_SEAL.json").read_text())
    for relative, identity in seal["inputs"].items():
        data = subprocess.check_output(
            ["git", "show", f"{seal['source_commit']}:{relative}"], cwd=REPOSITORY
        )
        if (
            len(data) != identity["bytes"]
            or hashlib.sha256(data).hexdigest() != identity["sha256"]
        ):
            raise ValueError(
                f"Source commit does not match registered input: {relative}"
            )
        target = BUNDLE / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for relative in (
        "experiments/adaptive_neuron_v2/README.md",
        "experiments/adaptive_neuron_v2/learning/THEORY.md",
        "experiments/adaptive_neuron_v2/owner/README.md",
    ):
        target = BUNDLE / "source" / relative
        target.write_bytes(
            subprocess.check_output(
                ["git", "show", f"{seal['source_commit']}:{relative}"], cwd=REPOSITORY
            )
        )
    shutil.copytree(
        registration,
        BUNDLE / "registration",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    for name in ("scientific001", "launch"):
        shutil.copytree(
            PRESERVED / name, BUNDLE / "evidence" / name, copy_function=os.link
        )
    for name in ("independent_review001", "development"):
        shutil.copytree(
            REPOSITORY / "experiments/adaptive_neuron_v2/results" / name,
            BUNDLE / "evidence" / name,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    for name in ("build01", "build02"):
        build = PRESERVED / "sealed-builds" / name
        runtime = BUNDLE / "runtime" / name
        runtime.mkdir(parents=True)
        binary = build / "target/release/examples/adaptive_neuron_host"
        identity = json.loads((build / "BUILD_RECEIPT.json").read_text())
        if sha(binary) != identity["binary_sha256"]:
            raise ValueError("Exact binary changed after build")
        shutil.copy2(binary, runtime / "adaptive_neuron_host")
        for filename in (
            "BUILD_RECEIPT.json",
            "Cargo.toml",
            "Cargo.lock",
            "cargo-build.log",
            "cargo-lock.log",
        ):
            shutil.copy2(build / filename, runtime / filename)
    # Rebuild inputs are included once; cached object files and compiler installs
    # are reproducible infrastructure, not scientific raw evidence.
    vendor = REPOSITORY / "experiments/free_boundary_neuron/owner/runs/build01/vendor"
    shutil.copytree(vendor, BUNDLE / "vendor", symlinks=False)
    shutil.copy2(HERE / "replay.py", BUNDLE / "replay.py")
    (BUNDLE / "README.md").write_text(
        """# Exact adaptive-neuron v2 scientific evidence

The complete 45 training fits, 2,880 native episodes, all original native audits,
checkpoints, progress, optimizer histories, streams and statistics are under
`evidence/scientific001`. All 141 registered source inputs come from commit
58c1f6caabd28ad99f2d425cfaa5c4e050f7a19a and retain their exact bytes. Two fresh
builds produced the same executable. Development receipts and negative results
remain visible. Original absolute paths in receipts are historical provenance.

On Linux x86_64 with Python 3.12 and the pinned NumPy/SciPy in
`source/experiments/adaptive_neuron_v2/requirements.txt`, run:

```sh
python3 replay.py --output /absolute/new/replay_directory
```

This verifies the manifest and source seal, copies the native evidence, reissues
only DENY_ALL local research-root permits, performs all 2,880 cold native replays,
and reconstructs the registered statistics. It must produce no new owner ticks,
no new credit records, and no change to the original archive. It costs additional
CPU time, recorded in its separate receipt. No training is repeated. Choose a
new destination outside this bundle; an existing destination is rejected.

The exact runtime is supplied; compiler installations and intermediate Cargo
objects are omitted. A checksum-verified vendor cache is included for the sealed
builder. Rebuilding requires the declared Rust 1.95.0 toolchain and a new output
root; the original build receipts state compiler/target and dependency identities.

Both registered OOD superiority claims failed their predeclared 97.5% confidence
interval criterion. Functional closure is not evidence of efficacy. Resource
work is a declared proxy, not Joules. This batch uses the original native credit
finalizer with a local research account. Authenticated LedgerWriter feedback is
a separate versioned bridge experiment and must not be attributed to this batch.

All files except MANIFEST.json are listed in MANIFEST.json. The archive checksum,
packaging and transfer costs are delivered separately to avoid self-referential
hashes. Cached build objects are not part of the scientific record.
""",
        encoding="utf-8",
    )
    files = {}
    for path in sorted(BUNDLE.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Nonportable archive symlink: {path}")
        if path.is_file():
            files[str(path.relative_to(BUNDLE))] = {
                "bytes": path.stat().st_size,
                "sha256": sha(path),
            }
    manifest = {
        "schema": "hepta.adaptive-neuron.exact-evidence-manifest.v1",
        "source_seal_sha256": sha(registration / "SOURCE_SEAL.json"),
        "files": files,
    }
    (BUNDLE / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {
        "schema": "hepta.adaptive-neuron.bundle-materialization.v1",
        "complete": True,
        "bundle": str(BUNDLE),
        "manifest_sha256": sha(BUNDLE / "MANIFEST.json"),
        "files": len(files),
        "bytes": sum(row["bytes"] for row in files.values()),
        "wall_seconds": time.perf_counter() - started,
        "parent_cpu_seconds": time.process_time() - cpu,
        "child_cpu_seconds": after.ru_utime
        + after.ru_stime
        - before.ru_utime
        - before.ru_stime,
        "scope": "Exact Git source restoration, all evidence and binary/vendor copies, complete manifest hashing. This is additional to the original science and independent reviews. Excludes interpreter startup/final receipt write; an outer receipt encloses those costs.",
    }
    with (HERE / "MATERIALIZATION.json").open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
