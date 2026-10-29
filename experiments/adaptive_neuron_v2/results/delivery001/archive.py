"""Archive complete immutable evidence and all new portable-replay observations."""

from pathlib import Path
import hashlib
import json
import tarfile

from experiments.adaptive_neuron_v2.ledger import measured_stage


def sha(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main():
    here = Path(__file__).resolve().parent
    repository = here.parents[3]
    deliverables = repository.parent / "deliverables"
    bundle = deliverables / "hepta_adaptive_neuron_v2_exact_evidence"
    replay = deliverables / "hepta_adaptive_neuron_v2_portable_replay001"
    archive = deliverables / "hepta_adaptive_neuron_v2_complete.tar.gz"
    prefix = "hepta_adaptive_neuron_v2"
    with measured_stage(
        here / "archive001",
        identity={"stage": "complete_evidence_archive"},
        scope="Complete file inventory, SHA-256 manifest, archive compression, archive SHA and independent per-member archive byte verification. Includes all delivery attempts and replay receipts available before archiving; this stage's final cost and upload are external receipts to avoid self-referential hashes.",
    ) as facts:
        files = {}
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                files[f"{prefix}/exact_evidence/{path.relative_to(bundle)}"] = path
        for path in sorted(replay.rglob("*")):
            if path.is_file() and not path.is_relative_to(replay / "native"):
                files[f"{prefix}/portable_replay001/{path.relative_to(replay)}"] = path
        for path in sorted(here.rglob("*")):
            if (
                path.is_file()
                and "__pycache__" not in path.parts
                and not path.is_relative_to(here / "archive001")
            ):
                files[f"{prefix}/delivery/{path.relative_to(here)}"] = path
        report = repository / "experiments/adaptive_neuron_v2/RESULTS.md"
        files[f"{prefix}/RESULTS.md"] = report
        formatted = (
            repository
            / "experiments/adaptive_neuron_v2/results/independent_review001/FORMAT_PROVENANCE.json"
        )
        files[f"{prefix}/delivery/FORMAT_PROVENANCE.json"] = formatted
        identities = {
            relative: {"bytes": path.stat().st_size, "sha256": sha(path)}
            for relative, path in files.items()
        }
        manifest_path = here / "archive001/ARCHIVE_MANIFEST.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema": "hepta.adaptive-neuron.archive-manifest.v1",
                    "files": identities,
                    "scope": "All natural scientific raw files are included. Portable replay's unchanged working copy is represented by the exact original native directory and its explicit permit relocation map; every new replay audit, statistic and RPC observation is included. Reproducible intermediate Cargo objects and compiler installs are omitted.",
                },
                sort_keys=True,
                indent=2,
            )
            + "\n"
        )
        files[f"{prefix}/ARCHIVE_MANIFEST.json"] = manifest_path
        if archive.exists():
            raise FileExistsError(archive)
        with tarfile.open(archive, "w:gz", compresslevel=6, dereference=True) as output:
            for relative, path in files.items():
                output.add(path, arcname=relative, recursive=False)
        verified = set()
        with tarfile.open(archive, "r:gz") as source:
            for member in source:
                if (
                    not member.isfile()
                    or member.name not in files
                    or member.name in verified
                ):
                    raise ValueError(
                        "Unexpected, duplicate, or nonregular archive member"
                    )
                expected = identities.get(member.name)
                if expected is None:
                    expected = {
                        "bytes": manifest_path.stat().st_size,
                        "sha256": sha(manifest_path),
                    }
                stream = source.extractfile(member)
                value = hashlib.sha256()
                count = 0
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    value.update(block)
                    count += len(block)
                if (
                    count != expected["bytes"]
                    or value.hexdigest() != expected["sha256"]
                ):
                    raise ValueError(f"Archive bytes differ: {member.name}")
                verified.add(member.name)
        if verified != set(files):
            raise ValueError("Incomplete archive")
        facts.update(
            {
                "archive": str(archive),
                "archive_bytes": archive.stat().st_size,
                "archive_sha256": sha(archive),
                "members_verified": len(verified),
                "content_bytes": sum(row["bytes"] for row in identities.values()),
                "manifest_sha256": sha(manifest_path),
                "immutable_bundle_manifest_sha256": sha(bundle / "MANIFEST.json"),
                "portable_replay_complete_sha256": sha(replay / "COMPLETE.json"),
            }
        )
        print(json.dumps(facts))


if __name__ == "__main__":
    main()
