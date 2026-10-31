"""Real transport and process lifecycle acceptance with explicitly synthetic data.

This exercises the released queue, owned wait4, literal validator and transport.
It never opens a scientific input, invokes a scientific worker, or produces a
production PIPELINE_CONFIG/COMPLETE. Use a fresh Actions run: artifact names are
immutable and this must not share a run with the separate transport exercise.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from operational.parameter_field_recovery07 import artifact_transport as transport  # noqa: E402
from operational.parameter_field_recovery07.process import (  # noqa: E402
    EPISODE,
    descriptor,
    read,
    regular_tree,
    require,
    run_owned,
    write,
)
from operational.parameter_field_recovery07.job_queue import (  # noqa: E402
    ORDER,
    accept_ack,
    activate,
    canonical,
)
from operational.parameter_field_recovery07.supervisor import verify_literal  # noqa: E402
from operational.parameter_field_recovery07.terminal import require_measurement  # noqa: E402


def health_until(deadline):
    def health():
        require(
            time.monotonic() < deadline, "Synthetic lifecycle time budget exhausted"
        )

    return health


def owned(argv, root, name, health):
    log = root / (name + ".log")
    log.touch(exist_ok=False)
    return run_owned(
        argv,
        directory=root / "measurements" / name,
        cwd=str(root / "empty_cwd"),
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"},
        log=log,
        health=health,
        binding={"synthetic_only": True, "name": name},
    )


def source_identity():
    directory = ROOT / "operational/parameter_field_recovery07"
    return {
        path.relative_to(ROOT).as_posix(): descriptor(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file()
        and path.suffix in (".py", ".json", ".mjs")
        and "node_modules" not in path.parts
    } | {
        "operational/parameter_field_recovery06/owned_children.py": descriptor(
            ROOT / "operational/parameter_field_recovery06/owned_children.py"
        )
    }


def fixture_literal(root, source_commit):
    raw, cas = root / "raw", root / "raw_cas"
    # The real finalizer inventories the original lock files, including empty
    # files. Exercise all five permitted names without acquiring any raw lock.
    for name in (
        ".ops-controller.lock",
        ".ops-phase.lock",
        ".ops-write.lock",
        ".ops-slot-0.lock",
        ".ops-slot-1.lock",
    ):
        with (raw / name).open("xb"):
            pass
    frozen = write(
        root / "SYNTHETIC_FREEZE.json",
        {
            "synthetic_only": True,
            "scientific_source_executed": False,
            "operational_amendment_sha256": "0" * 64,
            "registered_commit": source_commit,
        },
    )
    entries = {
        p.relative_to(raw).as_posix(): {
            "bytes": descriptor(p)["bytes"],
            "sha256": descriptor(p)["sha256"],
            "storage": "direct",
            "blob": None,
        }
        for p in regular_tree(raw)
    }
    with tempfile.TemporaryDirectory(dir=root, prefix="literal-fixture-") as directory:
        restore = Path(directory)
        for name, row in entries.items():
            source, target = raw / name, restore / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            require(
                (source.stat().st_dev, source.stat().st_ino)
                != (target.stat().st_dev, target.stat().st_ino)
                and descriptor(target)["sha256"] == row["sha256"],
                "Synthetic literal copy differs",
            )
    binding = {
        "attempt_id": "attempt02",
        "source_freeze_sha256": frozen["sha256"],
        "operational_amendment_sha256": "0" * 64,
        "registered_commit": source_commit,
    }
    manifest = write(
        raw / "evidence_v2/verification07/MANIFEST.json",
        {
            "schema": "hepta.fullstudy.cas-container-manifest.1",
            "synthetic_only": True,
            "binding": binding,
            "root": str(raw),
            "cas_root": str(cas),
            "logical_paths": entries,
            "logical_artifact_count": len(entries),
            "logical_artifact_bytes": sum(row["bytes"] for row in entries.values()),
        },
    )
    write(
        raw / "evidence_v2/verification07/VERIFIED.json",
        {
            "synthetic_only": True,
            "archive_verification_complete": True,
            "binding": binding,
            "manifest": {
                **manifest,
                "path": "evidence_v2/verification07/MANIFEST.json",
            },
            "logical_files_restored": len(entries),
            "logical_bytes_restored": sum(row["bytes"] for row in entries.values()),
            "logical_paths_verified": sorted(entries),
            "temporary_directory_removed_after_success": True,
        },
    )
    verify_literal({"raw_root": str(raw), "cas_root": str(cas)}, frozen)


def stages(root):
    config = descriptor(root / "SYNTHETIC_CONFIG.json")
    health = health_until(time.monotonic() + 3600)
    done, acks, active, results = [], [], None, []

    def queue(count):
        return canonical(
            {
                "schema": "hepta.fullstudy.queue.2",
                "attempt_id": "attempt02",
                "finalize": False,
                "jobs": [
                    {"id": name, "requires": [] if index == 0 else [ORDER[index - 1]]}
                    for index, name in enumerate(ORDER[:count])
                ],
            },
            count,
        )

    registered = queue(4)

    def barrier(label):
        paths = {"control/SYNTHETIC_CONFIG.json": root / "SYNTHETIC_CONFIG.json"}
        paths.update(
            {
                "synthetic/" + path.relative_to(root).as_posix(): path
                for directory in (root / "raw", root / "measurements")
                for path in regular_tree(directory)
            }
        )
        paths.update(
            {
                f"prior_acks/{index:02d}.json": Path(row["ack"]["path"])
                for index, row in enumerate(acks, 1)
            }
        )
        binding = {
            "execution_episode": EPISODE,
            "sequence": len(acks) + 1,
            "label": label,
            "pipeline_config": config,
            "completed_jobs": list(done),
            "previous_ack": acks[-1]["ack"] if acks else None,
        }
        result = transport.archive_barrier(
            label, paths, binding, root / "barriers" / label, health_check=health
        )
        accept_ack(acks, result, config, done)
        print(
            json.dumps(
                {
                    "synthetic_stage": label,
                    "artifact_id": result["artifact"]["id"],
                    "scientific_inputs_opened": False,
                }
            ),
            flush=True,
        )

    for index, name in enumerate(ORDER):
        active = activate(registered, index + 1, done, acks, active)
        target = root / "raw" / (name + ".json")
        code = "import json,sys; from pathlib import Path; value=sum(range(10000)); Path(sys.argv[1]).write_text(json.dumps({'synthetic_only':True,'label':sys.argv[2],'value':value}))"
        result = owned(
            [sys.executable, "-B", "-c", code, str(target), name], root, name, health
        )
        require(
            result["exit_code"] == 0 and read(target).get("label") == name,
            "Synthetic child did not produce its own fixture",
        )
        results.append(result)
        done.append(name)
        barrier(name)
        if index in (2, 10):
            registered = queue(11 if index == 2 else 14)
    activate(registered, 14, done, acks, active, finalize=True)
    write(
        root / "raw/GRID.json",
        {"synthetic_only": True, "jobs": done, "actual_child_wait4": results},
    )
    barrier("controller")
    write(
        root / "raw/ANALYSIS_FIXTURE.json",
        {"synthetic_only": True, "scientific_analysis_executed": False},
    )
    barrier("analysis")
    fixture_literal(root, read(config)["source_head"])
    barrier("final_closure")
    write(
        root / "STAGES_COMPLETE.json",
        {
            "schema": "hepta.execution07.synthetic-stages.1",
            "synthetic_only": True,
            "scientific_inputs_opened": False,
            "source_files": source_identity(),
            "acks": acks,
            "actual_fixture_children": 14,
            "primary_barriers": 17,
        },
    )


def terminal_stage(root):
    stage = read(root / "STAGES_COMPLETE.json")
    outer = require_measurement(root / "measurements/STAGES")
    binding = {
        "execution_episode": EPISODE,
        "sequence": 18,
        "label": "terminal_metadata",
        "pipeline_config": descriptor(root / "SYNTHETIC_CONFIG.json"),
        "completed_jobs": ORDER,
        "previous_ack": stage["acks"][-1]["ack"],
    }
    paths = {"terminal/STAGES_COMPLETE.json": root / "STAGES_COMPLETE.json"}
    paths.update(
        {
            "terminal/" + Path(value["path"]).name: Path(value["path"])
            for value in outer.values()
        }
    )
    paths.update(
        {
            f"prior_acks/{index:02d}.json": Path(row["ack"]["path"])
            for index, row in enumerate(stage["acks"], 1)
        }
    )
    result = transport.archive_terminal_metadata(
        paths,
        binding,
        root / "terminal_archive",
        health_check=health_until(time.monotonic() + 3600),
    )
    write(root / "TERMINAL_PUBLICATION.json", result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--child", choices=("stages", "terminal"))
    args = parser.parse_args()
    root = args.output.resolve()
    if args.child:
        {"stages": stages, "terminal": terminal_stage}[args.child](root)
        return
    root.mkdir(parents=True, exist_ok=False)
    for name in ("raw", "raw_cas", "measurements", "empty_cwd"):
        (root / name).mkdir()
    sources = source_identity()
    write(
        root / "SYNTHETIC_CONFIG.json",
        {
            "schema": "hepta.execution07.synthetic-configuration.1",
            "synthetic_only": True,
            "science_admission": False,
            "source_head": os.environ["GITHUB_SHA"],
            "raw_root": str(root / "raw"),
            "source_files": sources,
        },
    )
    health = health_until(time.monotonic() + 3 * 3600)
    for mode, name in (("stages", "STAGES"), ("terminal", "TERMINAL")):
        result = owned(
            [
                sys.executable,
                "-B",
                str(Path(__file__).resolve()),
                "--output",
                str(root),
                "--child",
                mode,
            ],
            root,
            name,
            health,
        )
        require(result["exit_code"] == 0, "Synthetic lifecycle phase failed")
    require(
        source_identity() == sources,
        "Source changed during the actual lifecycle acceptance",
    )
    write(
        root / "SYNTHETIC_LIFECYCLE_PASS.json",
        {
            "schema": "hepta.execution07.synthetic-lifecycle-pass.1",
            "synthetic_only": True,
            "science_admission": False,
            "scientific_inputs_opened": False,
            "actual_fixture_children": 14,
            "primary_barriers": 17,
            "independent_terminal_barriers": 1,
            "source_files": sources,
            "stages_measurement": require_measurement(root / "measurements/STAGES"),
            "terminal_measurement": require_measurement(root / "measurements/TERMINAL"),
            "terminal_publication": descriptor(root / "TERMINAL_PUBLICATION.json"),
            "unexercised_by_this_fixture": [
                "scientific computations",
                "statistical outcomes",
                "full production registration",
            ],
        },
    )
    print(
        json.dumps(
            {
                "synthetic_lifecycle": "PASS",
                "actual_fixture_children": 14,
                "primary_barriers": 17,
                "terminal_barriers": 1,
                "science_admission": False,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
