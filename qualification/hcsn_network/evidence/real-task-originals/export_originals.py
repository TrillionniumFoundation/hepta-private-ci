"""Retain exact completed campaign originals in verified, lossless Git parts."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
import time


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, allow_nan=False)+"\n").encode()


def main():
    parser = argparse.ArgumentParser()
    for name in ("campaign", "profile", "data", "dataset-zip", "console-prefix", "archive", "output"):
        parser.add_argument("--"+name, required=True)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    repository = Path(__file__).resolve().parents[4]
    namespace = repository/"qualification/hcsn_network"
    protocol_path = namespace/"PROTOCOL.json"
    protocol = json.loads(protocol_path.read_text())
    if sha(protocol_path.read_bytes()) != "9601216e77b3dc5b3b41f77d7df8f124b7ab176692b0a0b66f24773b95eec9e0":
        raise ValueError("original protocol changed")
    campaign, profile, output = Path(args.campaign), Path(args.profile), Path(args.output)
    complete = json.loads((campaign/"COMPLETE.json").read_text())
    if (complete["fit_children"], complete["evaluation_children"], complete["fit_failures"], complete["evaluation_failures"]) != (30, 30, 0, 0):
        raise ValueError("cannot package an incomplete campaign as complete")
    output.mkdir(parents=True, exist_ok=False)
    archive = Path(args.archive)
    if archive.exists():
        raise FileExistsError("archive already exists")
    files = {}
    def add(name, path):
        if name in files or path.is_symlink() or not path.is_file():
            raise ValueError("duplicate, symbolic, or absent original: "+name)
        files[name] = path
    for prefix, directory in (("campaign", campaign), ("length-profile", profile),
                              ("benchmark-review", namespace/"evidence/benchmark-review"),
                              ("length-review", namespace/"evidence/length-review"),
                              ("campaign-static-review", namespace/"evidence/campaign-static-review")):
        for path in sorted(directory.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                add(prefix+"/"+path.relative_to(directory).as_posix(), path)
    for name, expected in protocol["sources"].items():
        path = repository/name
        if sha(path.read_bytes()) != expected:
            raise ValueError("frozen source changed: "+name)
        add("frozen-source/"+name, path)
    add("frozen-source/PROTOCOL.json", protocol_path)
    for name, expected in protocol["data_sha256"].items():
        path = Path(args.data)/name
        if sha(path.read_bytes()) != expected:
            raise ValueError("original UCI data changed: "+name)
        add("data/"+name, path)
    add("data/pendigits.names", Path(args.data)/"pendigits.names")
    add("data/original-uci-distribution.zip", Path(args.dataset_zip))
    if sha(Path(args.dataset_zip).read_bytes()) != protocol["dataset_zip_sha256"]:
        raise ValueError("original UCI ZIP changed")
    for suffix in ("stdout", "stderr"):
        add("execution-console/controller."+suffix, Path(args.console_prefix+"."+suffix))
    add("export-source/export_originals.py", Path(__file__))
    manifest = {"identity": "hcsn-coupled-pendigits-originals-20261119-d741-attempt001",
                "source_commit": "8fe7bc209803659cc3f4780be0940c5183ca6e9b",
                "protocol_sha256": sha(protocol_path.read_bytes()),
                "new_model_calls": 0, "new_optimizer_calls": 0, "new_matrix_actions": 0,
                "files": []}
    for name, path in sorted(files.items()):
        data = path.read_bytes()
        manifest["files"].append({"path": name, "original_path": str(path), "bytes": len(data),
                                   "sha256": sha(data)})
    manifest["file_count"] = len(files)
    manifest["original_bytes"] = sum(row["bytes"] for row in manifest["files"])
    manifest_bytes = encoded(manifest)
    (output/"MANIFEST.json").write_bytes(manifest_bytes)
    def put(tar, name, data):
        info = tarfile.TarInfo(name)
        info.size, info.mode, info.mtime = len(data), 0o644, 0
        info.uid, info.gid, info.uname, info.gname = 0, 0, "", ""
        tar.addfile(info, io.BytesIO(data))
    with tarfile.open(archive, "w:xz", preset=3) as tar:
        put(tar, "MANIFEST.json", manifest_bytes)
        for row in manifest["files"]:
            data = files[row["path"]].read_bytes()
            if sha(data) != row["sha256"]:
                raise ValueError("original changed during archiving: "+row["path"])
            put(tar, row["path"], data)
    expected = {row["path"]: row for row in manifest["files"]}
    with tarfile.open(archive, "r:xz") as tar:
        members = tar.getmembers()
        if len(members) != len(files)+1 or {m.name for m in members} != {*files, "MANIFEST.json"}:
            raise ValueError("archive roster mismatch")
        if tar.extractfile("MANIFEST.json").read() != manifest_bytes:
            raise ValueError("archived manifest mismatch")
        for member in members:
            if not member.isfile():
                raise ValueError("nonregular archive member")
            if member.name == "MANIFEST.json":
                continue
            data = tar.extractfile(member).read()
            if len(data) != expected[member.name]["bytes"] or sha(data) != expected[member.name]["sha256"]:
                raise ValueError("archive member differs: "+member.name)
    data, parts, reconstructed = archive.read_bytes(), [], hashlib.sha256()
    for index, offset in enumerate(range(0, len(data), 4*1024**2)):
        block = data[offset:offset+4*1024**2]
        name = f"part-{index:03}.tar.xz.part"
        with (output/name).open("xb") as handle:
            handle.write(block)
        restored = (output/name).read_bytes()
        reconstructed.update(restored)
        parts.append({"path": name, "bytes": len(restored), "sha256": sha(restored),
                      "git_blob_sha1": hashlib.sha1(b"blob "+str(len(restored)).encode()+b"\0"+restored).hexdigest()})
    if reconstructed.hexdigest() != sha(data):
        raise ValueError("ordered archive part reconstruction differs")
    for row in manifest["files"]:
        if sha(files[row["path"]].read_bytes()) != row["sha256"]:
            raise ValueError("original changed after archive: "+row["path"])
    result = {"status": "COMPLETE_EXACT_ARCHIVE_READBACK", "archive_bytes": len(data),
              "archive_sha256": sha(data), "members": len(files)+1, "original_files": len(files),
              "original_bytes": manifest["original_bytes"], "manifest_sha256": sha(manifest_bytes),
              "parts": parts, "new_model_calls": 0, "new_optimizer_calls": 0, "new_matrix_actions": 0,
              "body_wall_seconds": time.perf_counter()-started, "body_cpu_seconds": time.process_time()-cpu,
              "body_excludes_imports_and_final_result_write": True,
              "model_source_files_unchanged": len(protocol["sources"])}
    (output/"ARCHIVE.json").write_bytes(encoded(result))
    print(json.dumps({k: v for k, v in result.items() if k != "parts"}), flush=True)


if __name__ == "__main__":
    main()
