"""Losslessly package raw files without changing scientific outcomes."""
import json
from pathlib import Path
import zipfile
from common import HERE, save, sha, verify


def expected():
    data = json.loads((HERE / "data_manifest.json").read_text())["files"]
    rows = json.loads((HERE / "results.json").read_text())["rows"]
    traces = {row["trace"]: row["trace_sha256"] for row in rows}
    return {"raw_data.zip": data, "raw_traces.zip": traces}


def run():
    verify()
    records = []
    for archive_name, files in expected().items():
        target = HERE / archive_name
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for relative, digest in sorted(files.items()):
                source = HERE / relative
                assert sha(source) == digest
                info = zipfile.ZipInfo(relative, date_time=(2026, 10, 30, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        records.append(dict(path=archive_name, sha256=sha(target), files=len(files),
                            bytes=target.stat().st_size,
                            uncompressed_bytes=sum((HERE / name).stat().st_size for name in files)))
    save(HERE / "evidence_archives.json", dict(archives=records,
        data_manifest_sha256=sha(HERE / "data_manifest.json"), results_sha256=sha(HERE / "results.json"),
        source_sha256=sha(HERE / "pack_evidence.py"),
        restoration_source_sha256=sha(HERE / "restore_evidence.py"),
        meaning="Exact raw bytes retained; original per-file identities and outcomes unchanged"))
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    run()
