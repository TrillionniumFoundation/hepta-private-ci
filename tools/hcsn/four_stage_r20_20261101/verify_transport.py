"""Bounded transport safety controls; no scientific evaluator imports."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile
import tempfile

from restore_evidence import restore


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fixture(root, member_name=None, kind=tarfile.REGTYPE, file_path="result.bin"):
    root.mkdir()
    data = b"retained evidence\n"
    digest = sha(data)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        member = tarfile.TarInfo(member_name or "objects/" + digest)
        member.type = kind
        if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
            member.linkname = "../../outside"
            tar.addfile(member)
        else:
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
    raw = buffer.getvalue()
    compressed = gzip.compress(raw, mtime=0)
    (root / "transport").mkdir()
    (root / "transport/0000.part").write_bytes(compressed)
    map_raw = json.dumps(dict(files=[dict(path=file_path, size=len(data), sha256=digest, mode=0o644)])).encode()
    map_gzip = gzip.compress(map_raw, mtime=0)
    (root / "map_transport").mkdir()
    (root / "map_transport/0000.part").write_bytes(map_gzip)
    manifest = dict(schema="hcsn-evidence-transport-v2", file_count_cap=65536, logical_bytes_cap=512*1024**2,
                    archive=dict(gzip_bytes=len(compressed), gzip_sha256=sha(compressed), raw_bytes=len(raw), raw_sha256=sha(raw),
                                 parts=[dict(path="transport/0000.part", size=len(compressed), sha256=sha(compressed))]),
                    file_map=dict(gzip_bytes=len(map_gzip), gzip_sha256=sha(map_gzip), raw_bytes=len(map_raw), raw_sha256=sha(map_raw),
                                  parts=[dict(path="map_transport/0000.part", size=len(map_gzip), sha256=sha(map_gzip))]))
    (root / "EVIDENCE_TRANSPORT.json").write_text(json.dumps(manifest))
    return data


def main():
    results = []
    with tempfile.TemporaryDirectory(prefix="hcsn-r19-transport-controls-") as temporary:
        base = Path(temporary)
        component = base / "valid"
        data = fixture(component)
        destination = base / "roundtrip"
        restore(component, destination)
        restore(component, destination)
        assert (destination / "result.bin").read_bytes() == data
        results.append(dict(name="roundtrip_and_idempotence", passed=True))
        for name, kwargs in [("entry_traversal", dict(file_path="../escape")),
                             ("tar_traversal", dict(member_name="../escape")),
                             ("symlink_member", dict(kind=tarfile.SYMTYPE)),
                             ("hardlink_member", dict(kind=tarfile.LNKTYPE))]:
            source, target = base / name, base / (name + "-out")
            fixture(source, **kwargs)
            try:
                restore(source, target)
            except (ValueError, OSError, tarfile.TarError) as error:
                results.append(dict(name=name, passed=True, error=str(error)))
            else:
                raise AssertionError(name)
        for name in ["existing_different", "symlink_target", "symlink_parent", "tampered_part", "symlink_part", "symlink_part_parent", "tampered_map", "wrong_map_raw_hash", "oversized_map", "excess_file_count", "logical_size_cap"]:
            source, target = base / name, base / (name + "-out")
            fixture(source, file_path="nested/result.bin")
            target.mkdir()
            if name == "existing_different":
                (target / "nested").mkdir(); (target / "nested/result.bin").write_bytes(b"different")
            elif name == "symlink_target":
                (target / "nested").mkdir(); (target / "nested/result.bin").symlink_to(base / "not-created")
            elif name == "symlink_parent":
                (target / "nested").symlink_to(base / "roundtrip", target_is_directory=True)
            elif name == "tampered_part":
                with (source / "transport/0000.part").open("ab") as output:
                    output.write(b"tampered")
            elif name == "symlink_part":
                part = source / "transport/0000.part"
                outside = base / "outside-part"
                shutil.copyfile(part, outside); part.unlink(); part.symlink_to(outside)
            elif name == "symlink_part_parent":
                folder = source / "transport"; moved = base / "outside-transport"
                folder.rename(moved); folder.symlink_to(moved, target_is_directory=True)
            elif name == "tampered_map":
                with (source / "map_transport/0000.part").open("ab") as output:
                    output.write(b"tampered")
            else:
                manifest = json.loads((source / "EVIDENCE_TRANSPORT.json").read_text())
                if name == "wrong_map_raw_hash":
                    manifest["file_map"]["raw_sha256"] = "0"*64
                elif name == "oversized_map":
                    manifest["file_map"]["raw_bytes"] = 64*1024**2+1
                elif name == "excess_file_count":
                    manifest["file_count_cap"] = 0
                elif name == "logical_size_cap":
                    manifest["logical_bytes_cap"] = 0
                else:
                    raise AssertionError(name)
                (source / "EVIDENCE_TRANSPORT.json").write_text(json.dumps(manifest))
            try:
                restore(source, target)
            except (ValueError, OSError, tarfile.TarError) as error:
                results.append(dict(name=name, passed=True, error=str(error)))
            else:
                raise AssertionError(name)
        assert not (base / "escape").exists()
    result = dict(passed=True, controls=results, source_sha256={name:sha(Path(__file__).with_name(name).read_bytes())
                                                              for name in ("build_transport.py", "restore_evidence.py", "verify_transport.py")})
    Path(__file__).with_name("TRANSPORT_CONTROLS.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
