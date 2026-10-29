"""Deterministic, bounded-blob transport for explicitly selected research evidence.

Evidence is never deleted. Directory selection is a whitelist: generated
retained bundles, source/build caches and executable binaries are not discovered
recursively. Exact regular files may be named explicitly. Restore rejects unsafe
paths, links, malformed archives and conflicting existing files.
"""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tarfile
import tempfile


PACKAGE = Path(__file__).resolve().parent
PART_LIMIT = 256000
MANIFEST_LIMIT = 512000
SKIP_DIRS = {"retained",".git","__pycache__",".pytest_cache","target","build",
             "oldsource","old_source","old-source","node_modules"}
BINARY_SUFFIXES = {".exe",".dll",".so",".dylib",".o",".a",".rlib",".pdb"}
SCHEMA = "hepta.first-passage.retained-evidence.v1"


def safe_name(value):
    if (not isinstance(value,str) or not value or "\\" in value or ":" in value
            or any(c in value for c in ("\x00","\r","\n"))):
        raise ValueError("Unsafe evidence path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in (".","..","") for part in value.split("/")):
        raise ValueError("Evidence paths must be canonical relative paths")
    return path.as_posix()


def safe_path(root, name, *, create_parents=False):
    parts = PurePosixPath(safe_name(name)).parts
    current = Path(root)
    for part in parts[:-1]:
        current = current/part
        if current.is_symlink():
            raise ValueError("Symlink ancestor in evidence path")
        if current.exists() and not current.is_dir():
            raise ValueError("Non-directory ancestor in evidence path")
        if create_parents:
            current.mkdir(exist_ok=True)
    target = current/parts[-1]
    if target.is_symlink():
        raise ValueError("Symlink evidence entry")
    return target


def sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda:handle.read(1024*1024),b""):
            digest.update(block)
    return digest.hexdigest()


def _selected_files(root, paths, output, excluded):
    selected,skipped = set(),{}
    excluded = {safe_name(path) for path in excluded}
    output_name = output.relative_to(root).as_posix()
    def omitted(name):
        return any(name == item or name.startswith(item+"/") for item in excluded|{output_name})
    for entry in paths:
        name = safe_name(entry)
        path = safe_path(root,name)
        if omitted(name):
            raise ValueError("An explicit whitelist entry is excluded or is the bundle output")
        if path.is_file():
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError("Only regular evidence files are supported")
            selected.add(name)
        elif path.is_dir():
            if path.name in SKIP_DIRS:
                raise ValueError("Build/source caches require explicit file selection")
            for directory,dirs,files in os.walk(path,followlinks=False):
                parent = Path(directory)
                for child in list(dirs):
                    subpath = parent/child
                    relative = subpath.relative_to(root).as_posix()
                    if subpath.is_symlink():
                        raise ValueError("Symlink inside a whitelisted evidence directory")
                    if child in SKIP_DIRS or omitted(relative):
                        skipped[relative] = "excluded directory"
                        dirs.remove(child)
                for child in files:
                    subpath = parent/child
                    relative = subpath.relative_to(root).as_posix()
                    if subpath.is_symlink() or not stat.S_ISREG(subpath.stat().st_mode):
                        raise ValueError("Non-regular file in whitelisted evidence directory")
                    if omitted(relative):
                        skipped[relative] = "explicit exclusion"
                    elif subpath.suffix.lower() in BINARY_SUFFIXES or subpath.stat().st_mode & 0o111:
                        skipped[relative] = "binary/executable requires explicit file selection"
                    else:
                        selected.add(relative)
        else:
            raise FileNotFoundError(path)
    if not selected:
        raise ValueError("The evidence whitelist selected no files")
    return sorted(selected),skipped


def pack(root, paths, *, name="scientific-evidence", output="evidence/retained",
         part_bytes=PART_LIMIT, excluded=()):
    root = Path(root).resolve()
    paths = list(paths)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}",name) or not 1 <= part_bytes <= PART_LIMIT:
        raise ValueError("Invalid bundle name or piece size")
    destination = safe_path(root,output,create_parents=True)
    destination.mkdir(exist_ok=True)
    files,skipped = _selected_files(root,paths,destination,excluded)
    manifest_path = destination/"manifest.json"
    if manifest_path.exists():
        raise FileExistsError(manifest_path)
    metadata = []
    with tempfile.TemporaryDirectory(prefix="retain-pack-",dir=destination) as temporary:
        archive = Path(temporary)/"archive.tar.gz"
        with archive.open("wb") as raw:
            with gzip.GzipFile(filename="",fileobj=raw,mode="wb",mtime=0,compresslevel=9) as compressed:
                with tarfile.open(fileobj=compressed,mode="w|",format=tarfile.PAX_FORMAT) as tar:
                    for relative in files:
                        path = safe_path(root,relative)
                        before = path.stat()
                        digest = sha_file(path)
                        info = tarfile.TarInfo(relative)
                        info.size,info.mode,info.mtime = before.st_size,0o644,0
                        info.uid,info.gid,info.uname,info.gname = 0,0,"",""
                        with path.open("rb") as handle:
                            tar.addfile(info,handle)
                        after = path.stat()
                        if (before.st_size,before.st_mtime_ns) != (after.st_size,after.st_mtime_ns) or sha_file(path) != digest:
                            raise ValueError("Evidence changed while packing")
                        metadata.append({"path":relative,"bytes":before.st_size,"sha256":digest})
        archive_hash = sha_file(archive)
        pieces = []
        with archive.open("rb") as handle:
            index = 0
            while block := handle.read(part_bytes):
                filename = f"{name}.part{index:03d}"
                if (destination/filename).exists():
                    raise FileExistsError(destination/filename)
                piece = Path(temporary)/filename
                piece.write_bytes(block)
                pieces.append({"path":filename,"bytes":len(block),"sha256":hashlib.sha256(block).hexdigest()})
                index += 1
        manifest = {"schema":SCHEMA,"name":name,"archive":{"format":"tar.gz","bytes":archive.stat().st_size,
                    "sha256":archive_hash},"piece_limit":part_bytes,"pieces":pieces,"files":metadata,
                    "total_file_bytes":sum(row["bytes"] for row in metadata),
                    "selected_paths":list(paths),"excluded_paths":skipped,
                    "restoration_root":"first_passage_adaptive package directory"}
        encoded = (json.dumps(manifest,indent=2,sort_keys=True,allow_nan=False)+"\n").encode()
        if len(encoded) > MANIFEST_LIMIT:
            raise ValueError("Manifest exceeds repository blob limit; use smaller explicit whitelists")
        for piece in pieces:
            with (destination/piece["path"]).open("xb") as handle:
                with (Path(temporary)/piece["path"]).open("rb") as source:
                    shutil.copyfileobj(source,handle)
        with manifest_path.open("xb") as handle:
            handle.write(encoded)
    return {"manifest":str(manifest_path),"manifest_sha256":sha_file(manifest_path),
            "file_count":len(metadata),"piece_count":len(pieces),"archive_sha256":archive_hash,
            "excluded_paths":skipped}


def _unique_object(pairs):
    result = {}
    for key,value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON manifest key")
        result[key] = value
    return result


def load_manifest(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > MANIFEST_LIMIT:
        raise ValueError("Unsafe or oversized evidence manifest")
    data = json.loads(path.read_text(),object_pairs_hook=_unique_object)
    if data.get("schema") != SCHEMA or data["archive"]["format"] != "tar.gz":
        raise ValueError("Unknown evidence manifest schema")
    limit = data["piece_limit"]
    if isinstance(limit,bool) or not isinstance(limit,int) or not 1 <= limit <= PART_LIMIT:
        raise ValueError("Invalid evidence piece limit")
    for kind in ("files","pieces"):
        seen = set()
        if not isinstance(data[kind],list) or not data[kind]:
            raise ValueError("Empty or invalid evidence manifest entries")
        for row in data[kind]:
            name = safe_name(row["path"])
            if name in seen or (kind == "pieces" and len(PurePosixPath(name).parts) != 1):
                raise ValueError("Duplicate or nested evidence entry")
            seen.add(name)
            size = row["bytes"]
            if isinstance(size,bool) or not isinstance(size,int) or size < 0 or (kind == "pieces" and not 0 < size <= limit):
                raise ValueError("Invalid evidence entry size")
            if not re.fullmatch(r"[0-9a-f]{64}",row["sha256"]):
                raise ValueError("Invalid evidence digest")
    if (sum(row["bytes"] for row in data["pieces"]) != data["archive"]["bytes"]
            or sum(row["bytes"] for row in data["files"]) != data["total_file_bytes"]
            or not re.fullmatch(r"[0-9a-f]{64}",data["archive"]["sha256"])):
        raise ValueError("Evidence manifest totals do not match")
    return data


def _verified_archive(manifest_path, data, temporary, staging=None):
    archive = Path(temporary)/"archive.tar.gz"
    overall = hashlib.sha256()
    with archive.open("xb") as combined:
        for piece in data["pieces"]:
            path = safe_path(Path(manifest_path).parent,piece["path"])
            if not path.is_file() or path.stat().st_size != piece["bytes"] or sha_file(path) != piece["sha256"]:
                raise ValueError("Evidence piece hash/size mismatch")
            with path.open("rb") as handle:
                block = handle.read(PART_LIMIT+1)
            overall.update(block)
            combined.write(block)
    if overall.hexdigest() != data["archive"]["sha256"]:
        raise ValueError("Evidence archive digest mismatch")
    expected = {row["path"]:row for row in data["files"]}
    seen = set()
    with tarfile.open(archive,mode="r|gz") as tar:
        for member in tar:
            name = safe_name(member.name)
            if (name not in expected or name in seen or member.type not in (tarfile.REGTYPE,tarfile.AREGTYPE)
                    or member.linkname or member.size != expected[name]["bytes"]):
                raise ValueError("Unexpected, linked or duplicate evidence archive member")
            seen.add(name)
            digest = hashlib.sha256()
            source = tar.extractfile(member)
            target = safe_path(staging,name,create_parents=True) if staging is not None else None
            output = target.open("xb") if target is not None else None
            try:
                for block in iter(lambda:source.read(1024*1024),b""):
                    digest.update(block)
                    if output is not None:
                        output.write(block)
            finally:
                source.close()
                if output is not None:
                    output.close()
            if digest.hexdigest() != expected[name]["sha256"]:
                raise ValueError("Archived evidence file digest mismatch")
    if seen != set(expected):
        raise ValueError("Evidence archive omitted declared files")


def _existing(root, data, *, require_all):
    present = []
    for row in data["files"]:
        path = safe_path(root,row["path"])
        if path.exists():
            if not path.is_file() or path.stat().st_size != row["bytes"] or sha_file(path) != row["sha256"]:
                raise FileExistsError(f"Conflicting evidence file: {row['path']}")
            present.append(row["path"])
        elif require_all:
            raise FileNotFoundError(path)
    return set(present)


def check(root, manifest_path, *, restored_only=False, include_restored=False):
    root,manifest_path = Path(root).resolve(),Path(manifest_path)
    data = load_manifest(manifest_path)
    if not restored_only:
        with tempfile.TemporaryDirectory(prefix="retain-check-") as temporary:
            _verified_archive(manifest_path,data,temporary)
    if restored_only or include_restored:
        _existing(root,data,require_all=True)
    return {"status":"verified","file_count":len(data["files"]),"archive_sha256":data["archive"]["sha256"],
            "packed_verified":not restored_only,"restored_verified":restored_only or include_restored}


def restore(root, manifest_path):
    root,manifest_path = Path(root).resolve(),Path(manifest_path)
    root.mkdir(parents=True,exist_ok=True)
    data = load_manifest(manifest_path)
    present = _existing(root,data,require_all=False)
    with tempfile.TemporaryDirectory(prefix="retain-restore-",dir=root) as temporary:
        staging = Path(temporary)/"files"
        staging.mkdir()
        _verified_archive(manifest_path,data,temporary,staging)
        # Recheck every existing destination before creating any final file.
        present = _existing(root,data,require_all=False)
        for row in data["files"]:
            if row["path"] not in present:
                target = safe_path(root,row["path"],create_parents=True)
                with target.open("xb") as output:
                    with (staging/row["path"]).open("rb") as source:
                        shutil.copyfileobj(source,output)
    _existing(root,data,require_all=True)
    return {"status":"restored","created":len(data["files"])-len(present),"already_identical":len(present),
            "file_count":len(data["files"]),"archive_sha256":data["archive"]["sha256"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",default=str(PACKAGE))
    commands = parser.add_subparsers(dest="command",required=True)
    packing = commands.add_parser("pack")
    packing.add_argument("paths",nargs="*")
    packing.add_argument("--pathsfile")
    packing.add_argument("--name",default="scientific-evidence")
    packing.add_argument("--output",default="evidence/retained")
    packing.add_argument("--exclude",action="append",default=[])
    for command in ("restore","check"):
        action = commands.add_parser(command)
        action.add_argument("--manifest")
        if command == "check":
            action.add_argument("--restored-only",action="store_true")
            action.add_argument("--include-restored",action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if args.command == "pack":
        paths = list(args.paths)
        if args.pathsfile:
            content = Path(args.pathsfile).read_text().strip()
            paths.extend(json.loads(content) if content.startswith("[") else
                         [line.strip() for line in content.splitlines() if line.strip() and not line.lstrip().startswith("#")])
        result = pack(root,paths,name=args.name,output=args.output,excluded=args.exclude)
    else:
        supplied = args.manifest or "evidence/retained/manifest.json"
        manifest = Path(supplied)
        if not manifest.is_absolute():
            manifest = (manifest.resolve() if args.manifest and manifest.is_file()
                        else safe_path(root,supplied))
        result = (restore(root,manifest) if args.command == "restore" else
                  check(root,manifest,restored_only=args.restored_only,include_restored=args.include_restored))
    print(json.dumps(result,indent=2,sort_keys=True))


if __name__ == "__main__":
    main()
