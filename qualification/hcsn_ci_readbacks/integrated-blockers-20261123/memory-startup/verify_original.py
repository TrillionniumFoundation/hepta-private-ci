"""Check the original startup archive and group the six terminal failures by child."""
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

root = Path(__file__).resolve().parent
archive = root / "original.zip"
expected = "1ebe11429dae4bbdf4b63ad2099f6ea96e4d53c9ced5c2fd089ed31fb4aad9b2"
assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected
with ZipFile(archive) as z:
    for row in z.read("SHA256SUMS").decode().splitlines():
        digest, member = row.split(maxsplit=1)
        assert hashlib.sha256(z.read(member.removeprefix("./"))).hexdigest() == digest
    source = z.read("tested-commit.txt").decode().strip()
    logs = z.read("all-agentd-unit-tests.log").decode()
assert source == "de944cb80e0104c28383aee6ec55b9a43f23606b"
assert "1552 tests run: 1546 passed (1 slow), 6 failed, 171 skipped" in logs
names = {}
pattern = r"^\s*TRY 2 FAIL \[[^\n]*?\] \([^\n]*?\) codex-hepta-agentd (\S+)\n  stdout"
for m in re.finditer(pattern, logs, re.M):
    block = logs[m.end():].split("Cargo/Bazel binary metadata is unavailable", 1)[0]
    assert len(block) < 6500
    cause = re.search(r'(?:could not locate binary|NotFound \{ name:) "(hepta-joint-propose|codex)"', block)
    assert cause and m[1] not in names
    names[m[1]] = cause[1]
assert Counter(names.values()) == {"codex": 1, "hepta-joint-propose": 5}
print(json.dumps(dict(source=source, run=45115542771, job=137497428233, artifact=14792796112,
    archive_sha256=expected, ran=1552, passed=1546, failed=6, skipped_by_original_suite=171,
    missing_children=names), indent=2, sort_keys=True))
