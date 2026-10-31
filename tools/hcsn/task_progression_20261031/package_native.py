"""Archive both native qualification attempts, including the reporting failure."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile
import time


def sha(data):
    return hashlib.sha256(data).hexdigest()


def package(root, out):
    out.mkdir(parents=True, exist_ok=False)
    cpu, wall = time.process_time(), time.perf_counter()
    archives, manifests, summaries = [], {}, []
    for attempt in (1, 2):
        names = [f"confirmation{attempt:02d}", f"process{attempt:02d}"]
        members = {}
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w") as stream:
            for name in names:
                for path in sorted((root/name).rglob("*")):
                    if not path.is_file():
                        continue
                    data = path.read_bytes()
                    relative = str(path.relative_to(root))
                    # Empty stderr is still represented in the exact manifest.
                    info = tarfile.TarInfo(relative)
                    info.size, info.mode, info.mtime = len(data), 0o644, 0
                    stream.addfile(info, io.BytesIO(data))
                    members[relative] = sha(data)
        archive = out/f"native-attempt-{attempt:02d}.tar.gz"
        archive.write_bytes(gzip.compress(raw.getvalue(), mtime=0))
        with tarfile.open(archive, "r:gz") as stream:
            restored = {member.name:sha(stream.extractfile(member).read()) for member in stream.getmembers()}
        if restored != members:
            raise ArithmeticError("Archived native evidence changed")
        manifests[archive.name] = members
        report = json.loads((root/names[0]/"REPORT.json").read_text())
        process = json.loads((root/names[1]/"PROCESS.json").read_text())
        visible = out/f"attempt{attempt:02d}"
        visible.mkdir()
        for folder, filename in ((names[0], "REPORT.json"), (names[1], "PROCESS.json"), (names[1], "OUTPUT.log")):
            shutil.copyfile(root/folder/filename, visible/filename)
        rows = report["models"]
        summaries.append(dict(attempt=attempt, returncode=process["returncode"],
            source_sha256=report["source_sha256"], accepted_data=report["accepted"],
            evaluated_models=len(rows), numeric_states=512*len(rows),
            paired_episodes=sum(row["pairs"] for row in rows),
            matching_pairs=sum(row["equivalent_pairs"] for row in rows),
            reads=sum(row["actual_file_reads"] for row in rows),
            restored_rollouts=sum(row["restored_rollouts"] for row in rows),
            python_mean_cpu_seconds=sum(row["python_mean_cpu_seconds"] for row in rows)/len(rows),
            native_mean_cpu_seconds=sum(row["native_mean_cpu_seconds"] for row in rows)/len(rows),
            complete_stage_cpu_seconds=process["total_cpu_seconds"],
            complete_stage_wall_seconds=process["wall_seconds"]))
        data = archive.read_bytes()
        archives.append(dict(path=archive.name, bytes=len(data), files=len(members), sha256=sha(data)))
    (out/"ARCHIVE_MEMBERS.json.gz").write_bytes(gzip.compress(json.dumps(manifests, sort_keys=True).encode(), mtime=0))
    report = dict(schema="hepta.native-confirmation.publication.v1", attempts=summaries, archives=archives,
        independent_numeric_states=2560, independent_paired_episodes=160,
        repeated_qualification_is_not_extra_independent_evidence=True,
        original_failure="Attempt01 completed every computation and wrote the accepted-data report, then failed terminal CLI logging. Exact original source, output, process exit1 and costs are preserved.",
        repair="One print-argument line only, newly versioned and published before repeating the same cases. Attempt02 process exit0; models and four candidate packages unchanged.",
        scope="Native learned MLP and durable action owner; external content/planner/cell physics. Lifecycle costs include different durability work and are not a language speed benchmark.",
        packaging_cpu_seconds=time.process_time()-cpu, packaging_wall_seconds=time.perf_counter()-wall,
        native_physics_executed=False, main_activation=False)
    (out/"SUMMARY.json").write_text(json.dumps(report, indent=2)+"\n")
    allowed = [str(p) for p in sorted(out.rglob("*")) if p.is_file()]
    allowed.append(str(out/"PUBLISH_ALLOWLIST.json"))
    (out/"PUBLISH_ALLOWLIST.json").write_text(json.dumps(dict(paths=allowed), indent=2)+"\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    package(args.root, args.out)
