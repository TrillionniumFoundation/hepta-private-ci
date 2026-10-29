"""Execute the registered study with disjoint process-inclusive cost intervals."""

import argparse
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

from .ledger import measured_stage, sha, write_json_exclusive


def execute(module, arguments, directory):
    """Count process imports, child CPU, output I/O and failed executions."""
    started = time.perf_counter()
    before_self, before_child = (
        time.process_time(),
        resource.getrusage(resource.RUSAGE_CHILDREN),
    )
    directory.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, "-m", module, *map(str, arguments)]
    write_json_exclusive(directory / "START.json", {"command": command})
    error, code = None, None
    try:
        with (
            (directory / "stdout.log").open("xb") as out,
            (directory / "stderr.log").open("xb") as err,
        ):
            code = subprocess.run(
                command, stdout=out, stderr=err, check=False
            ).returncode
        if code:
            raise RuntimeError(f"{module} failed ({code}); preserved {directory}")
    except BaseException as caught:
        error = {"type": type(caught).__name__, "message": str(caught)}
        raise
    finally:
        child = resource.getrusage(resource.RUSAGE_CHILDREN)
        receipt = {
            "schema": "hepta.adaptive-neuron.command-cost.v2",
            "command": command,
            "complete": error is None,
            "exit_code": code,
            "error": error,
            "wall_seconds": time.perf_counter() - started,
            "parent_cpu_seconds": time.process_time() - before_self,
            "child_cpu_seconds": child.ru_utime
            + child.ru_stime
            - before_child.ru_utime
            - before_child.ru_stime,
            "scope": "Before command directory creation through subprocess exit and output-file close; includes process startup/imports, all child work and failed attempts. Subordinate timers are nested, not additional.",
            "logs": {
                name: sha(directory / name)
                for name in ("stdout.log", "stderr.log")
                if (directory / name).exists()
            },
        }
        write_json_exclusive(
            directory / ("COMPLETE.json" if error is None else "FAILED.json"), receipt
        )
    return receipt


def run(destination, source_seal, compiler, vendor_root, build_root):
    from .provenance import verify

    destination, build_root = Path(destination).resolve(), Path(build_root).resolve()
    source_seal, compiler, vendor_root = map(
        lambda p: Path(p).resolve(), (source_seal, compiler, vendor_root)
    )
    with measured_stage(
        destination,
        identity={"stage": "complete_registered_batch"},
        scope="All registered source/environment verification, two sealed builds, 45 fits, learning audits, 2880 native episodes, every native cold replay, and registered statistics. Archive transfer is separately measured after this interval.",
    ) as cost:
        source = verify(source_seal)
        build_root.mkdir(parents=True, exist_ok=False)
        costs, receipts = [], []
        for number in (1, 2):
            location = build_root / f"build{number:02d}"
            costs.append(
                execute(
                    "experiments.adaptive_neuron_v2.owner.build",
                    [
                        "--destination",
                        location,
                        "--compiler",
                        compiler,
                        "--vendor-root",
                        vendor_root,
                        "--reproducible",
                        "--source-seal",
                        source_seal,
                    ],
                    destination / "commands" / f"build{number:02d}",
                )
            )
            receipt = json.loads((location / "BUILD_RECEIPT.json").read_text())
            write_json_exclusive(destination / f"BUILD{number:02d}.json", receipt)
            receipts.append(receipt)
        if receipts[0]["binary_sha256"] != receipts[1]["binary_sha256"]:
            raise ValueError(
                "independent build directories produced different executable bytes"
            )
        binary, built = Path(receipts[0]["binary"]), destination / "BUILD01.json"
        write_json_exclusive(
            destination / "REPRODUCIBLE_BUILD.json",
            {
                "passed": True,
                "source": source,
                "binary_sha256": sha(binary),
                "build_receipts": [
                    sha(destination / f"BUILD{number:02d}.json") for number in (1, 2)
                ],
                "claim": "Exact byte identity across two fresh output directories with the declared same compiler, source, vendor and target; not across toolchain versions or architectures.",
            },
        )
        for phase in ("screening", "confirmation"):
            learning_root = destination / "learning" / phase
            costs.append(
                execute(
                    "experiments.adaptive_neuron_v2.learning.runner",
                    [
                        "--phase",
                        phase,
                        "--source-seal",
                        source_seal,
                        "--output-dir",
                        learning_root,
                    ],
                    destination / "commands" / f"train_{phase}",
                )
            )
            costs.append(
                execute(
                    "experiments.adaptive_neuron_v2.learning.audit",
                    [
                        "--root",
                        learning_root,
                        "--source-seal",
                        source_seal,
                        "--output",
                        destination / f"LEARNING_AUDIT_{phase}.json",
                    ],
                    destination / "commands" / f"audit_{phase}",
                )
            )
        confirmation = destination / "learning/confirmation"
        learning_audit = destination / "LEARNING_AUDIT_confirmation.json"
        native_root, audit_root = destination / "raw/native", destination / "raw/audit"
        costs.append(
            execute(
                "experiments.adaptive_neuron_v2.deployment",
                [
                    "run",
                    "--binary",
                    binary,
                    "--training",
                    confirmation,
                    "--learning-audit",
                    learning_audit,
                    "--destination",
                    native_root,
                    "--source-seal",
                    source_seal,
                    "--build-receipt",
                    built,
                ],
                destination / "commands/native_run",
            )
        )
        costs.append(
            execute(
                "experiments.adaptive_neuron_v2.deployment",
                [
                    "audit",
                    "--binary",
                    binary,
                    "--training",
                    confirmation,
                    "--learning-audit",
                    learning_audit,
                    "--root",
                    native_root,
                    "--destination",
                    audit_root,
                    "--source-seal",
                    source_seal,
                ],
                destination / "commands/native_audit",
            )
        )
        costs.append(
            execute(
                "experiments.adaptive_neuron_v2.statistics",
                [
                    "--root",
                    native_root,
                    "--audit-root",
                    audit_root,
                    "--destination",
                    destination / "statistics",
                    "--source-seal",
                    source_seal,
                ],
                destination / "commands/statistics",
            )
        )
        for name, path in (
            ("NATIVE_INDEX.json", native_root / "INDEX.json"),
            ("NATIVE_AUDIT_INDEX.json", audit_root / "INDEX.json"),
        ):
            write_json_exclusive(destination / name, json.loads(path.read_text()))
        if verify(source_seal) != source:
            raise ValueError("registered source identity changed during the batch")
        cost.update(
            source=source,
            binary_sha256=sha(binary),
            scientific_fits=45,
            native_episodes=2880,
            independent_native_replay_episodes=2880,
            disjoint_subprocess_cpu_seconds=sum(
                row["parent_cpu_seconds"] + row["child_cpu_seconds"] for row in costs
            ),
            disjoint_subprocess_wall_seconds=sum(row["wall_seconds"] for row in costs),
            statistics_sha256=sha(destination / "statistics/STATISTICS.json"),
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("destination", "source-seal", "compiler", "vendor-root", "build-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(
        args.destination,
        args.source_seal,
        args.compiler,
        args.vendor_root,
        args.build_root,
    )


if __name__ == "__main__":
    main()
