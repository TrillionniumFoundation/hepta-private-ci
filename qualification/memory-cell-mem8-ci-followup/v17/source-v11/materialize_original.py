"""Read the original ZIP and its canonical tar without executing repository code."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import tarfile
import zipfile
import zlib


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def safe(name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name or path.as_posix() != name:
        raise ValueError("unsafe member path")
    return path


def write_new(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def record(path, value):
    write_new(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output
    out.mkdir(exist_ok=False)
    prefix = "mem8-source-gates-v11/"
    root = out / "expanded"
    rows, names = [], set()
    with zipfile.ZipFile(args.zip) as archive:
        if sum(info.file_size for info in archive.infolist()) > 512 * 1024 * 1024:
            raise ValueError("ZIP exceeds read bound")
        for entry in archive.infolist():
            if entry.is_dir():
                safe(entry.filename.rstrip("/"))
                continue
            path = safe(entry.filename)
            if entry.filename in names or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("duplicate or redirected ZIP member")
            names.add(entry.filename)
            raw = archive.read(entry)
            assert len(raw) == entry.file_size and zlib.crc32(raw) & 0xffffffff == entry.CRC
            write_new(root.joinpath(*path.parts), raw)
            rows.append({"path": entry.filename, "crc32": f"{entry.CRC:08x}", **pin(raw)})
    record(out / "ZIP_FULL_MEMBER_AUDIT.json", {"archive": {"path": args.zip.name, **pin(args.zip.read_bytes())}, "member_count": len(rows), "all_lengths_crc_and_sha_checked": True, "members": rows})
    info_path = root / prefix / "ARCHIVE_INFO.json"
    if not info_path.is_file():
        record(out / "CANONICAL_ARCHIVE_MATERIALIZATION.json", {"state": "NO_ORIGINAL_CANONICAL_GATE_ARCHIVE", "source_result": "UNKNOWN_OR_NOT_STARTED; inspect original job and launcher records", "source_or_native_executions_started_by_reader": 0})
        print(json.dumps({"zip_members": len(rows), "canonical_archive": "ABSENT"}))
        return
    info_raw = info_path.read_bytes()
    info = json.loads(info_raw)
    assert info["path"] == "mem8-source-gates-v11-records.tar.xz"
    bundle = root / prefix / info["path"]
    assert pin(bundle.read_bytes()) == {key: info[key] for key in ("bytes", "sha256", "git_blob")}
    canonical = out / "canonical-original"
    canonical.mkdir()
    write_new(canonical / "ARCHIVE_INFO.json", info_raw)
    write_new(canonical / info["path"], bundle.read_bytes())
    tar_names, omitted, directly_equal = set(), [], []
    with tarfile.open(bundle, "r:xz") as archive:
        total = 0
        for member in archive:
            path = safe(member.name)
            if not member.isfile() or member.name in tar_names:
                raise ValueError("duplicate or nonregular tar member")
            total += member.size
            if total > 256 * 1024 * 1024:
                raise ValueError("tar exceeds read bound")
            tar_names.add(member.name)
            raw = archive.extractfile(member).read()
            assert len(raw) == member.size
            write_new(canonical / "records" / path, raw)
            outer = root / prefix / "records" / path
            if outer.is_file():
                assert outer.read_bytes() == raw
                directly_equal.append(member.name)
            else:
                omitted.append(member.name)
    assert len(tar_names) == info["members"]
    expanded_record_names = {str(PurePosixPath(name).relative_to(prefix + "records")) for name in names if name.startswith(prefix + "records/")}
    assert expanded_record_names <= tar_names
    record(out / "CANONICAL_ARCHIVE_MATERIALIZATION.json", {"state": "COMPLETE_ORIGINAL_TAR_READ_AND_MATCHED", "original_archive": info, "tar_members": len(tar_names), "direct_zip_equal_members": len(directly_equal), "direct_zip_omitted_paths": sorted(omitted), "scope": "All original ZIP bytes checked; original complete tar is canonical when upload-artifact omitted hidden expanded source members.", "original_bytes_modified": False, "source_or_native_executions_started_by_reader": 0})
    print(json.dumps({"zip_members": len(rows), "canonical_tar_members": len(tar_names), "expanded_omitted_count": len(omitted), "canonical_root": str(canonical)}))


if __name__ == "__main__":
    main()
