"""Verify the build-only archive preceding the first native owner-CPU measurement."""
import hashlib
from pathlib import Path
import re
import sys
from zipfile import ZipFile

archive = Path(sys.argv[1])
assert hashlib.sha256(archive.read_bytes()).hexdigest() == "c2faa896f9ddb7ca5175f793971eade984a44817c866b2dc97d1a4b7cc550bed"
with ZipFile(archive) as recorded:
    assert recorded.read("observed/ref.txt").decode().strip() == "7258bcd5c214e729c7fc39ba909533684e7b34d9"
    assert int(recorded.read("observed/exit.txt")) != 0
    assert not any(n.endswith(("/test.log", "/test.xml", "/record.json")) for n in recorded.namelist())
    log = recorded.read("observed/console.log").decode(errors="replace")
    assert set(re.findall(r"^error\[(E\d+)\]", log, re.MULTILINE)) == {"E0308"}
    assert "TryLockError" in log and "circuit_task_source_readback.rs:46" in log
print("build-only E0308 verified; native test logs and XMLs: 0")
