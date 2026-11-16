"""Package exact metadata bytes with immutable input and ZIP-member identities."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import zipfile


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    config_path, output = map(Path, sys.argv[1:3])
    config_raw = config_path.read_bytes()
    config = json.loads(config_raw)
    output.mkdir(exist_ok=False)
    rows, source_bytes = {}, {}
    for row in config["files"]:
        path, name = Path(row["source"]), row["destination"]
        relative = PurePosixPath(name)
        assert path.is_file() and not path.is_symlink()
        assert not relative.is_absolute() and ".." not in relative.parts and "\\" not in name
        assert name not in rows and not name.endswith("/")
        raw = path.read_bytes()
        assert identity(raw) == {k: row[k] for k in ("bytes", "sha256")}
        rows[name], source_bytes[str(path)] = raw, raw
    rows["CONFIG.json"] = config_raw
    rows["package_metadata_handoff_v1.py"] = Path(__file__).read_bytes()
    manifest = {name: identity(raw) for name, raw in sorted(rows.items())}
    manifest_raw = (json.dumps({"schema": "hcsn-metadata-capsule-members-v1", "files": manifest}, indent=2) + "\n").encode()
    rows["MEMBERS.json"] = manifest_raw
    archive_path = output / "ORIGINALS.zip"
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, raw in sorted(rows.items()):
            archive.writestr(name, raw)
    assert archive_path.stat().st_size <= 500000
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None and set(archive.namelist()) == set(rows)
        assert all(archive.read(name) == raw for name, raw in rows.items())
    assert all(Path(path).read_bytes() == raw for path, raw in source_bytes.items())
    assert config_path.read_bytes() == config_raw
    (output / "MEMBERS.json").write_bytes(manifest_raw)
    receipt = {"schema": "hcsn-exact-metadata-capsule-v1", "archive": identity(archive_path.read_bytes()),
               "members": len(rows), "CRC_and_member_bytes_verified": True, "original_inputs_unchanged": True,
               "source": identity(Path(__file__).read_bytes()), "config": identity(config_raw),
               "scope": config["scope"], "compute_cost_scope": "Complete packaging child costs recorded externally; original nested costs are not summed."}
    (output / "RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
