"""Verify the original 289 MB startup artifact without executing either child binary."""
import argparse
import hashlib
import json
import struct
import tarfile
from pathlib import Path
from zipfile import ZipFile
import zstandard

expected_archive = "15b9787b6ece195417ca6737fe8d9f3aa6bd9322dfa05b1d2c5dbf08caea79fe"
source = "c6a3ed9c36f88707d2f29630efe1e3ea4ee0e902"

def elf_entry(f):
    head = f.read(64)
    assert head[:7] == b"\x7fELF\x02\x01\x01" and struct.unpack_from("<H",head,18)[0] == 62
    digest = hashlib.sha256(head)
    size = len(head)
    for chunk in iter(lambda: f.read(1 << 20), b""):
        size += len(chunk)
        digest.update(chunk)
    return {"machine": "x86-64", "bytes": size, "sha256": digest.hexdigest()}

def check(path):
    with path.open("rb") as f:
        assert hashlib.file_digest(f, "sha256").hexdigest() == expected_archive
    with ZipFile(path) as archive:
        sums = {name: digest for digest,name in (line.split() for line in archive.read("SHA256SUMS").decode().splitlines())}
        assert set(sums) == set(archive.namelist())-{"SHA256SUMS","source.txt"}
        assert archive.read("source.txt").decode().strip() == source
        records = {}
        for name in sums:
            with archive.open(name) as f:
                if name in ("codex", "hepta-joint-propose"):
                    records[name] = elf_entry(f)
                    digest = records[name]["sha256"]
                else:
                    digest = hashlib.file_digest(f, "sha256").hexdigest()
            assert digest == sums[name], name
        suites = json.loads(archive.read("source-list.json"))["rust-suites"]
        assert list(suites) == ["codex-hepta-agentd"]
        suite = next(iter(suites.values()))
        assert (suite["status"], suite["kind"]) == ("listed", "lib")
        cases = suite["testcases"]
        n_active = sum(not r["ignored"] and r["filter-match"]["status"]=="matches" for r in cases.values())
        assert (len(cases),n_active)==(1723,1552)
        release = archive.read("nextest-version.txt").decode().splitlines()[0]
        with archive.open("agentd-lib.tar.zst") as f, zstandard.ZstdDecompressor().stream_reader(f) as stream:
            with tarfile.open(fileobj=stream, mode="r|") as tar:
                members, native = set(), {}
                for member in tar:
                    assert member.name not in members
                    members.add(member.name)
                    if member.name.startswith("target/debug/deps/codex_hepta_agentd-"):
                        assert member.isfile() and member.mode & 0o111
                        native[member.name] = elf_entry(tar.extractfile(member))
                        assert native[member.name]["bytes"] == member.size
                assert len(members)==109 and len(native)==1
                assert {"target/nextest/cargo-metadata.json","target/nextest/binaries-metadata.json"} <= members
    return {"run":45125165645,"job":137527725126,"artifact":14796807476,"archive_bytes":path.stat().st_size,
            "archive_sha256":expected_archive,"source":source,"roster_size":len(cases),"selected":n_active,
            "ignored":sum(r["ignored"] for r in cases.values()),"archive_member_count":len(members),
            "native_test_binary":native,"child_processes":records,"native_tool":release,"manifest":sums}

if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip", type=Path)
    print(json.dumps(check(parser.parse_args().zip),indent=2,sort_keys=True))
