"""Freeze real node-local Git objects or source trees into registered snapshots.

Only the new output directory is written. Repository worktrees are not changed.
The modes report their own CPU/wall costs so packing can be charged only to
the centralized-copy arm instead of disappearing into common setup.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import stat
import tarfile
import time


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def safe_path(value):
    path = PurePosixPath(value)
    return bool(value) and len(value.encode("utf-8")) <= 1024 and not path.is_absolute() and all(part not in ("", ".", "..") for part in value.split("/")) and "\\" not in value and not any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)


def tree_digest(files):
    value = bytearray(b"hepta.source-tree-content.v1\0")
    for entry in files:
        name = entry["path"].encode("utf-8")
        value.extend(len(name).to_bytes(8, "little")); value.extend(name)
        value.extend(entry["bytes"].to_bytes(8, "little")); value.extend(bytes.fromhex(entry["sha256"]))
    return hashlib.sha256(value).hexdigest()


def fingerprint(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def tree_inventory(root):
    selected, total, visited = {}, 0, 0
    def fail(error):
        raise error
    for directory, children, files in os.walk(root, followlinks=False, onerror=fail):
        visited += 1
        if visited > 20000:
            raise ValueError("source directory inventory bound")
        children[:] = sorted(name for name in children if name not in (".git", ".venv", "target", "node_modules", "__pycache__"))
        for name in children:
            if (Path(directory) / name).is_symlink():
                raise ValueError("source directory symlink refused")
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix not in (".rs", ".py", ".toml", ".md", ".lock"):
                continue
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            if not safe_path(relative) or not stat.S_ISREG(info.st_mode) or info.st_size > 4 * 1024 * 1024:
                raise ValueError("bounded nonsymlink source file required")
            total += info.st_size
            selected[relative] = fingerprint(info)
            if len(selected) > 4096 or total > 64 * 1024 * 1024:
                raise ValueError("source-tree file/byte budget exceeded")
    if not selected:
        raise ValueError("source tree selected no files")
    return dict(sorted(selected.items()))


def read_tree_file(root, relative, expected):
    """Open each path component without following symlinks, then check stability."""
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = relative.split("/")
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor); descriptor = child
        source = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
        with os.fdopen(source, "rb") as stream:
            if fingerprint(os.fstat(stream.fileno())) != expected:
                raise ValueError("source changed before copy")
            content = stream.read(expected[3] + 1)
            if len(content) != expected[3] or fingerprint(os.fstat(stream.fileno())) != expected:
                raise ValueError("source changed during copy")
            return content
    finally:
        os.close(descriptor)


def freeze_tree(args):
    started, cpu = time.perf_counter(), time.process_time()
    if args.source_root.is_symlink():
        raise ValueError("source root symlink refused")
    root = args.source_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("source directory required")
    before = tree_inventory(root)
    args.output.mkdir(parents=True, exist_ok=False)
    destination = args.output / "source"; destination.mkdir()
    files, seen = [], set()
    for relative, expected in before.items():
        content = read_tree_file(root, relative, expected)
        digest = hashlib.sha256(content).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        target = destination / relative; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        files.append({"path":relative, "bytes":len(content), "sha256":digest})
    if before != tree_inventory(root):
        raise ValueError("source tree changed before snapshot completion")
    identity = tree_digest(files)
    manifest = {"schema":"hepta.source-shard-manifest.v2", "source_commit":None,
                "source_tree_sha256":identity, "files":files}
    payload = encoded(manifest); (args.output / "manifest.json").write_bytes(payload)
    receipt = {"schema":"hepta.source-shard-freeze.v2", "source_root":str(root), "source_commit":None,
               "source_tree_sha256":identity, "manifest_sha256":hashlib.sha256(payload).hexdigest(),
               "selected_source_entries":len(before), "files":len(files), "source_bytes":sum(entry["bytes"] for entry in files),
               "duplicate_contents_excluded":len(before)-len(files), "before_after_inventory_equal":True,
               "real_node_local_source_tree":True, "synthetic_repeated_data":False,
               "cpu_seconds":time.process_time()-cpu, "wall_seconds":time.perf_counter()-started,
               "identity_scope":"bounded selected source extensions, excluding build/cache directories; no upstream commit asserted"}
    (args.output / "FREEZE.json").write_bytes(encoded(receipt)); print(json.dumps(receipt, sort_keys=True))


def freeze(args):
    started, cpu = time.perf_counter(), time.process_time()
    repo = args.repo.resolve(strict=True)
    git_environment = {**os.environ, "GIT_NO_LAZY_FETCH":"1", "GIT_OPTIONAL_LOCKS":"0"}
    commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "--verify", args.commit + "^{commit}"], text=True, env=git_environment).strip()
    if len(commit) != 40:
        raise ValueError("fixed forty-character source commit required")
    raw = subprocess.check_output(["git", "-C", str(repo), "ls-tree", "-rz", "--full-tree", commit, "--", *args.prefix], env=git_environment)
    entries = []
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        header, path = entry.split(b"\t", 1)
        mode, kind, identity = header.decode().split()
        name = path.decode("utf-8")
        if mode not in ("100644", "100755") or kind != "blob" or not safe_path(name):
            continue
        if PurePosixPath(name).suffix not in (".rs", ".py", ".toml", ".md", ".lock"):
            continue
        entries.append((name, identity))
    args.output.mkdir(parents=True, exist_ok=False)
    source = args.output / "source"; source.mkdir()
    files, seen, total, excluded = [], set(), 0, 0
    process = subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=git_environment)
    try:
        for name, identity in sorted(entries):
            if identity in seen:
                excluded += 1; continue
            process.stdin.write((identity + "\n").encode()); process.stdin.flush()
            header = process.stdout.readline().decode().split()
            if len(header) != 3 or header[1] != "blob":
                raise ValueError("Git blob read failed")
            count = int(header[2])
            if count > 4 * 1024 * 1024:
                remaining = count
                while remaining:
                    chunk = process.stdout.read(min(remaining, 65536))
                    if not chunk:
                        raise ValueError("oversized Git blob truncated")
                    remaining -= len(chunk)
                if process.stdout.read(1) != b"\n":
                    raise ValueError("Git blob framing differs")
                excluded += 1; continue
            content = process.stdout.read(count)
            if len(content) != count or process.stdout.read(1) != b"\n":
                raise ValueError("Git blob truncated")
            if count > 4 * 1024 * 1024 or total + count > 64 * 1024 * 1024 or len(files) >= 4096:
                excluded += 1; continue
            seen.add(identity)
            target = source / name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            files.append({"path":name, "bytes":count, "sha256":hashlib.sha256(content).hexdigest()})
            total += count
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait()
        process.stdout.close(); process.stderr.close()
    if process.returncode or not files:
        raise RuntimeError("source freeze failed or selected no files")
    manifest = {"schema":"hepta.source-shard-manifest.v1", "source_commit":commit, "files":files}
    payload = encoded(manifest); (args.output / "manifest.json").write_bytes(payload)
    receipt = {"schema":"hepta.source-shard-freeze.v1", "source_repository":str(repo), "source_commit":commit,
               "manifest_sha256":hashlib.sha256(payload).hexdigest(), "files":len(files), "source_bytes":total,
               "excluded_duplicate_or_bounded_files":excluded, "prefixes":args.prefix,
               "real_node_local_git_objects":True, "synthetic_repeated_data":False,
               "cpu_seconds":time.process_time()-cpu, "wall_seconds":time.perf_counter()-started,
               "cost_boundary":"snapshot extraction only; Git child CPU is reported by the outer process receipt"}
    (args.output / "FREEZE.json").write_bytes(encoded(receipt)); print(json.dumps(receipt, sort_keys=True))


def pack(args):
    started, cpu = time.perf_counter(), time.process_time()
    manifest = json.loads((args.snapshot / "manifest.json").read_bytes())
    if args.output.exists():
        raise FileExistsError(args.output)
    with tarfile.open(args.output, "w:gz", compresslevel=1) as archive:
        for entry in manifest["files"]:
            if not safe_path(entry["path"]):
                raise ValueError("invalid registered archive path")
            path = args.snapshot / "source" / entry["path"]
            if not path.is_file() or path.is_symlink() or path.stat().st_size != entry["bytes"]:
                raise ValueError("source changed before packaging")
            archive.add(path, arcname=entry["path"], recursive=False)
    receipt = {"schema":"hepta.source-shard-pack.v1", "archive":str(args.output),
               "archive_sha256":hashlib.sha256(args.output.read_bytes()).hexdigest(), "archive_bytes":args.output.stat().st_size,
               "cpu_seconds":time.process_time()-cpu, "wall_seconds":time.perf_counter()-started,
               "cost_arm":"centralized-copy setup; compression level 1"}
    args.output.with_suffix(args.output.suffix + ".receipt.json").write_bytes(encoded(receipt))
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="mode", required=True)
    freezing = commands.add_parser("freeze")
    freezing.add_argument("--repo", type=Path, required=True)
    freezing.add_argument("--commit", required=True)
    freezing.add_argument("--prefix", action="append", default=[])
    freezing.add_argument("--output", type=Path, required=True)
    tree = commands.add_parser("freeze-tree")
    tree.add_argument("--source-root", type=Path, required=True)
    tree.add_argument("--output", type=Path, required=True)
    packing = commands.add_parser("pack")
    packing.add_argument("--snapshot", type=Path, required=True)
    packing.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    {"freeze":freeze, "freeze-tree":freeze_tree, "pack":pack}[args.mode](args)
