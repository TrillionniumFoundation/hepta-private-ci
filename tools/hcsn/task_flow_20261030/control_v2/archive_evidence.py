"""Lossless evidence packaging after the frozen prospective study is complete."""
import json
import time
import zipfile
from identity import HERE, save, sha, verify


def inventories():
    development = json.loads((HERE / "development_manifest.json").read_text())["files"]
    heldout = json.loads((HERE / "heldout_manifest.json").read_text())["files"]
    rows = json.loads((HERE / "confirmation.json").read_text())["rows"]
    training = json.loads((HERE / "training_manifest.json").read_text())["files"]
    return {"raw_development.zip": development, "raw_heldout.zip": heldout,
            "raw_traces.zip": {r["trace"]: r["trace_sha256"] for r in rows},
            "raw_training.zip": training}


def training_manifest():
    files = {str(path.relative_to(HERE)): sha(path) for folder in ("runs", "states")
             for path in sorted((HERE / folder).rglob("*")) if path.is_file()}
    assert len(files) == 245 and not any(name.endswith(".partial") for name in files)
    result = dict(files=files, development_results_sha256=sha(HERE / "development_results.json"),
        description="All 180 candidate checkpoints, 15 update logs, 15 run records, 15 selected-validation predictions and 20 state/provenance files; no omitted candidate or replacement run")
    target = HERE / "training_manifest.json"
    if target.exists():
        assert result == json.loads(target.read_text())
    else:
        save(target, result)


def pack():
    verify()
    start = time.perf_counter()
    training_manifest()
    previous = HERE / "evidence_archives.json"
    old = {r["path"]: r for r in json.loads(previous.read_text())["archives"]} if previous.exists() else {}
    rows = []
    for name, files in inventories().items():
        target = HERE / name
        temporary = target.with_suffix(".partial")
        raw_bytes = sum((HERE / relative).stat().st_size for relative in files)
        for relative, expected in files.items():
            assert sha(HERE / relative) == expected, relative
        if target.exists():
            assert name in old and sha(target) == old[name]["sha256"], name
            candidate = target
        else:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for relative in sorted(files):
                    payload = (HERE / relative).read_bytes()
                    entry = zipfile.ZipInfo(relative, date_time=(2026, 10, 30, 0, 0, 0))
                    entry.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(entry, payload, compresslevel=9)
            candidate = temporary
        with zipfile.ZipFile(candidate) as archive:
            import hashlib
            assert len(archive.namelist()) == len(set(archive.namelist())) == len(files)
            assert set(archive.namelist()) == set(files)
            for relative, expected in files.items():
                assert hashlib.sha256(archive.read(relative)).hexdigest() == expected, relative
        if candidate == temporary:
            temporary.replace(target)
        rows.append(dict(path=name, files=len(files), bytes=target.stat().st_size,
                         uncompressed_bytes=raw_bytes, sha256=sha(target)))
    manifest = dict(archives=rows, original_unpacked_data_retained=True,
        meaning="Every closed ZIP member independently compared with the original per-file scientific manifest; source data and scientific results unchanged",
        bound_files_sha256={name: sha(HERE / name) for name in
            ("freeze.json", "development_manifest.json", "heldout_manifest.json", "training_manifest.json", "confirmation.json", "completion.json")},
        archive_source_sha256=sha(HERE / "archive_evidence.py"),
        restore_source_sha256=sha(HERE / "restore_evidence.py"))
    save(HERE / "evidence_archives.json", manifest)
    save(HERE / "packaging_receipt.json", dict(passed=True, wall_seconds=time.perf_counter()-start,
        archive_count=len(rows), members=sum(r["files"] for r in rows),
        archive_bytes=sum(r["bytes"] for r in rows), manifest_sha256=sha(HERE / "evidence_archives.json")))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    pack()
