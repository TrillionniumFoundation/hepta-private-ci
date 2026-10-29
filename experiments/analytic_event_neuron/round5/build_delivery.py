"""Package restored Round5 bytes backed by an independently verified Git index."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
import time


PREFIX = "experiments/analytic_event_neuron/round5/"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git_digest(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def build(repo, index_path, output, receipt_path):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    repo, output, receipt_path = repo.resolve(), output.resolve(), receipt_path.resolve()
    if (output.exists() or receipt_path.exists() or output == receipt_path
            or output.is_relative_to(repo) or receipt_path.is_relative_to(repo)):
        raise ValueError("New output and receipt paths outside the source snapshot are required")
    index = json.loads(index_path.read_text())
    if not index.get("remote_verified") or not index.get("original_blobs_preserved"):
        raise ValueError("A separately verified source index is required")
    blobs, archived = index["blobs"], {}
    targets = {"selection_smoke_001": "evidence/selection_smoke_001",
               "selection_prepared_001": "evidence/selection_registered_001/prepared",
               "selection_confirmation_001": "evidence/selection_registered_001/confirmation",
               "figures_001": "figures"}
    for envelope, target in targets.items():
        path = PREFIX + "evidence/envelopes/" + envelope + "/MANIFEST.json"
        raw = (repo / path).read_bytes()
        if git_digest(raw) != blobs[path]["sha"]:
            raise ValueError("An archive manifest is detached from the verified Git snapshot")
        manifest = json.loads(raw)
        for member in manifest["members"]:
            archived[PREFIX + target + "/" + member["path"]] = {
                **member, "origin": "restored_archive", "manifest": path,
                "manifest_sha256": digest(raw)}
    selected, excluded = [], []
    for path in sorted(repo.rglob("*")):
        if not path.is_file():
            continue
        name = path.relative_to(repo).as_posix()
        if ("__pycache__" in path.parts or path.suffix == ".pyc" or ".git" in path.parts
                or name.startswith(PREFIX + "evidence/delivery/")
                or (name.startswith(PREFIX + "evidence/envelopes/") and path.name != "MANIFEST.json")):
            continue
        if path.is_symlink():
            raise ValueError("Symlinks are outside the research delivery contract")
        raw, origin = path.read_bytes(), None
        if name in blobs:
            record = blobs[name]
            if git_digest(raw) != record["sha"] or len(raw) != record["size"]:
                raise ValueError("Local source differs from verified Git bytes: " + name)
            if record["mode"] not in ("100644", "100755"):
                raise ValueError("Unsupported Git file mode: " + name)
            origin = {"origin": "git_blob", "git_blob_sha1": record["sha"], "mode": record["mode"]}
        elif name in archived:
            record = archived[name]
            if digest(raw) != record["sha256"] or len(raw) != record["bytes"]:
                raise ValueError("Restored bytes differ from their published manifest: " + name)
            origin = {key: record[key] for key in ("origin", "manifest", "manifest_sha256")}
            origin["mode"] = "100644"
        if origin is None:
            if name.startswith(PREFIX):
                raise ValueError("Unpublished Round5 file would enter the delivery: " + name)
            excluded.append(name)
            continue
        selected.append({"path": name, "bytes": len(raw), "sha256": digest(raw), **origin})
    selected_names = {item["path"] for item in selected}
    if not set(archived).issubset(selected_names):
        raise ValueError("A restored original archive member is missing")
    frozen = json.loads((repo / (PREFIX + "evidence/selection_registered_001/FREEZE.json")).read_text())
    required = set(frozen["sources_sha256"]) | {"LICENSE", "NOTICE",
        "experiments/analytic_event_neuron/round4/evidence/FREEZE.json",
        "experiments/analytic_event_neuron/round4/evidence/execute.py"}
    required |= {name for name in blobs if name.startswith(PREFIX)
                 and not name.startswith(PREFIX + "evidence/delivery/")
                 and not (name.startswith(PREFIX + "evidence/envelopes/") and not name.endswith("/MANIFEST.json"))}
    actual_hashes = {row["path"]: row["sha256"] for row in selected}
    if not required.issubset(selected_names) or any(actual_hashes.get(path) != value for path, value in frozen["sources_sha256"].items()):
        raise ValueError("A required research source or published record is missing or changed")
    contents = {"schema": "hepta.analytic-event.research-delivery-contents.v1",
                "source_commit": index["commit"], "source_tree": index["tree"],
                "supplied_verified_index_sha256": digest(index_path.read_bytes()),
                "scope": "Complete new Round5 research with restored raw data, available inherited source/reference files and original license notices; not a complete repository or original Round4 final bundle.",
                "files": selected, "excluded_unbacked_non_round5_files": excluded,
                "encoded_archive_chunks_omitted": "Original members are already restored; their published manifests are retained.",
                "production_promotion": False}
    contents_bytes = (json.dumps(contents, indent=2, sort_keys=True) + "\n").encode()
    start = ("# Hepta Round5 research delivery\n\n"
             "Open [the Chinese acceptance report](experiments/analytic_event_neuron/round5/ACCEPTANCE.md) "
             "and [reproduction instructions](experiments/analytic_event_neuron/round5/REPRODUCTION.md).\n\n"
             "The raw prepared and confirmation directories are already restored. "
             "The two range-expansion comparisons and all eight joint scientific gates failed. "
             "Interface tests and independent numerical verification passed; production promotion remains false.\n\n"
             "Source commit: `" + index["commit"] + "`. Every delivered source byte is bound to that verified Git index "
             "or an original member of one of its published evidence archives.\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "x:xz", preset=6) as archive:
        for name, raw in (("DELIVERY_CONTENTS.json", contents_bytes), ("START_HERE.md", start)):
            info = tarfile.TarInfo("hepta-round5-research/" + name)
            info.size, info.mode, info.mtime = len(raw), 0o644, 0
            archive.addfile(info, io.BytesIO(raw))
        for row in selected:
            raw = (repo / row["path"]).read_bytes()
            if digest(raw) != row["sha256"]:
                raise ValueError("Source changed while packaging: " + row["path"])
            info = tarfile.TarInfo("hepta-round5-research/" + row["path"])
            info.size, info.mode, info.mtime = len(raw), int(row["mode"][-3:], 8), 0
            archive.addfile(info, io.BytesIO(raw))
    expected = {"hepta-round5-research/" + row["path"]: row for row in selected}
    expected.update({"hepta-round5-research/DELIVERY_CONTENTS.json": {"bytes": len(contents_bytes), "sha256": digest(contents_bytes)},
                     "hepta-round5-research/START_HERE.md": {"bytes": len(start), "sha256": digest(start)}})
    checked = set()
    with tarfile.open(output, "r:xz") as archive:
        for member in archive:
            if not member.isfile() or member.name not in expected or member.name in checked:
                raise ValueError("Unexpected delivery member")
            raw = archive.extractfile(member).read()
            if len(raw) != expected[member.name]["bytes"] or digest(raw) != expected[member.name]["sha256"]:
                raise ValueError("Delivery member mismatch: " + member.name)
            checked.add(member.name)
    if checked != set(expected):
        raise ValueError("Incomplete delivery archive")
    with output.open("rb") as stream:
        archive_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    receipt = {"schema": "hepta.analytic-event.research-delivery.v1", "archive": output.name,
               "archive_bytes": output.stat().st_size, "archive_sha256": archive_digest,
               "source_commit": index["commit"], "source_tree": index["tree"],
               "contents_manifest_sha256": digest(contents_bytes), "source_files": len(selected),
               "archive_members": len(checked), "source_original_bytes": sum(row["bytes"] for row in selected),
               "all_archive_member_bytes_verified": True, "all_sources_git_or_published_archive_bound": True,
               "builder_sha256": digest(Path(__file__).read_bytes()),
               "wall_ns": time.perf_counter_ns() - started, "parent_cpu_ns": time.process_time_ns() - cpu,
               "production_promotion": False}
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    with receipt_path.open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--verified-source-index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.repository, args.verified_source_index, args.output, args.receipt)))


if __name__ == "__main__":
    main()
