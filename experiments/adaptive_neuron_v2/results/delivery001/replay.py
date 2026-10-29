"""Verify and replay the exact archived batch in a new local research directory."""

from pathlib import Path
import argparse
import hashlib
import json
import resource
import shutil
import sys
import time


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def main():
    started = time.perf_counter()
    cpu = time.process_time()
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bundle = Path(__file__).resolve().parent
    sys.dont_write_bytecode = True
    output = args.output.resolve()
    if output.is_relative_to(bundle) or output.exists():
        raise ValueError("Choose a new output directory outside the immutable bundle")
    output.mkdir(parents=True, exist_ok=False)
    write(output / "START.json", {"bundle": str(bundle), "output": str(output)})
    passed = False
    facts = {}
    try:
        manifest_path = bundle / "MANIFEST.json"
        manifest = json.loads(manifest_path.read_text())
        present = {
            str(path.relative_to(bundle))
            for path in bundle.rglob("*")
            if path.is_file() and path != manifest_path
        }
        if present != set(manifest["files"]):
            raise ValueError("Archive file roster differs from its complete manifest")
        for relative, identity in manifest["files"].items():
            path = bundle / relative
            if path.is_symlink() or not path.resolve().is_relative_to(bundle):
                raise ValueError(f"Invalid archive member: {relative}")
            if (
                path.stat().st_size != identity["bytes"]
                or digest(path) != identity["sha256"]
            ):
                raise ValueError(f"Archive identity mismatch: {relative}")
        facts["manifest_sha256"] = digest(manifest_path)
        facts["archive_files_verified"] = len(manifest["files"])
        sys.path.insert(0, str(bundle / "source"))
        from experiments.adaptive_neuron_v2 import deployment, provenance, statistics
        from experiments.adaptive_neuron_v2.owner.common import permit

        source_seal = bundle / "registration/SOURCE_SEAL.json"
        facts["source"] = provenance.verify(source_seal)
        science = bundle / "evidence/scientific001"
        original = science / "raw/native"
        working = output / "native"
        shutil.copytree(original, working)
        relocations = []
        for organ in sorted((working / "organs").iterdir()):
            local_permit = organ / "RESEARCH_PERMIT.json"
            previous = json.loads(local_permit.read_text())
            if (
                previous.get("external_effects") is not False
                or previous.get("production_authority") is not False
            ):
                raise ValueError(
                    "Only a local, DENY_ALL research scope may be relocated"
                )
            old_hash = digest(local_permit)
            local_permit.unlink()
            permit(organ)
            relocations.append(
                {
                    "organ": organ.name,
                    "original_sha256": old_hash,
                    "local_sha256": digest(local_permit),
                }
            )
        write(
            output / "RELOCATION.json",
            {
                "scope": "Only copied local research-root permits are reissued for this explicitly requested replay. Original archive bytes, task streams, identities, checkpoints, credit, and authority are unchanged.",
                "permits": relocations,
            },
        )
        binary = bundle / "runtime/build01/adaptive_neuron_host"
        result = deployment.audit_batch(
            binary,
            science / "learning/confirmation",
            working,
            output / "audit",
            source_seal,
            science / "LEARNING_AUDIT_confirmation.json",
        )
        replay_statistics = statistics.summarize(
            working, output / "audit", output / "statistics", source_seal
        )
        original_statistics = json.loads(
            (science / "statistics/STATISTICS.json").read_text()
        )
        for key in (
            "episodes",
            "organs",
            "independent_seeds",
            "primary_contrasts",
            "descriptive_summaries",
            "seed_means",
            "trajectory_changes",
            "execution_work",
        ):
            if replay_statistics[key] != original_statistics[key]:
                raise ValueError(f"Relocation changed a scientific conclusion: {key}")
        for relative, identity in manifest["files"].items():
            if digest(bundle / relative) != identity["sha256"]:
                raise ValueError(f"Replay modified the original archive: {relative}")
        facts.update(
            {
                "passed": result["passed"],
                "organs": len(result["organs"]),
                "episodes": sum(row["episode_count"] for row in result["organs"]),
                "original_archive_unchanged": True,
                "scientific_results_unchanged": True,
                "replay_work": replay_statistics["independent_replay_work"],
            }
        )
        passed = True
    except Exception as error:
        facts["error"] = repr(error)
        raise
    finally:
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        write(
            output / ("COMPLETE.json" if passed else "FAILED.json"),
            {
                "schema": "hepta.adaptive-neuron.portable-replay.v1",
                "complete": passed,
                "facts": facts,
                "wall_seconds": time.perf_counter() - started,
                "parent_cpu_seconds": time.process_time() - cpu,
                "child_cpu_seconds": after.ru_utime
                + after.ru_stime
                - children.ru_utime
                - children.ru_stime,
                "scope": "Manifest verification, new-root copy, research-permit relocation, full 2880-episode native cold replay, statistical reconstruction and final immutable-file checks. Excludes interpreter startup and final receipt write; an outer launch receipt encloses those costs. No new training or owner ticks.",
            },
        )


if __name__ == "__main__":
    main()
