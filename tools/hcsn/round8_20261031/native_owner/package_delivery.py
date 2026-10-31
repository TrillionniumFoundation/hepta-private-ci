"""Package raw revalidation files and hash the exact readable delivery set."""
import gzip
import hashlib
import json
from pathlib import Path
import tarfile

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "evidence"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    archive = EVIDENCE / "RAW_REVALIDATION_20261031.tar.gz"
    groups = ("qualification-revalidation-20261031", "qualification-content-20261031")
    rows = []
    with archive.open("xb") as stream:
        with gzip.GzipFile(fileobj=stream, mode="wb", filename="", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as output:
                for group in groups:
                    for path in sorted((EVIDENCE / group).rglob("*")):
                        if not path.is_file():
                            continue
                        if path.is_symlink():
                            raise ValueError("Evidence archives must contain regular files")
                        identity = sha(path)
                        name = str(path.relative_to(EVIDENCE))
                        info = output.gettarinfo(str(path), arcname=name)
                        info.uid = info.gid = info.mtime = 0
                        info.uname = info.gname = ""
                        with path.open("rb") as content:
                            output.addfile(info, content)
                        if sha(path) != identity:
                            raise ValueError("Evidence changed during packaging")
                        rows.append(dict(path=name, bytes=path.stat().st_size, sha256=identity))
    with tarfile.open(archive, "r:gz") as check:
        for row in rows:
            data = check.extractfile(row["path"]).read()
            if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise ValueError("Archive readback mismatch")
    manifest = dict(schema="hcsn.native-raw-revalidation.v1", archive=archive.name,
        archive_sha256=sha(archive), archive_bytes=archive.stat().st_size,
        member_paths_relative_to="native_owner/evidence", members=rows,
        all_members_readback_verified=True,
        repeated_qualification_is_not_new_independent_sample_evidence=True)
    (EVIDENCE / "RAW_RECORDS_MANIFEST_REVALIDATION_20261031.json").write_text(json.dumps(manifest, indent=2)+"\n")
    selected = [p for p in HERE.iterdir() if p.is_file() and p.name != "DELIVERY_MANIFEST_CURRENT.json"]
    selected += [p for p in EVIDENCE.iterdir() if p.is_file()]
    for path in EVIDENCE.iterdir():
        if path.is_dir() and (path.name.startswith("qualification-") or path.name.startswith("source-")):
            selected += [p for p in path.iterdir() if p.is_file()]
    files = {str(p.relative_to(HERE)): dict(bytes=p.stat().st_size, sha256=sha(p)) for p in sorted(selected)}
    build = json.loads((EVIDENCE / "BUILD_REVALIDATION_20261031.json").read_text())
    final = dict(schema="hcsn.native-owner-delivery.v2", canonical_source_digest=build["source_digest"],
        canonical_binary_sha256=build["binary_sha256"], build="evidence/BUILD_REVALIDATION_20261031.json",
        qualification="evidence/qualification-revalidation-20261031/REPORT.json",
        content_qualification="evidence/qualification-content-20261031/REPORT.json", files=files,
        canonical_manifest="DELIVERY_MANIFEST_CURRENT.json",
        historical_manifest="DELIVERY_MANIFEST.json is an unchanged superseded 456a-release record",
        raw_archives=["evidence/RAW_NATIVE_EVIDENCE.tar.gz", "evidence/RAW_NATIVE_EVIDENCE_TAILFIX.tar.gz", "evidence/RAW_REVALIDATION_20261031.tar.gz"],
        content_dependencies="CONTENT_SOURCE_IDENTITY.json; all six are already in base 3a0e62c",
        bootstrap_inputs="Base native_task_bridge_20261031/build.py is Git-blob-verified; owner native-Cargo.lock is recovered from its own successful Cargo report and SHA256-verified",
        omit_expanded_raw_members_from_upload=True, production_activation=False)
    (HERE / "DELIVERY_MANIFEST_CURRENT.json").write_text(json.dumps(final, indent=2)+"\n")
    print(json.dumps(dict(files=len(files), bytes=sum(x["bytes"] for x in files.values()),
                         raw_members=len(rows), archive_bytes=archive.stat().st_size)))


if __name__ == "__main__":
    main()
