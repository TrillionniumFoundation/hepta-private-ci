"""Create-only raw export after root has confirmed both writers terminal.

No experiment, model, verifier or C access. Whole ZIP/index are transport objects.
Terminal observations plus byte rechecks are not a filesystem atomic snapshot.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import time
import traceback
import zipfile

PART, LIMIT = 322560, 512000
DEV, DIAG = "qwen-e1e2-development-01", "qwen-postrun-diagnostic-01"
HELPERS = {
    "qwen_development_io_v3.py": "3ae5f7ba07cc2b116e3e181669410cbcfe30b9a69db2cc57bf3b8f009d6c957e",
    "qwen_development_inputs_v3.py": "baa7eb6acb8ca63293a6c941f9a58a6a128f5a9a49eb2190813625af0d40796b",
    "qwen_development_execution_v3.py": "3b7a2edbe7294b4a420a4db324a51fa6c9520ce81eb665837f5f890dea3202b6",
    "run_qwen_development_v3.py": "6fc992ff3ec3bf7df18fa4574aac16d3df70a548c6e42cef57b929960baf03f8",
}
FORBIDDEN = {"catalog-C.sealed.json", "specs-confirmation.json", "C_STARTED.json", "INPUTS_C.json"}
OMIT = {"__pycache__", ".pytest_cache", ".cache", "venv", "materials", "materials-recovered"}


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def checksum(path):
    require(not path.is_symlink() and stat.S_ISREG(path.lstat().st_mode), "regular nonsymlink bytes required")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            h.update(block)
    return h.hexdigest()


def bounded(root, relative):
    name = PurePosixPath(relative)
    require(name.parts and not name.is_absolute() and ".." not in name.parts
            and str(name) == relative and "\\" not in relative, "bounded relative path required")
    current = root
    for part in name.parts:
        current /= part
        require(not current.is_symlink(), "symlink rejected: " + str(current))
    require(current.resolve().is_relative_to(root), "path escaped artifact root")
    return current


def read(path):
    require(not path.is_symlink() and path.is_file() and path.stat().st_size <= 64 * 1024**2, "bounded regular JSON required")
    return json.loads(path.read_bytes())


def write_new(path, value):
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def walk(root, path):
    mode = path.lstat().st_mode
    require(not stat.S_ISLNK(mode), "symlink rejected: " + str(path))
    require(path.name not in FORBIDDEN, "confirmation member rejected before reading")
    if path.name in OMIT:
        return []
    if stat.S_ISREG(mode):
        return [path]
    require(stat.S_ISDIR(mode), "special file rejected: " + str(path))
    return [p for child in sorted(path.iterdir())
            for p in walk(root, bounded(root, child.relative_to(root).as_posix()))]


def inventory(root, sources):
    result = []
    for path in sorted({p for source in sources for p in walk(root, source)}):
        s = path.stat()
        result.append({"path": path.relative_to(root).as_posix(), "bytes": s.st_size,
                       "sha256": checksum(path), "mode": stat.S_IMODE(s.st_mode),
                       "mtime_ns": s.st_mtime_ns, "device": s.st_dev, "inode": s.st_ino})
    return result


def writer_evidence(root, index_path, helpers, postrun):
    index = read(index_path)
    require(index.get("schema") == "hepta.qwen-export-terminal-observations.v3"
            and index.get("artifact_root") == str(root) and index.get("writers_stopped_confirmed") is True
            and type(index.get("observed_at_ns")) is int and index["observed_at_ns"] > 0,
            "root's confirmed terminal observation index is required")
    rows = index.get("writers", [])
    require(len(rows) == 2 and {r.get("role") for r in rows} == {"e1e2", "postrun"}
            and len({r.get("session_id") for r in rows}) == 2, "both distinct writer observations required")
    retained = [index_path]
    for row in rows:
        output = DEV if row["role"] == "e1e2" else DIAG
        source = helpers / "run_qwen_development_v3.py" if row["role"] == "e1e2" else postrun
        require(row["output_directory"] == output and bounded(root, row["source_path"]) == source
                and checksum(source) == row["source_sha256"], "writer source/output differs")
        path = bounded(root, row["observation_path"])
        require(checksum(path) == row["observation_sha256"], "raw terminal observation changed")
        raw = read(path)
        state = raw.get("status", {})
        require(raw.get("host") == "desktop" and raw.get("session_id") == row["session_id"]
                and state.get("state") == "exited" and type(state.get("exit_code")) is int
                and state.get("output_complete") is True, "authoritative terminal writer status required")
        retained.append(path)
        directory = bounded(root, output)
        require(any((directory / n).is_file() for n in ("RESULT.json", "FAILED.json", "PREPARATION_FAILED.json")),
                "no terminal output artifact; do not archive a live directory")
    processes = bounded(root, DEV + "/processes")
    if processes.exists():
        for directory in processes.iterdir():
            bounded(root, directory.relative_to(root).as_posix())
            if not directory.is_dir() or not (directory / "LAUNCH.json").exists():
                continue
            paths = [p for p in (directory / "EXIT.json", directory / "INTERRUPTED.json") if p.exists()]
            require(len(paths) == 1, "owned child lacks a single terminal receipt")
            child = read(paths[0])
            require(type(child.get("pid")) is int and child["pid"] > 0
                    and type(child.get("exit_code")) is int, "owned child writer not confirmed terminal")
    return retained, index


def partition(path, destination, prefix):
    parts, whole = [], hashlib.sha256()
    with path.open("rb") as source:
        for i, raw in enumerate(iter(lambda: source.read(PART), b"")):
            name = f"{prefix}-{i:05d}.bin"
            with (destination / name).open("xb") as target:
                target.write(raw)
                target.flush()
                os.fsync(target.fileno())
            parts.append({"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
            whole.update(raw)
    require(whole.hexdigest() == checksum(path), "partition source changed")
    restored, size = hashlib.sha256(), 0
    for item in parts:
        raw = (destination / item["path"]).read_bytes()
        require(len(raw) == item["bytes"] and hashlib.sha256(raw).hexdigest() == item["sha256"], "part bytes differ")
        restored.update(raw)
        size += len(raw)
    require(size == path.stat().st_size and restored.hexdigest() == whole.hexdigest(), "parts do not reconstruct original")
    return {"transport_path": path.name, "bytes": size, "sha256": whole.hexdigest(), "parts": parts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    for name in ("helpers", "postrun-source", "terminal-index", "output"):
        parser.add_argument("--" + name, required=True, help="relative path under artifact root")
    args = parser.parse_args()
    root = args.artifact_root
    require(root.is_absolute() and root.resolve() == root and root.is_dir(), "existing nonsymlink absolute root required")
    helpers, postrun = bounded(root, args.helpers), bounded(root, args.postrun_source)
    index_path, output = bounded(root, args.terminal_index), bounded(root, args.output)
    own = Path(__file__).absolute()
    require(own.resolve() == own and own.is_relative_to(root), "archive helper must be retained under artifact root")
    sources = [bounded(root, DEV), bounded(root, DIAG), postrun, own]
    sources.extend(bounded(root, (helpers / name).relative_to(root).as_posix()) for name in HELPERS)
    require(not output.exists(), "export directory exists; do not overwrite or retry into it")
    retained, terminal = writer_evidence(root, index_path, helpers, postrun)
    sources.extend(retained)
    require(all(not output.is_relative_to(p) and not p.is_relative_to(output) for p in sources), "export/source overlap rejected")
    require({name: checksum(helpers / name) for name in HELPERS} == HELPERS, "helpers02 bytes differ")
    freeze, result = root / DEV / "FREEZE.json", root / DIAG / "RESULT.json"
    if freeze.exists():
        require(read(freeze)["helper_inventory"] == HELPERS, "helpers differ from actual execution freeze")
    if result.exists():
        require(read(result)["script_sha256"] == checksum(postrun), "postrun source differs from actual result")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=False)
    started = time.time_ns()
    write_new(output / "STARTED.json", {"started_at_ns": started, "root": str(root), "terminal_index_sha256": checksum(index_path)})
    try:
        members = inventory(root, sources)
        require(members, "empty export rejected")
        index = output / "MEMBERS.jsonl"
        with index.open("xb") as stream:
            for row in members:
                stream.write(canonical(row) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        archive = output / "qwen-e1e2-postrun.zip"
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
            for row in members:
                z.write(bounded(root, row["path"]), row["path"])
        with zipfile.ZipFile(archive) as z:
            require(z.namelist() == [r["path"] for r in members] and z.testzip() is None, "ZIP inventory or CRC differs")
            for row in members:
                h, count = hashlib.sha256(), 0
                with z.open(row["path"]) as stream:
                    for block in iter(lambda: stream.read(1024**2), b""):
                        h.update(block)
                        count += len(block)
                require(count == row["bytes"] and h.hexdigest() == row["sha256"], "ZIP member differs from source")
        manifest = {"schema": "hepta.qwen-final-export.v3", "artifact_root": str(root), "started_at_ns": started,
                    "member_count": len(members), "source_bytes": sum(r["bytes"] for r in members), "part_bytes": PART,
                    "archive": partition(archive, output, "archive-part"), "members": partition(index, output, "members-part"),
                    "terminal_index_sha256": checksum(index_path), "writer_observations": terminal["writers"],
                    "public_base_included": False, "new_C_read": False, "new_model_calls": 0, "new_verifier_calls": 0,
                    "filesystem_atomic_snapshot_claimed": False,
                    "snapshot_basis": "root terminal observations, owned-child terminal receipts, final source byte/stat comparison"}
        require(inventory(root, sources) == members, "source files, paths or metadata changed during export")
        manifest.update(completed_at_ns=time.time_ns(), final_source_recheck_equal=True,
                        zip_crc_and_all_member_hashes_verified=True, all_part_reconstructions_verified=True)
        write_new(output / "TRANSFER_MANIFEST.json", manifest)
        restore = "Concatenate each manifest object's ordered parts into new archive/index files. Verify every part's size/SHA256, then each whole object's size/SHA256. Verify ZIP CRC and every member's path/size/SHA256 against MEMBERS.jsonl before extraction to a new directory. Reject symlinks, traversal, existing targets and special members. Preserve receipt bytes and original absolute paths; do not rewrite them. Base weights, environment and caches are separate dependencies. Git objects ONLY: TRANSFER_MANIFEST.json, RESTORE.txt, archive-part-*.bin and members-part-*.bin. Whole ZIP and MEMBERS.jsonl are transfer-only. STARTED/FAILED are operation evidence, outside that Git object list.\n"
        with (output / "RESTORE.txt").open("x") as stream:
            stream.write(restore)
        git_objects = [output / "TRANSFER_MANIFEST.json", output / "RESTORE.txt"] + [output / p["path"] for key in ("archive", "members") for p in manifest[key]["parts"]]
        require(all(p.stat().st_size < LIMIT for p in git_objects), "proposed Git object exceeds bound")
        print(json.dumps({"status": "EXPORTED_VERIFIED", "output": str(output), "members": len(members),
                          "archive_sha256": manifest["archive"]["sha256"], "git_objects": len(git_objects)}), flush=True)
    except BaseException as error:
        write_new(output / "FAILED.json", {"error": repr(error), "traceback": traceback.format_exc(),
                  "partial_export_preserved": True, "source_modified": False, "automatic_retry": False})
        raise


if __name__ == "__main__":
    main()
