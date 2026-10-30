"""Compact only exact verified raw duplicates, even with very little disk space."""
import hashlib
import json
import os
from pathlib import Path
import zipfile
from common import HERE, save, sha, verify
from pack_evidence import expected


def validate(archive, files):
    with zipfile.ZipFile(archive) as source:
        assert len(source.namelist()) == len(set(source.namelist())) == len(files)
        assert set(source.namelist()) == set(files)
        for relative, digest in files.items():
            assert hashlib.sha256(source.read(relative)).hexdigest() == digest


def run():
    verify()
    records = []
    chunks = HERE / "packaging_chunks"
    chunks.mkdir(exist_ok=True)
    for archive_name, files in expected().items():
        group = archive_name.removesuffix(".zip")
        stored, total_uncompressed = {}, 0
        existing = sorted(chunks.glob(group + "_*.zip"))
        for part in existing:
            with zipfile.ZipFile(part) as reader:
                member_hashes = {name: files[name] for name in reader.namelist()}
            validate(part, member_hashes)
            for name in member_hashes:
                assert name not in stored
                stored[name] = part
        pending = [name for name in sorted(files) if name not in stored]
        cursor, number = 0, len(existing)
        while cursor < len(pending):
            available = os.statvfs(HERE).f_bavail * os.statvfs(HERE).f_frsize
            count = 8 if available < 1024*1024 else 128
            names = pending[cursor:cursor+count]
            part = chunks / f"{group}_{number:05d}.zip"
            try:
                with zipfile.ZipFile(part, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as writer:
                    for name in names:
                        assert sha(HERE / name) == files[name]
                        writer.write(HERE / name, arcname=name)
                with part.open("rb") as handle:
                    os.fsync(handle.fileno())
                validate(part, {name: files[name] for name in names})
            except Exception:
                # No source copy is removed before complete validation.
                if part.exists():
                    part.unlink()
                raise
            for name in names:
                (HERE / name).unlink()
                stored[name] = part
            cursor, number = cursor+len(names), number+1
        # Previously verified parts may coexist with duplicate originals after a prior interruption.
        for name in stored:
            original = HERE / name
            if original.exists():
                assert sha(original) == files[name]
                original.unlink()
        target = HERE / archive_name
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as writer:
            for part in sorted(set(stored.values())):
                with zipfile.ZipFile(part) as reader:
                    for name in reader.namelist():
                        raw = reader.read(name)
                        assert hashlib.sha256(raw).hexdigest() == files[name]
                        total_uncompressed += len(raw)
                        info = zipfile.ZipInfo(name, date_time=(2026, 10, 30, 0, 0, 0))
                        info.compress_type = zipfile.ZIP_DEFLATED
                        info.external_attr = 0o644 << 16
                        writer.writestr(info, raw, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        with target.open("rb") as handle:
            os.fsync(handle.fileno())
        validate(target, files)
        for part in set(stored.values()):
            part.unlink()
        records.append(dict(path=archive_name, sha256=sha(target), files=len(files),
                            bytes=target.stat().st_size, uncompressed_bytes=total_uncompressed))
        print(group, len(files), "verified", flush=True)
    save(HERE / "evidence_archives.json", dict(archives=records,
        data_manifest_sha256=sha(HERE / "data_manifest.json"), results_sha256=sha(HERE / "results.json"),
        source_sha256=sha(HERE / "compact_evidence.py"),
        restoration_source_sha256=sha(HERE / "restore_evidence.py"),
        meaning="All raw bytes verified in closed chunks before unpacked duplicates were removed; consolidated archives independently reverified"))
    save(HERE / "packaging_receipt.json", dict(passed=True,
        initial_failure="Whole ZIP central-directory write failed with ENOSPC; incomplete archive removed, scientific source and result hashes unchanged",
        recovery="Only own reproducible Python cache removed, then own raw duplicate files compacted after complete per-chunk verification",
        raw_files=len(expected()["raw_data.zip"])+len(expected()["raw_traces.zip"]),
        originals_removed_only_after_verified_archive=True,
        final_archive_manifest_sha256=sha(HERE / "evidence_archives.json")))


if __name__ == "__main__":
    run()
