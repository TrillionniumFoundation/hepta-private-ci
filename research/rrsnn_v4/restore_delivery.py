"""Restore verified local Git blobs and both raw archives; run read-only checks only."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
ELFS = {"rrsnn_v4/" + p for p in (
    "hepta/native_build/target/release/rrsnn-native-owner",
    "hepta/native_build/target/release/rrsnn-native-bootstrap-repair",
    "hepta/crate_validation_build/bin/hepta-neuron-unit-tests",
    "hepta/rr_bridge_build/bin/rrsnn-rr-feature-broker")}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key: " + key)
        result[key] = value
    return result


def parse(data):
    return json.loads(data, object_pairs_hook=unique_object)


def hex_id(value, length):
    return isinstance(value, str) and len(value) == length and all(c in "0123456789abcdef" for c in value)


def safe_name(name):
    require(isinstance(name, str) and name and not any(c in name for c in "\\\0:"), "Unsafe path")
    require(all(p not in ("", ".", "..") for p in name.split("/")), "Unsafe path: " + name)
    return name


def regular_mode(mode):
    require(stat.S_IFMT(mode) in (0, stat.S_IFREG) and not mode & 0o7000, "Nonregular or special permissions")
    return mode & 0o777


def place(destination, name, data, mode, counts):
    target = destination / safe_name(name)
    target.parent.mkdir(parents=True, exist_ok=True)
    require(not any(p.is_symlink() for p in (target, *target.parents)), "Symlink destination")
    if target.exists():
        require(target.is_file() and target.read_bytes() == data, "Conflicting existing member: " + name)
        require(stat.S_IMODE(target.stat().st_mode) == mode, "Conflicting member permissions: " + name)
        counts["identical_existing"] += 1
    else:
        with target.open("xb") as stream:
            stream.write(data)
        target.chmod(mode)
        counts["files_created"] += 1
    counts["members_verified"] += 1
    counts["bytes_verified"] += len(data)


def counters():
    return dict(files_created=0, identical_existing=0, members_verified=0, bytes_verified=0)


def restore_archive(path, kind, destination, elf_modes):
    before = file_sha(path)
    counts = counters()
    metadata = ["RAW_MANIFEST_" + kind + ".json", "RESTORE_" + kind + ".txt"]
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [safe_name(i.filename) for i in infos]
        require(len(names) == len(set(names)), "Duplicate ZIP member")
        manifest_bytes = archive.read(metadata[0])
        manifest = parse(manifest_bytes)
        require(manifest["schema"] == "rrsnn-v4-raw-evidence-archive-1" and manifest["kind"] == kind
                and manifest["root_prefix"] == "rrsnn_v4", "Wrong archive schema/kind/prefix")
        entries = manifest["files"]
        index = {safe_name(e["path"]): e for e in entries}
        require(len(index) == len(entries) == manifest["raw_files"], "Duplicate/count mismatch in manifest")
        require(all(n.startswith("rrsnn_v4/") for n in index), "Raw member outside package")
        require(set(names) == set(index) | set(metadata), "Missing/extra ZIP member")
        require(sum(e["bytes"] for e in entries) == manifest["raw_bytes"], "Manifest byte total mismatch")
        for info in infos:
            mode = regular_mode(info.external_attr >> 16)
            require(not info.is_dir() and not info.flag_bits & 1, "Directory/encrypted member")
            data = archive.read(info)
            if info.filename in index:
                e = index[info.filename]
                require(type(e["bytes"]) is int and e["bytes"] >= 0 and hex_id(e["sha256"], 64), "Invalid member metadata")
                require(len(data) == info.file_size == e["bytes"] and sha(data) == e["sha256"], "Member mismatch: " + info.filename)
            if data.startswith(b"\x7fELF"):
                require(info.filename in ELFS and mode & 0o111, "Unexpected/nonexecutable ELF")
                elf_modes[info.filename] = oct(mode)
            place(destination, info.filename, data, mode, counts)
        metadata_hashes = {n: sha(archive.read(n)) for n in metadata}
    require(file_sha(path) == before, "Archive changed while restoring")
    return dict(path=str(path), archive_sha256=before, manifest_sha256=sha(manifest_bytes),
                metadata_sha256=metadata_hashes, source_commit=manifest["source_commit"],
                published_paths_sha256=manifest["published_paths_sha256"], counts=counts)


def snapshot(destination):
    result = {}
    for path in (destination, *sorted(destination.rglob("*"))):
        s = path.lstat()
        require(stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode), "Nonregular restored object")
        entry = ["directory"] if stat.S_ISDIR(s.st_mode) else ["file", file_sha(path), s.st_size]
        result[str(path.relative_to(destination))] = entry + [stat.S_IMODE(s.st_mode), s.st_mtime_ns, s.st_ctime_ns]
    return result


WRAPPER = """import importlib.util,json,pathlib,runpy,sys
name=sys.argv[1]; expected=pathlib.Path(sys.argv[2])/(name.rsplit('.',1)[1]+'.py')
spec=importlib.util.find_spec(name)
if spec is None or pathlib.Path(spec.origin).resolve()!=expected: raise RuntimeError('Wrong module origin')
print(json.dumps({'resolved_module_file':spec.origin}),flush=True)
sys.argv=[name,'--verify-only']; namespace=runpy.run_module(name,run_name='__main__')
if pathlib.Path(namespace['__file__']).resolve()!=expected: raise RuntimeError('Wrong executed module')
print(json.dumps({'executed_module_file':namespace['__file__']}),flush=True)
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("core-archive", "resources-archive", "published-paths", "source-commit", "destination", "receipt"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    destination, receipt = Path(args.destination).absolute(), Path(args.receipt).absolute()
    require(destination.parent.is_dir() and destination.parent.resolve() == destination.parent, "Destination needs an existing nonsymlink parent")
    require(not destination.exists() and not destination.is_symlink(), "Destination must be new")
    require(ROOT not in destination.parents, "Restore outside source tree")
    require(receipt.parent.is_dir() and receipt.parent.resolve() == receipt.parent, "Receipt needs an existing nonsymlink parent")
    require(receipt != destination and destination not in receipt.parents and not receipt.exists() and not receipt.is_symlink(), "Receipt must be new and outside restored tree")
    record = dict(schema="rrsnn-v4-delivery-restoration-1", started_at_utc=datetime.now(timezone.utc).isoformat(),
        source_root=str(ROOT), destination=str(destination), executable=sys.executable, commands=[],
        source_commit=args.source_commit, restore_script_sha256=file_sha(Path(__file__)),
        scope="Same-environment new-directory restoration from locally available files whose Git blobs match a supplied independently remote-verified map; not a fresh remote download, new-environment rebuild, retraining, actor run, or production qualification.",
        archive_commit_scope="Archive commits are historical minimum evidence snapshots and may precede the final supplied source commit.",
        source_permissions_scope="Local ordinary source permissions are copied; the supplied Git blob map verifies content, not Git tree modes.")
    with receipt.open("x") as output:
        try:
            require(hex_id(args.source_commit, 40), "Immutable 40-character source commit required")
            source_map_path = Path(args.published_paths).resolve(strict=True)
            source_bytes = source_map_path.read_bytes()
            published = parse(source_bytes)
            require(isinstance(published, dict) and published and all(hex_id(v, 40) for v in published.values()), "Invalid published Git blob map")
            required_sources = {"__init__.py", "restore_delivery.py", "build_closeout.py", "delivery_behavior_diagnostic.py"}
            require(required_sources <= published.keys(), "Publication map must cover all executed restoration/verification sources")
            record["published_paths"] = dict(path=str(source_map_path), sha256=sha(source_bytes), entries=len(published))
            destination.mkdir(mode=0o700)
            copied = record["git_backed_files"] = counters()
            for name, expected in sorted(published.items()):
                source = ROOT / safe_name(name)
                require(not any(p.is_symlink() for p in (source, *source.parents)) and source.is_file(), "Nonregular source: " + name)
                data = source.read_bytes()
                blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
                require(blob == expected, "Published Git blob mismatch: " + name)
                place(destination, "rrsnn_v4/" + name, data, regular_mode(source.stat().st_mode), copied)
            record["archives"], elf_modes = {}, {}
            for kind in ("core", "resources"):
                path = Path(getattr(args, kind + "_archive")).resolve(strict=True)
                record["archives"][kind] = restore_archive(path, kind, destination, elf_modes)
            require(set(elf_modes) == ELFS, "The four preserved executable ELF members are required")
            record["preserved_elf_permissions"] = elf_modes
            require(file_sha(source_map_path) == sha(source_bytes), "Source map changed")
            before = snapshot(destination)
            file_count = sum(entry[0] == "file" for entry in before.values())
            require(copied["files_created"] + sum(a["counts"]["files_created"] for a in record["archives"].values()) == file_count, "Restored file count mismatch")
            record.update(restored_files=file_count, restored_objects=len(before))
            record["restored_tree_fingerprint_sha256"] = sha(json.dumps(before, sort_keys=True).encode())
            env = dict(os.environ, PYTHONPATH=str(destination), PYTHONDONTWRITEBYTECODE="1", PYTHONOPTIMIZE="0")
            for module in ("rrsnn_v4.build_closeout", "rrsnn_v4.delivery_behavior_diagnostic"):
                command = [sys.executable, "-c", WRAPPER, module, str(destination / "rrsnn_v4")]
                item = dict(command=command, cwd=str(destination), module=module)
                record["commands"].append(item)
                result = subprocess.run(command, cwd=destination, env=env, capture_output=True, text=True, timeout=600)
                item.update(exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr,
                            restored_tree_unchanged=snapshot(destination) == before)
                require(item["restored_tree_unchanged"], "Read-only verifier changed restored files")
            require(all(c["exit_code"] == 0 for c in record["commands"]), "A read-only verification failed")
            record["result_files_not_rewritten"] = True
            record["status"] = "passed"
        except Exception as error:
            record.update(status="failed", error=type(error).__name__ + ": " + str(error))
            raise
        finally:
            record["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
            json.dump(record, output, indent=2, ensure_ascii=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
    print(json.dumps({"receipt":str(receipt), "receipt_sha256":file_sha(receipt), "status":record["status"]}))


if __name__ == "__main__":
    main()
